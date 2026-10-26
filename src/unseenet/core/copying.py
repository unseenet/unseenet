"""Copying identities to another device (UN-RFC 0050 section 3): the protocol, without
the network.

The old device makes a one-time code ``<n>-<word1>-<word2>`` (two words from the BIP39
list, ``n`` from the meeting point) and a QR text ``unseenet-copy:1:<onion>:<code>``.
Both devices run SPAKE2 (``spake2``, as used by Magic Wormhole) with the code as the
password, confirm the key, show the same two check words, and the old device sends the
chosen part of its vault encrypted under ``copy_key``. The connection's framing and order
are section 3.9; ``read_msg`` / ``write_msg`` do the framing.

What goes in the copy (section 3.6) and how it joins the new device's vault (3.7) are
``build_payload`` and ``merge_payload``. The session (``client/session/copying.py``)
does the Tor and onion part.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
import secrets

from .encoding import DS, H
from . import crypto
from . import recovery as rc

VERSION = b"UNSEENET-COPY-1"
AAD = b"UNSEENET-COPY-1"
PORT = 9119                         # the one-time onion service's virtual port (3.9)
MAX_MSG = 64 * 1024                 # every message but the copy
MAX_COPY = 1024 * 1024              # the copy itself
CODE_SECONDS = 600.0                # a code lives 10 minutes (3.2)
OLD, NEW = b"unseenet-copy-old", b"unseenet-copy-new"     # SPAKE2 identities and roles (3.4)
QR_PREFIX = "unseenet-copy:1:"
_ONION = re.compile(r"^[a-z2-7]{56}\.onion$")


class CopyError(Exception):
    """A copy cannot go on: a wrong code, a wrong confirmation, a message out of order,
    too big, or the other side closed. The message says what a person can act on."""


# --- the code and the QR text (section 3.2) --------------------------------------------

def new_words() -> tuple[str, str]:
    """The two secret words of a code, chosen at random from the BIP39 list."""
    wl = rc.wordlist()
    return secrets.choice(wl), secrets.choice(wl)


def make_code(n: int, word1: str, word2: str) -> str:
    return f"{n}-{word1}-{word2}"


def parse_code(text: str) -> tuple[int, str, str]:
    """``(n, word1, word2)`` from a typed code: any case, spaces or dashes between the
    parts, four letters per word enough. Raises ``CopyError``."""
    parts = re.split(r"[\s\-_.]+", text.strip().lower())
    parts = [p for p in parts if p]
    if len(parts) != 3 or not parts[0].isdigit() or not 1 <= int(parts[0]) <= 999:
        raise CopyError("A code is a number and two words, such as 7-guitar-tunnel.")
    words = []
    for w in parts[1:]:
        full = _word(w)
        if full is None:
            raise CopyError(f"\"{w}\" is not one of the words a code is made of. Check the spelling.")
        words.append(full)
    return int(parts[0]), words[0], words[1]


def _word(w: str) -> str | None:
    wl = rc.wordlist()
    if w in wl:
        return w
    if len(w) >= 4:
        hits = [x for x in wl if x.startswith(w[:4])]
        return hits[0] if len(hits) == 1 else None
    return None


def normal_code(text: str) -> str:
    """The code as the SPAKE2 password: ``<n>-<word1>-<word2>``, full words, lower case."""
    return make_code(*parse_code(text))


def tag(word1: str, word2: str) -> str:
    """What the meeting point keeps beside the address (section 3.3): 16 octets, hex."""
    return H(DS("UNSEENET-COPY-TAG-1") + f"{word1}-{word2}".encode())[:16].hex()


def qr_text(onion: str, code: str) -> str:
    """What the QR code carries: everything the new device needs, no meeting point."""
    return f"{QR_PREFIX}{onion}:{code}"


def parse_qr(text: str) -> tuple[str, str]:
    """``(onion address, code)`` from a scanned QR text. Raises ``CopyError``."""
    text = text.strip()
    if not text.startswith(QR_PREFIX):
        raise CopyError("This is not an Unseenet copy code.")
    onion, _, code = text[len(QR_PREFIX):].partition(":")
    if not _ONION.match(onion):
        raise CopyError("The QR code has no onion address.")
    return onion, normal_code(code)


# --- the exchange (sections 3.4, 3.5) ----------------------------------------------------

class Exchange:
    """One side's SPAKE2 run: ``message`` to send, ``finish`` with the other's, then
    ``confirmation`` / ``check_confirmation``, ``copy_key`` and ``check_words``."""

    def __init__(self, role: bytes, code: str):
        from spake2 import SPAKE2_A, SPAKE2_B
        if role not in (OLD, NEW):
            raise ValueError("role")
        self.role = role
        password = normal_code(code).encode()
        cls = SPAKE2_A if role == OLD else SPAKE2_B
        self._spake = cls(password, idA=OLD, idB=NEW)
        self.message = self._spake.start()
        self.key: bytes | None = None

    def finish(self, other: bytes) -> None:
        try:
            self.key = self._spake.finish(other)
        except Exception as exc:  # noqa: BLE001 - the library raises several kinds
            raise CopyError("the other device sent something that is not a copy") from exc

    def confirmation(self, role: bytes | None = None) -> bytes:
        """``H(DS("UNSEENET-COPY-CONFIRM-1") || role || K)``, our role by default."""
        return H(DS("UNSEENET-COPY-CONFIRM-1") + (role or self.role) + self._k())

    def check_confirmation(self, theirs: bytes) -> None:
        other = NEW if self.role == OLD else OLD
        if not hmac.compare_digest(theirs, self.confirmation(other)):
            raise CopyError("The code was not right. Start again with a new code.")

    @property
    def copy_key(self) -> bytes:
        return H(DS("UNSEENET-COPY-KEY-1") + self._k())

    @property
    def check_words(self) -> tuple[str, str]:
        """The two check words (section 3.5): the first 22 bits of ``check_value``."""
        v = int.from_bytes(H(DS("UNSEENET-COPY-CHECK-1") + self._k())[:3], "big") >> 2
        wl = rc.wordlist()
        return wl[v >> 11], wl[v & 0x7FF]

    def seal(self, obj: dict) -> bytes:
        return crypto.aead_encrypt(self.copy_key, _canonical(obj), AAD)

    def open(self, blob: bytes) -> dict:
        try:
            return json.loads(crypto.aead_decrypt(self.copy_key, blob, AAD))
        except (crypto.CryptoError, ValueError) as exc:
            raise CopyError("the copy could not be opened") from exc

    def _k(self) -> bytes:
        if self.key is None:
            raise CopyError("the exchange is not finished")
        return self.key


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


# --- framing (section 3.9) -------------------------------------------------------------

async def read_msg(reader: asyncio.StreamReader, limit: int = MAX_MSG) -> bytes:
    """One message: a 4-octet big-endian length and that many octets."""
    try:
        n = int.from_bytes(await reader.readexactly(4), "big")
        if n > limit:
            raise CopyError("the other device sent too much")
        return await reader.readexactly(n)
    except asyncio.IncompleteReadError as exc:
        raise CopyError("the other device closed the connection") from exc


async def write_msg(writer: asyncio.StreamWriter, data: bytes) -> None:
    writer.write(len(data).to_bytes(4, "big") + data)
    await writer.drain()


# --- what is copied (sections 3.6, 3.7) ------------------------------------------------

def build_payload(data: dict, names: list[str] | None = None, group_secrets: bool = True) -> dict:
    """The copy from a vault's data: the chosen identities (all by default), the default
    among them, and - unless left out - the secrets of the closed groups in the vault.
    Never the cache or the state (they come from the network)."""
    ids = data["identities"]
    names = list(ids) if names is None else [n for n in names if n in ids]
    if not names:
        raise CopyError("choose at least one identity to copy")
    out = {"v": 1, "identities": {}, "groups": {}}
    for n in names:
        e = ids[n]
        out["identities"][n] = {k: e[k] for k in ("seed", "display", "signature") if k in e}
    default = data.get("default_identity")
    out["default"] = default if default in names else names[0]
    if group_secrets:
        for gid, entry in data.get("groups", {}).items():
            if entry.get("keys") and (entry.get("type") == "closed"
                                      or (entry.get("manifest") or {}).get("type") == "closed"):
                out["groups"][gid] = {"keys": dict(entry["keys"])}
    return out


def check_payload(p) -> dict:
    """The copy as received, checked: version, seeds of 32 octets, keys in hex."""
    try:
        assert isinstance(p, dict) and p.get("v") == 1
        assert isinstance(p.get("identities"), dict) and p["identities"]
        for name, e in p["identities"].items():
            assert isinstance(name, str) and 0 < len(name) <= 64
            assert len(bytes.fromhex(e["seed"])) == 32
        assert p.get("default") in p["identities"]
        assert isinstance(p.get("groups", {}), dict)
        for gid, g in p.get("groups", {}).items():
            for epoch, key in g["keys"].items():
                assert str(epoch).isdigit() and len(bytes.fromhex(key)) == 32
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        raise CopyError("the copy is not in the expected form") from exc
    return p


def merge_payload(data: dict, p: dict) -> list[str]:
    """Add a copy to a vault's data (section 3.7): identities not there yet (an identity
    already there is not overwritten, whatever its name), and missing group secrets.
    A name taken by another key gets a suffix. The copied default becomes the default
    when the vault had none. Returns the names of the identities added."""
    check_payload(p)
    have = {e.get("seed"): n for n, e in data["identities"].items()}
    added, names = [], {}
    for name, e in p["identities"].items():
        if e["seed"] in have:
            names[name] = have[e["seed"]]
            continue
        new = name
        i = 2
        while new in data["identities"]:
            new, i = f"{name}-{i}", i + 1
        data["identities"][new] = {k: e[k] for k in ("seed", "display", "signature") if k in e}
        data["identities"][new].setdefault("display", new)
        names[name] = new
        added.append(new)
    if not data.get("default_identity"):
        data["default_identity"] = names[p["default"]]
    for gid, g in p.get("groups", {}).items():
        entry = data["groups"].setdefault(gid, {"type": "closed", "owner": False, "keys": {}})
        entry.setdefault("keys", {})
        for epoch, key in g["keys"].items():
            entry["keys"].setdefault(str(epoch), key)
    return added
