"""Encodings and helpers from UN-RFC 0003, section 1."""

from __future__ import annotations

import base64
import hashlib


def b32(data: bytes) -> str:
    """RFC 4648 base32, lowercase, no padding."""
    return base64.b32encode(data).decode("ascii").rstrip("=").lower()


def b32decode(text: str) -> bytes:
    text = text.upper()
    return base64.b32decode(text + "=" * (-len(text) % 8))


def b64(data: bytes) -> str:
    """RFC 4648 base64url, no padding."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def H(data: bytes) -> bytes:
    """SHA-256."""
    return hashlib.sha256(data).digest()


def DS(label: str) -> bytes:
    """Domain separator: ASCII label followed by a zero octet."""
    return label.encode("ascii") + b"\x00"
