"""Encrypted client vault (UN-RFC 0007, section 2)."""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import nacl.exceptions
import nacl.pwhash
import nacl.secret

MAGIC = b"UNSVAULT1"
OPSLIMIT = nacl.pwhash.argon2id.OPSLIMIT_MODERATE
MEMLIMIT = nacl.pwhash.argon2id.MEMLIMIT_MODERATE


class VaultError(ValueError):
    pass


def _key(passphrase: str, salt: bytes, ops: int, mem: int) -> bytes:
    return nacl.pwhash.argon2id.kdf(nacl.secret.SecretBox.KEY_SIZE, passphrase.encode(),
                                    salt, opslimit=ops, memlimit=mem)


def seal(payload: bytes, passphrase: str, *, ops: int = OPSLIMIT, mem: int = MEMLIMIT) -> bytes:
    salt = os.urandom(16)
    box = nacl.secret.SecretBox(_key(passphrase, salt, ops, mem)).encrypt(payload)
    return MAGIC + struct.pack(">II", ops, mem // 1024) + salt + bytes(box)


def unseal(blob: bytes, passphrase: str) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 8 + 16 + 40:
        raise VaultError("not an Unseenet vault")
    ops, mem_kib = struct.unpack(">II", blob[9:17])
    salt, box = blob[17:33], blob[33:]
    try:
        return nacl.secret.SecretBox(_key(passphrase, salt, ops, mem_kib * 1024)).decrypt(box)
    except nacl.exceptions.CryptoError as exc:
        raise VaultError("wrong passphrase or damaged vault") from exc


class Vault:
    """JSON state kept only in memory and saved encrypted, atomically."""

    def __init__(self, path: Path, passphrase: str, data: dict | None = None, **kdf):
        self.path, self._pass, self.data, self._kdf = path, passphrase, data or {}, kdf

    @classmethod
    def open(cls, path: Path, passphrase: str, **kdf) -> "Vault":
        if not path.exists():
            return cls(path, passphrase, {"v": 1, "identities": {}, "groups": {}, "nodes": []}, **kdf)
        return cls(path, passphrase, json.loads(unseal(path.read_bytes(), passphrase)), **kdf)

    def save(self) -> None:
        blob = seal(json.dumps(self.data).encode(), self._pass, **self._kdf)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, self.path)
