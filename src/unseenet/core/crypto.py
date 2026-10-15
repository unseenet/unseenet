"""Identities, signatures and encryption (UN-RFC 0003)."""

from __future__ import annotations

import os
from dataclasses import dataclass

import nacl.bindings as sodium
import nacl.exceptions
import nacl.public
import nacl.signing

from .encoding import DS, H, b32, b32decode, b64, b64decode

KEY_PREFIX = "ed25519:"
SIG_PREFIX = "ed25519:"

# Signature purposes (UN-RFC 0003, section 3)
PURPOSE_ARTICLE = "UNSEENET-ARTICLE-1"
PURPOSE_MEMBER = "UNSEENET-MEMBER-1"
PURPOSE_APPROVAL = "UNSEENET-APPROVAL-1"


class CryptoError(ValueError):
    pass


# --- keys -----------------------------------------------------------------

def key_to_text(pk: bytes) -> str:
    return KEY_PREFIX + b32(pk)


def key_from_text(text: str) -> bytes:
    text = text.strip()
    if not text.startswith(KEY_PREFIX):
        raise CryptoError("unknown key algorithm")
    try:
        raw = b32decode(text[len(KEY_PREFIX):])
    except Exception as exc:  # noqa: BLE001
        raise CryptoError("malformed key") from exc
    if len(raw) != 32:
        raise CryptoError("malformed key")
    return raw


def fingerprint(pk: bytes) -> str:
    """80-bit fingerprint used in group IDs."""
    return b32(H(DS("UNSEENET-FP-1") + pk))[:16]


@dataclass
class Identity:
    """An Ed25519 identity. The public key *is* the identity."""

    signing_key: nacl.signing.SigningKey

    @classmethod
    def generate(cls) -> "Identity":
        return cls(nacl.signing.SigningKey.generate())

    @classmethod
    def from_seed(cls, seed: bytes) -> "Identity":
        return cls(nacl.signing.SigningKey(seed))

    @property
    def seed(self) -> bytes:
        return bytes(self.signing_key)

    @property
    def public_key(self) -> bytes:
        return bytes(self.signing_key.verify_key)

    @property
    def key_text(self) -> str:
        return key_to_text(self.public_key)

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.public_key)

    def sign(self, purpose: str, message: bytes) -> bytes:
        return self.signing_key.sign(DS(purpose) + message).signature

    def sign_text(self, purpose: str, message: bytes) -> str:
        return SIG_PREFIX + b64(self.sign(purpose, message))

    # sealed boxes (UN-RFC 0003, section 4.1)
    def open_sealed(self, box: bytes) -> bytes:
        sk = self.signing_key.to_curve25519_private_key()
        return nacl.public.SealedBox(sk).decrypt(box)


def sig_from_text(text: str) -> bytes:
    text = text.strip()
    if not text.startswith(SIG_PREFIX):
        raise CryptoError("unknown signature algorithm")
    try:
        raw = b64decode(text[len(SIG_PREFIX):])
    except Exception as exc:  # noqa: BLE001
        raise CryptoError("malformed signature") from exc
    if len(raw) != 64:
        raise CryptoError("malformed signature")
    return raw


def verify(pk: bytes, purpose: str, message: bytes, signature: bytes) -> bool:
    """Strict Ed25519 verification (libsodium rejects non-canonical input)."""
    try:
        nacl.signing.VerifyKey(pk).verify(DS(purpose) + message, signature)
        return True
    except nacl.exceptions.BadSignatureError:
        return False


def seal_to(pk: bytes, message: bytes) -> bytes:
    """Anonymous sealed box to an Ed25519 identity (converted to X25519)."""
    curve_pk = nacl.signing.VerifyKey(pk).to_curve25519_public_key()
    return nacl.public.SealedBox(curve_pk).encrypt(message)


# --- symmetric (UN-RFC 0003, section 4.2) --------------------------------

def aead_encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(24)
    ct = sodium.crypto_aead_xchacha20poly1305_ietf_encrypt(plaintext, aad, nonce, key)
    return nonce + ct


def aead_decrypt(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < 24 + 16:
        raise CryptoError("ciphertext too short")
    try:
        return sodium.crypto_aead_xchacha20poly1305_ietf_decrypt(blob[24:], aad, blob[:24], key)
    except nacl.exceptions.CryptoError as exc:
        raise CryptoError("decryption failed") from exc


# --- group secret derivation (UN-RFC 0003, section 4.3) ------------------

@dataclass(frozen=True)
class GroupKeys:
    secret: bytes

    @classmethod
    def generate(cls) -> "GroupKeys":
        return cls(os.urandom(32))

    @property
    def enc_key(self) -> bytes:
        return H(DS("UNSEENET-GROUP-ENC-1") + self.secret)

    @property
    def member(self) -> Identity:
        return Identity.from_seed(H(DS("UNSEENET-GROUP-MEMBER-1") + self.secret))
