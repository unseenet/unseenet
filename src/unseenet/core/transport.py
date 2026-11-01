"""Transport addresses (UN-RFC 0064): ``onion:`` and ``test:``, and the bare onion
addresses of before.

Belongs here: reading a transport address, writing it, the form a connection needs,
and which of several addresses to use. Only ``onion`` hides where a node is; ``test``
is for development and test networks, and offered only behind a test setting.

Not here: opening the connection (``core/tor.py``)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

KNOWN = ("onion", "test")
RESERVED = ("i2p", "rns")                 # section 2.1: not to be used yet
MAX_ADDRESSES = 8                         # section 4
ONION_PORT = 119

_SCHEME = re.compile(r"^([a-z0-9-]{1,16}):(.*)$")
_ONION = re.compile(r"^([a-z2-7]{56}\.onion)(?::(\d{1,5}))?$")
_HOSTPORT = re.compile(r"^([A-Za-z0-9.\-]+|\[[0-9A-Fa-f:]+\]):(\d{1,5})$")


class AddressProblem(ValueError):
    pass


@dataclass(frozen=True)
class Address:
    scheme: str            # "onion" or "test"
    host: str
    port: int

    def text(self) -> str:
        """The written form (section 2): ``onion:x.onion`` (``:port`` unless 119),
        ``test:host:port``."""
        if self.scheme == "onion":
            return f"onion:{self.host}" + ("" if self.port == ONION_PORT else f":{self.port}")
        return f"test:{self.host}:{self.port}"

    def plain(self) -> str:
        """The form clients and nodes have kept so far: ``x.onion`` (``:port`` unless
        119) or ``host:port``. What a connection is opened to."""
        if self.scheme == "onion":
            return self.host + ("" if self.port == ONION_PORT else f":{self.port}")
        return f"{self.host}:{self.port}"


def test_allowed() -> bool:
    """Whether ``test:`` addresses (and plain ``host:port``) may be offered from lists
    (section 2.2): only behind a test setting, ``UNSEENET_TEST_ADDRESSES=1``."""
    return os.environ.get("UNSEENET_TEST_ADDRESSES", "").lower() in ("1", "true", "yes")


def _port(text: str | None, default: int) -> int:
    port = int(text) if text else default
    if not 0 < port < 65536:
        raise AddressProblem(f"port {port} is not 1 to 65535")
    return port


def parse(text: str) -> Address | None:
    """A transport address, or None when its scheme is one this software does not
    know - not an error, only unusable here (section 2). A bare onion address is the
    ``onion:`` one; a plain ``host:port`` is a ``test:`` one, as before. Raises
    ``AddressProblem`` when a known scheme's part is malformed."""
    text = (text or "").strip()
    m = _ONION.match(text.lower())
    if m:
        return Address("onion", m.group(1), _port(m.group(2), ONION_PORT))
    s = _SCHEME.match(text)
    if s and not _HOSTPORT.match(text):
        scheme, rest = s.group(1), s.group(2)
        if scheme == "onion":
            m = _ONION.match(rest.lower())
            if not m:
                raise AddressProblem(f"{text}: not an onion address (56 letters and digits, .onion)")
            return Address("onion", m.group(1), _port(m.group(2), ONION_PORT))
        if scheme == "test":
            h = _HOSTPORT.match(rest)
            if not h:
                raise AddressProblem(f"{text}: a test address is test:host:port")
            return Address("test", h.group(1), _port(h.group(2), 0))
        return None                                   # unknown or reserved scheme
    h = _HOSTPORT.match(text)
    if h:
        return Address("test", h.group(1), _port(h.group(2), 0))
    raise AddressProblem(f"{text}: not a node address")


def connect_target(text: str) -> str:
    """What a connection is opened to (``host:port`` or ``x.onion[:port]``); raises
    ``AddressProblem`` for an address it cannot reach."""
    a = parse(text)
    if a is None:
        raise AddressProblem(f"{text}: this software has no transport for that address")
    return a.plain()


def usable(addresses, allow_test: bool | None = None) -> list[Address]:
    """The addresses this software can use, ``onion:`` first (section 4), at most 8;
    unknown schemes are left out without error, and ``test:`` ones unless allowed."""
    allow_test = test_allowed() if allow_test is None else allow_test
    out = []
    for text in list(addresses)[:MAX_ADDRESSES + 1]:
        try:
            a = parse(text) if isinstance(text, str) else None
        except AddressProblem:
            a = None
        if a is not None and (a.scheme == "onion" or allow_test) and a not in out:
            out.append(a)
    return sorted(out, key=lambda a: a.scheme != "onion")
