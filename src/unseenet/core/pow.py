"""Proof-of-work postage (UN-RFC 0006)."""

from __future__ import annotations

import hashlib
import itertools
import re
import threading
from contextlib import contextmanager

from .encoding import DS, H, b64, b64decode

_PREFIX = DS("UNSEENET-POW-1")
_HEADER_RE = re.compile(r"^sha256;\s*bits=(\d+);\s*nonce=([A-Za-z0-9_-]+)$")
_REPORT_MASK = (1 << 16) - 1     # tell the hook every 65536 attempts
_local = threading.local()


@contextmanager
def reporting(callback):
    """Call ``callback(attempts, expected, done)`` while postage is computed in this
    thread, so a client can show a progress bar (unseenet #139). A hook rather than
    a parameter, as postage is computed deep inside article builders."""
    previous = getattr(_local, "callback", None)
    _local.callback = callback
    try:
        yield
    finally:
        _local.callback = previous


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
    report = getattr(_local, "callback", None)
    expected = 1 << bits
    for counter in itertools.count():
        nonce = counter.to_bytes(max(1, (counter.bit_length() + 7) // 8), "big")
        h = base.copy()
        h.update(nonce)
        if leading_zero_bits(h.digest()) >= bits:
            if report:
                report(counter + 1, expected, True)
            return f"sha256; bits={bits}; nonce={b64(nonce)}"
        if report and not counter & _REPORT_MASK and counter:
            report(counter, expected, False)
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
