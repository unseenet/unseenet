"""Proof-of-work postage (UN-RFC 0006)."""

from __future__ import annotations

import hashlib
import itertools
import re

from .encoding import DS, H, b64, b64decode

_PREFIX = DS("UNSEENET-POW-1")
_HEADER_RE = re.compile(r"^sha256;\s*bits=(\d+);\s*nonce=([A-Za-z0-9_-]+)$")


def leading_zero_bits(digest: bytes) -> int:
    n = 0
    for byte in digest:
        if byte == 0:
            n += 8
            continue
        return n + (8 - byte.bit_length())
    return n


def solve(canonical: bytes, bits: int) -> str:
    """Find a nonce; return the Proof-Of-Work header value."""
    base = hashlib.sha256(_PREFIX + H(canonical))
    for counter in itertools.count():
        nonce = counter.to_bytes(max(1, (counter.bit_length() + 7) // 8), "big")
        h = base.copy()
        h.update(nonce)
        if leading_zero_bits(h.digest()) >= bits:
            return f"sha256; bits={bits}; nonce={b64(nonce)}"
    raise AssertionError("unreachable")


def verify(header_value: str, canonical: bytes) -> int:
    """Return the proven number of bits, or -1 if invalid."""
    m = _HEADER_RE.match(header_value.strip())
    if not m:
        return -1
    claimed = int(m.group(1))
    try:
        nonce = b64decode(m.group(2))
    except Exception:  # noqa: BLE001
        return -1
    if not 1 <= len(nonce) <= 32:
        return -1
    actual = leading_zero_bits(H(_PREFIX + H(canonical) + nonce))
    return claimed if actual >= claimed else -1
