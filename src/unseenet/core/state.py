"""An identity's state in the network (UN-RFC 0044): what it is, sealed and merged.

The state - groups followed, people followed, contacts, ignored keys, hidden
profiles, closed chats, settings, read marks - lives encrypted in the manifest of the
identity's key-bound group ``state@<fp>``. This module is the protocol only:
the key (section 4.1), sealing to a fixed size (section 5) and opening, and
merging two states so that two clients never undo each other (section 7.2).
``client.session.state`` builds the state from a vault and writes it.
"""

from __future__ import annotations

import base64
import json
import os

import nacl.bindings as nb

from .encoding import DS, H

VERSION = 1
SIZES = (4 * 1024, 8 * 1024, 16 * 1024)     # section 5: padded to the smallest that holds it
MAX_ALSO = 64                               # section 4.3: read marks after "to", per group
MAX_THREADS = 256                           # section 4.5: watched and ignored threads
MAX_RULES = 2048                            # section 4.5: settings.feed_rules, in bytes (#615)
MAPS = ("subscribed", "unsubscribed", "following", "unfollowed", "contacts", "ignored", "hidden",
        "closed_chats")


class StateError(ValueError):
    """A state that cannot be opened: another key, damaged, or not a state."""


def state_key(seed: bytes) -> bytes:
    """``H(DS("UNSEENET-STATE-1") || seed)`` (section 4.1)."""
    return H(DS("UNSEENET-STATE-1") + seed)


def empty() -> dict:
    return {"v": VERSION, "updated": "", **{k: {} for k in MAPS}, "starter": 0,
            "settings": {}, "read": {}, "seen": {}, "threads": {}, "sent": []}


def _canonical(state: dict) -> bytes:
    return json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fit(state: dict) -> dict:
    """The state, made small enough for 16 KiB (section 5): the oldest sent entries
    first, then the oldest ``also`` read marks, then read marks of groups no longer
    followed, then the oldest read marks."""
    s = json.loads(json.dumps(state))
    def size():
        return len(_canonical(s))
    if len(s.get("threads", {})) > MAX_THREADS:      # section 4.5: the newest kept
        keep = sorted(s["threads"], key=lambda m: _at(s["threads"][m]))[-MAX_THREADS:]
        s["threads"] = {m: s["threads"][m] for m in keep}
    while size() > SIZES[-1] and s["sent"]:
        s["sent"].sort(key=lambda e: e.get("at", ""))
        s["sent"].pop(0)
    for gid in [g for g in s.get("seen", {}) if g not in s["subscribed"]]:   # seen before read
        if size() <= SIZES[-1]:
            break
        del s["seen"][gid]
    while size() > SIZES[-1] and s.get("threads"):
        oldest = min(s["threads"], key=lambda m: _at(s["threads"][m]))
        del s["threads"][oldest]
    for gid in sorted(s.get("seen", {}), key=lambda g: s["seen"][g]):
        if size() <= SIZES[-1]:
            break
        del s["seen"][gid]
    while size() > SIZES[-1] and any(r.get("also") for r in s["read"].values()):
        biggest = max(s["read"].values(), key=lambda r: len(r.get("also", [])))
        biggest["also"] = biggest["also"][1:]
    for gid in [g for g in s["read"] if g not in s["subscribed"]]:
        if size() <= SIZES[-1]:
            break
        del s["read"][gid]
    for gid in sorted(s["read"], key=lambda g: s["read"][g].get("to", "")):
        if size() <= SIZES[-1]:
            break
        del s["read"][gid]
    if size() > SIZES[-1]:
        raise StateError("the state does not fit in 16 KiB even without read marks")
    return s


def seal(state: dict, seed: bytes, group_id: str) -> str:
    """The state encrypted for its group's manifest: JSON padded with spaces to 4, 8
    or 16 KiB, XChaCha20-Poly1305 under ``state_key(seed)`` with the Group ID as
    associated data, nonce first, in base64."""
    plain = _canonical(fit(state))
    size = next(n for n in SIZES if n >= len(plain))
    plain += b" " * (size - len(plain))
    nonce = os.urandom(nb.crypto_aead_xchacha20poly1305_ietf_NPUBBYTES)
    box = nb.crypto_aead_xchacha20poly1305_ietf_encrypt(plain, group_id.encode(), nonce, state_key(seed))
    return base64.b64encode(nonce + box).decode()


def unseal(sealed: str, seed: bytes, group_id: str) -> dict:
    """The state from its manifest; StateError if it is not ours or is damaged."""
    try:
        raw = base64.b64decode(sealed, validate=True)
        n = nb.crypto_aead_xchacha20poly1305_ietf_NPUBBYTES
        plain = nb.crypto_aead_xchacha20poly1305_ietf_decrypt(raw[n:], group_id.encode(), raw[:n],
                                                               state_key(seed))
        state = json.loads(plain.decode().rstrip(" "))
    except Exception as exc:  # noqa: BLE001 - any failure means: not a state we can read
        raise StateError(f"the state cannot be opened ({type(exc).__name__})") from exc
    if not isinstance(state, dict) or state.get("v") != VERSION:
        raise StateError("not a state of this version")
    out = empty()
    out.update(state)          # fields this client does not know are kept (section 4.2)
    return out


def _at(entry) -> str:
    return entry if isinstance(entry, str) else (entry or {}).get("at", "")


def merge(a: dict, b: dict) -> dict:
    """Two states as one (section 7.2): per entry the newer ``at``, a group or person
    is followed if its newest entry says so; the higher starter version; read marks
    the later ``to`` and the union of ``also``; seen the later date and threads the
    newer ``at`` (section 4.5); sent entries united; fields this client does not know
    kept from the newer state."""
    out = empty()
    for name, off in (("subscribed", "unsubscribed"), ("following", "unfollowed")):
        keys = set(a[name]) | set(a[off]) | set(b[name]) | set(b[off])
        for k in keys:
            best = max(((s[name][k], name) for s in (a, b) if k in s[name]),
                       default=(None, name), key=lambda e: _at(e[0]))
            gone = max(((s[off][k], off) for s in (a, b) if k in s[off]),
                       default=(None, off), key=lambda e: _at(e[0]))
            winner = best if best[0] is not None and (gone[0] is None or _at(best[0]) >= _at(gone[0])) else gone
            out[winner[1]][k] = winner[0]
    for name in ("contacts", "ignored", "hidden", "closed_chats"):
        for k in set(a[name]) | set(b[name]):
            out[name][k] = max((s[name][k] for s in (a, b) if k in s[name]), key=_at)
    out["starter"] = max(int(a.get("starter") or 0), int(b.get("starter") or 0))
    if _at(a["settings"]) == _at(b["settings"]):     # as old as each other (two first syncs): both
        out["settings"] = {**a["settings"], **b["settings"]}
    else:
        out["settings"] = max((a["settings"], b["settings"]), key=_at)
    for gid in set(a["read"]) | set(b["read"]):
        marks = [s["read"][gid] for s in (a, b) if gid in s["read"]]
        to = max((m.get("to", "") for m in marks), default="")
        also = sorted({x for m in marks for x in m.get("also", [])})[-MAX_ALSO:]
        out["read"][gid] = {"to": to, "also": also}
    for gid in set(a.get("seen", {})) | set(b.get("seen", {})):        # section 4.5
        out["seen"][gid] = max(s["seen"][gid] for s in (a, b) if gid in s.get("seen", {}))
    for mid in set(a.get("threads", {})) | set(b.get("threads", {})):
        out["threads"][mid] = max((s["threads"][mid] for s in (a, b) if mid in s.get("threads", {})),
                                  key=_at)
    newer, older = (a, b) if a.get("updated", "") >= b.get("updated", "") else (b, a)
    for k in set(a) | set(b):           # fields this client does not know: the newer state's
        if k not in out:
            out[k] = newer.get(k, older.get(k))
    sent = {e["msgid"]: e for s in (a, b) for e in s.get("sent", []) if isinstance(e, dict) and "msgid" in e}
    out["sent"] = sorted(sent.values(), key=lambda e: e.get("at", ""))
    out["updated"] = max(a.get("updated", ""), b.get("updated", ""))
    return out


def same(a: dict, b: dict) -> bool:
    """Whether two states say the same, whatever their ``updated``."""
    strip = lambda s: {k: v for k, v in s.items() if k != "updated"}    # noqa: E731
    return _canonical(strip(a)) == _canonical(strip(b))


def state_id(public_key: bytes) -> str:
    """``state@<fingerprint>`` (UN-RFC 0044 section 3)."""
    from .groups import make_group_id
    return make_group_id("state", public_key)


def state_manifest(owner, sealed: str, *, serial: int, pow_bits: int):
    """The manifest that is the state (section 3): type ``state``, no articles."""
    from .groups import manifest_article
    data = {"v": 1, "name": "state", "type": "state", "owner": owner.key_text,
            "serial": serial, "state": sealed}
    return manifest_article(owner, state_id(owner.public_key), data, pow_bits)
