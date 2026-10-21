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

import nacl.exceptions
import nacl.pwhash
import nacl.secret

MAGIC = b"UNSVAULT1"
SIDECAR_MAGIC = b"UNSSIDE1"
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


def _open_box(key: bytes, box: bytes) -> bytes:
    try:
        return nacl.secret.SecretBox(key).decrypt(box)
    except nacl.exceptions.CryptoError as exc:
        raise VaultError("wrong passphrase or damaged vault") from exc


def seal(payload: bytes, passphrase: str, *, ops: int = OPSLIMIT, mem: int = MEMLIMIT) -> bytes:
    salt = os.urandom(16)
    return _pack(_key(passphrase, salt, ops, mem), salt, ops, mem, payload)


def unseal(blob: bytes, passphrase: str) -> bytes:
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
        backups) still open with the old passphrase.
        """
        if not self.check_passphrase(old):
            raise VaultError("wrong passphrase")
        side = {n: self.read_sidecar(n) for n in self.sidecar_names()}
        ops = self._ops if ops is None else ops
        mem = self._mem if mem is None else mem
        salt = os.urandom(16)
        key = _key(new, salt, ops, mem)
        with self._lock:
            self._key, self._salt, self._ops, self._mem = key, salt, ops, mem
        # The vault first: it is what matters. A sidecar left under the old key
        # by a crash here is only a cache, and the client starts it over.
        self.save()
        for name, payload in side.items():
            if payload is not None:
                self.write_sidecar(name, payload)

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
