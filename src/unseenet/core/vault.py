"""Encrypted client vault (UN-RFC 0007, section 2)."""

from __future__ import annotations

import atexit
import errno
import glob
import hmac
import json
import os
import socket
import struct
import sys
import tempfile
import threading
from pathlib import Path

import base64
import time

import nacl.encoding
import nacl.exceptions
import nacl.hash
import nacl.pwhash
import nacl.secret

MAGIC = b"UNSVAULT1"
SIDECAR_MAGIC = b"UNSSIDE1"
UNLOCK_NAME = "unlock"                    # <vault>.unlock: device unlocks (UN-RFC 0050 section 5)
UNLOCK_PERSON = b"UNSEENET-DEVUNL1"       # BLAKE2b personalisation, 16 octets
MAX_DEVICE_UNLOCKS = 8
OPSLIMIT = nacl.pwhash.argon2id.OPSLIMIT_MODERATE
MEMLIMIT = nacl.pwhash.argon2id.MEMLIMIT_MODERATE


class VaultError(ValueError):
    pass


class VaultLocked(VaultError):
    """The vault is open in another program."""


LOCKED_MESSAGE = ("This vault is already open in another Unseenet program. "
                  "Close it there first.")

# ---------------------------------------------------------------------------
# The vault lock: one program at a time (each saves the whole vault, the last
# one to save would win). A lock file beside the vault, locked by the OS, so a
# crashed program never leaves it locked. Where the file system has no locks
# (some FAT sticks on macOS) the file holds "pid host" and a dead or foreign
# holder counts as gone. Opening the same vault twice in one program is
# allowed: the program itself keeps one copy in step.
# ---------------------------------------------------------------------------
_held: dict[str, list] = {}          # resolved vault path -> [lock, number of opens]
_held_lock = threading.Lock()


def _os_lock(fd: int) -> bool | None:
    """True: locked. False: another program holds it. None: no locks on this file system."""
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES,
                         getattr(errno, "EDEADLOCK", errno.EDEADLK), errno.EDEADLK):
            return False
        if exc.errno in (errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOLCK, errno.EINVAL,
                         errno.ENOSYS):
            return None
        raise


def _holder_alive(text: str) -> bool:
    """A "pid host" lock file: is that program still running here?"""
    parts = text.split()
    if len(parts) < 2 or not parts[0].isdigit():
        return False
    if parts[1] != socket.gethostname():
        return False                  # the stick was in another computer; that one is gone
    pid = int(parts[0])
    if pid == os.getpid():
        return False
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _VaultLock:
    def __init__(self, vault_path: Path):
        self.path = vault_path.with_name(vault_path.name + ".lock")
        self.fd: int | None = None
        self.by_file = False          # the "pid host" fallback, removed on release

    def _stamp(self) -> bytes:
        return f"{os.getpid()} {socket.gethostname()}\n".encode()

    def acquire(self) -> None:
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            if exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM):
                return                # read-only: this program could not save either
            raise
        try:
            got = _os_lock(fd)
        except BaseException:
            os.close(fd)
            raise
        if got:
            self.fd = fd
            os.ftruncate(fd, 0)
            os.write(fd, self._stamp())   # who holds it, for people looking at the stick
            return
        if got is False:
            os.close(fd)
            raise VaultLocked(LOCKED_MESSAGE)
        try:
            text = os.read(fd, 200).decode("ascii", "replace")
        finally:
            os.close(fd)
        if _holder_alive(text):
            raise VaultLocked(LOCKED_MESSAGE)
        with open(self.path, "wb") as f:
            f.write(self._stamp())
        self.by_file = True
        atexit.register(self.release)

    def release(self) -> None:
        if self.fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            os.close(self.fd)         # the OS lock goes with it; the file stays
            self.fd = None
        if self.by_file:
            self.by_file = False
            try:
                if self.path.read_bytes() == self._stamp():
                    self.path.unlink()
            except OSError:
                pass


def _lock(path: Path) -> str:
    key = str(path.resolve())
    with _held_lock:
        entry = _held.get(key)
        if entry is not None:
            entry[1] += 1
            return key
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = _VaultLock(path)
        lock.acquire()
        _held[key] = [lock, 1]
        return key


def _unlock(key: str) -> None:
    with _held_lock:
        entry = _held.get(key)
        if entry is None:
            return
        entry[1] -= 1
        if entry[1] <= 0:
            del _held[key]
            entry[0].release()


def _key(passphrase: str, salt: bytes, ops: int, mem: int) -> bytes:
    return nacl.pwhash.argon2id.kdf(nacl.secret.SecretBox.KEY_SIZE, passphrase.encode(),
                                    salt, opslimit=ops, memlimit=mem)


def _pack(key: bytes, salt: bytes, ops: int, mem: int, payload: bytes) -> bytes:
    box = nacl.secret.SecretBox(key).encrypt(payload)   # fresh random nonce every time
    return MAGIC + struct.pack(">II", ops, mem // 1024) + salt + bytes(box)


def _unpack(blob: bytes) -> tuple[int, int, bytes, bytes]:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 8 + 16 + 40:
        raise VaultError("not an Unseenet vault")
    ops, mem_kib = struct.unpack(">II", blob[9:17])
    return ops, mem_kib * 1024, blob[17:33], blob[33:]


def _device_key(secret: bytes) -> bytes:
    """The key that wraps the vault key for one device: from the secret the device's
    secure hardware releases only after its PIN or unlock - a passkey's WebAuthn PRF
    output, say (UN-RFC 0050 section 5). The secret is random, so no slow KDF."""
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise VaultError("the device's secret is too short")
    return nacl.hash.blake2b(secret, digest_size=nacl.secret.SecretBox.KEY_SIZE,
                             person=UNLOCK_PERSON, encoder=nacl.encoding.RawEncoder)


def _read_unlocks(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return []
    items = data.get("devices") if isinstance(data, dict) and data.get("v") == 1 else None
    return [d for d in (items or []) if isinstance(d, dict) and isinstance(d.get("id"), str)
            and isinstance(d.get("box"), str)]


def device_unlocks_of(path: Path) -> list[dict]:
    """The devices that can open the vault at ``path`` without its passphrase - ``id``,
    ``label`` and ``created`` only, never the wrapped key - read without opening it, so
    a locked client knows which passkey to ask for."""
    p = Path(path)
    return [{"id": d["id"], "label": d.get("label", ""), "created": d.get("created", 0)}
            for d in _read_unlocks(p.with_name(f"{p.name}.{UNLOCK_NAME}"))]


def _open_box(key: bytes, box: bytes) -> bytes:
    try:
        return nacl.secret.SecretBox(key).decrypt(box)
    except nacl.exceptions.CryptoError as exc:
        raise VaultError("wrong passphrase or damaged vault") from exc


def seal(payload: bytes, passphrase: str, *, ops: int = OPSLIMIT, mem: int = MEMLIMIT) -> bytes:
    """Encrypt ``payload`` with a key derived from ``passphrase`` (Argon2id, UN-RFC 0007
    section 2). ``ops`` and ``mem`` are the KDF's cost; the result carries them."""
    salt = os.urandom(16)
    return _pack(_key(passphrase, salt, ops, mem), salt, ops, mem, payload)


def unseal(blob: bytes, passphrase: str) -> bytes:
    """Decrypt what ``seal`` made; raises on a wrong passphrase or a damaged file."""
    ops, mem, salt, box = _unpack(blob)
    return _open_box(_key(passphrase, salt, ops, mem), box)


class Vault:
    """JSON state kept only in memory and saved encrypted, atomically.

    The expensive Argon2id derivation runs once, when the vault is opened; the
    derived key is kept in memory so saving is fast. The passphrase itself is
    not kept. Saves are serialized and written with permissions 0600.
    """

    def __init__(self, path: Path, key: bytes, salt: bytes, ops: int, mem: int, data: dict,
                 lock_key: str | None = None):
        self.path, self.data = path, data
        self._key, self._salt, self._ops, self._mem = key, salt, ops, mem
        self._lock = threading.Lock()
        self._lock_key = lock_key

    def close(self) -> None:
        """Let other programs open the vault (also happens when this program ends)."""
        key, self._lock_key = self._lock_key, None
        if key is not None:
            _unlock(key)

    @classmethod
    def open(cls, path: Path, passphrase: str, ops: int = OPSLIMIT, mem: int = MEMLIMIT) -> "Vault":
        """Open (or start) a vault. Raises :class:`VaultLocked` if another program has it.

        The lock is taken first, so a second program is told at once, before the
        slow key derivation, and is released again if the passphrase is wrong.
        """
        path = Path(path)
        lock_key = _lock(path)
        try:
            if not path.exists():
                salt = os.urandom(16)
                key = _key(passphrase, salt, ops, mem)
                return cls(path, key, salt, ops, mem,
                           {"v": 1, "identities": {}, "groups": {}, "nodes": []}, lock_key)
            ops, mem, salt, box = _unpack(path.read_bytes())
            key = _key(passphrase, salt, ops, mem)
            return cls(path, key, salt, ops, mem, json.loads(_open_box(key, box)), lock_key)
        except BaseException:
            _unlock(lock_key)
            raise

    @classmethod
    def open_with_device(cls, path: Path, device: str, secret: bytes) -> "Vault":
        """Open the vault with a device's secret instead of its passphrase (UN-RFC 0050
        section 5): the vault key, wrapped for that device by ``add_device_unlock``.
        The passphrase still opens it, everywhere."""
        path = Path(path)
        lock_key = _lock(path)
        try:
            entry = next((d for d in _read_unlocks(path.with_name(f"{path.name}.{UNLOCK_NAME}"))
                          if d["id"] == device), None)
            if entry is None:
                raise VaultError("this device cannot open the vault: use the passphrase")
            try:
                key = nacl.secret.SecretBox(_device_key(secret)).decrypt(base64.b64decode(entry["box"]))
            except (nacl.exceptions.CryptoError, ValueError) as exc:
                raise VaultError("the device did not open the vault: use the passphrase") from exc
            ops, mem, salt, box = _unpack(path.read_bytes())
            return cls(path, key, salt, ops, mem, json.loads(_open_box(key, box)), lock_key)
        except BaseException:
            _unlock(lock_key)
            raise

    # --- device unlocks (UN-RFC 0050 section 5) ----------------------------------
    def unlock_path(self) -> Path:
        return self.sidecar_path(UNLOCK_NAME)

    def device_unlocks(self) -> list[dict]:
        """The devices that can open this vault without its passphrase."""
        return device_unlocks_of(self.path)

    def add_device_unlock(self, passphrase: str, device: str, secret: bytes, label: str = "") -> None:
        """Let a device open this vault with ``secret``, which its secure hardware gives
        only after its PIN or unlock. ``passphrase`` must be the vault's, so an unlocked,
        unattended program cannot let another device in. Kept in ``<vault>.unlock``,
        beside the vault and never copied with it: without the device it opens nothing."""
        if not self.check_passphrase(passphrase):
            raise VaultError("wrong passphrase")
        device = str(device).strip()
        if not device or len(device) > 512:
            raise VaultError("a device is named by its credential ID")
        box = nacl.secret.SecretBox(_device_key(secret)).encrypt(self._key)
        items = [d for d in _read_unlocks(self.unlock_path()) if d["id"] != device]
        if len(items) >= MAX_DEVICE_UNLOCKS:
            raise VaultError(f"at most {MAX_DEVICE_UNLOCKS} devices: remove one first")
        items.append({"id": device, "label": str(label)[:64], "created": int(time.time()),
                      "box": base64.b64encode(bytes(box)).decode()})
        with self._lock:
            self._atomic_write(self.unlock_path(), json.dumps({"v": 1, "devices": items}).encode())

    def remove_device_unlock(self, device: str | None = None) -> int:
        """Stop a device (or, with None, every device) opening this vault without its
        passphrase. Returns how many were removed."""
        items = _read_unlocks(self.unlock_path())
        keep = [] if device is None else [d for d in items if d["id"] != device]
        with self._lock:
            if keep:
                self._atomic_write(self.unlock_path(), json.dumps({"v": 1, "devices": keep}).encode())
            else:
                try:
                    os.unlink(self.unlock_path())
                except FileNotFoundError:
                    pass
        return len(items) - len(keep)

    def save(self) -> None:
        with self._lock:
            payload = json.dumps(self.data).encode()
            self._atomic_write(self.path, _pack(self._key, self._salt, self._ops, self._mem, payload))

    # --- changing the passphrase ------------------------------------------------
    def check_passphrase(self, passphrase: str) -> bool:
        """Does ``passphrase`` open this vault? (Runs the slow key derivation.)"""
        return hmac.compare_digest(_key(passphrase, self._salt, self._ops, self._mem), self._key)

    def change_passphrase(self, old: str, new: str, *, ops: int | None = None,
                          mem: int | None = None) -> None:
        """Encrypt the vault and its sidecar files again under ``new``.

        ``old`` must be the current passphrase, so an unlocked, unattended
        program is not enough to change it. A fresh salt is used. Only this
        file changes: copies of the vault elsewhere (other devices, sticks,
        backups) still open with the old passphrase. Device unlocks are removed,
        since they wrap the old key.
        """
        if not self.check_passphrase(old):
            raise VaultError("wrong passphrase")
        side = {n: self.read_sidecar(n) for n in self.sidecar_names()}
        ops = self._ops if ops is None else ops
        mem = self._mem if mem is None else mem
        salt = os.urandom(16)
        key = _key(new, salt, ops, mem)
        with self._lock:
            before = (self._key, self._salt, self._ops, self._mem)
            self._key, self._salt, self._ops, self._mem = key, salt, ops, mem
        # The vault first: it is what matters. If it cannot be written (a full disk,
        # a stick pulled out), the old key comes back: otherwise a later save would
        # quietly switch the file to a passphrase the person believes did not take.
        try:
            self.save()
        except BaseException:
            with self._lock:
                self._key, self._salt, self._ops, self._mem = before
            raise
        # A sidecar left under the old key by a crash here is only a cache, and the
        # client starts it over.
        for name, payload in side.items():
            if payload is not None:
                self.write_sidecar(name, payload)
        # The devices held the old key: they must be set up again (UN-RFC 0050 section 5)
        self.remove_device_unlock()

    # --- sidecar files: other data encrypted with the same key -----------------
    def sidecar_path(self, name: str) -> Path:
        return self.path.with_name(f"{self.path.name}.{name}")

    def sidecar_names(self) -> list[str]:
        """The sidecar files beside this vault: ``<vault>.<name>`` that start with the
        sidecar magic. The lock file, backups and anything else beside it are not."""
        prefix = self.path.name + "."
        names = []
        for p in sorted(self.path.parent.glob(glob.escape(prefix) + "*")):
            name = p.name[len(prefix):]
            if ".old-" in name or not p.is_file():
                continue
            try:
                with open(p, "rb") as f:
                    if f.read(len(SIDECAR_MAGIC)) == SIDECAR_MAGIC:
                        names.append(name)
            except OSError:
                continue
        return names

    def write_sidecar(self, name: str, payload: bytes) -> None:
        """Encrypt ``payload`` with the vault key into ``<vault>.<name>``."""
        box = nacl.secret.SecretBox(self._key).encrypt(payload)
        with self._lock:
            self._atomic_write(self.sidecar_path(name), SIDECAR_MAGIC + bytes(box))

    def read_sidecar(self, name: str) -> bytes | None:
        path = self.sidecar_path(name)
        try:
            blob = path.read_bytes()
        except FileNotFoundError:
            return None
        if not blob.startswith(SIDECAR_MAGIC):
            raise VaultError(f"{path.name} is not an Unseenet sidecar file")
        return _open_box(self._key, blob[len(SIDECAR_MAGIC):])

    @staticmethod
    def _atomic_write(path: Path, blob: bytes) -> None:
        directory = path.resolve().parent
        fd, tmp = tempfile.mkstemp(prefix=".unseenet-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
