"""Encrypted client vault (UN-RFC 0007, section 2)."""

from __future__ import annotations

import json
import os
import struct
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

    def __init__(self, path: Path, key: bytes, salt: bytes, ops: int, mem: int, data: dict):
        self.path, self.data = path, data
        self._key, self._salt, self._ops, self._mem = key, salt, ops, mem
        self._lock = threading.Lock()

    @classmethod
    def open(cls, path: Path, passphrase: str, ops: int = OPSLIMIT, mem: int = MEMLIMIT) -> "Vault":
        path = Path(path)
        if not path.exists():
            salt = os.urandom(16)
            key = _key(passphrase, salt, ops, mem)
            return cls(path, key, salt, ops, mem, {"v": 1, "identities": {}, "groups": {}, "nodes": []})
        ops, mem, salt, box = _unpack(path.read_bytes())
        key = _key(passphrase, salt, ops, mem)
        return cls(path, key, salt, ops, mem, json.loads(_open_box(key, box)))

    def save(self) -> None:
        with self._lock:
            payload = json.dumps(self.data).encode()
            self._atomic_write(self.path, _pack(self._key, self._salt, self._ops, self._mem, payload))

    # --- sidecar files: other data encrypted with the same key -----------------
    def sidecar_path(self, name: str) -> Path:
        return self.path.with_name(f"{self.path.name}.{name}")

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
