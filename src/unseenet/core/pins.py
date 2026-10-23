"""Pinned posts (UN-RFC 0033), the first kind of kept articles (UN-RFC 0017 section 2.1).

Pins and unpins are *markers*; the posts they keep are *targets*. Which pins are
in force is worked out from the markers a node or client holds and the group's
current manifest alone, so every node and client comes to the same result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import crypto
from .article import Article, new_article

MAX_PINS_DEFAULT = 5          # section 4.1
MAX_PINS_MAX = 25
MAX_NOTE = 256                # characters of a pin's note (section 3)
KEPT_PER_GROUP = 256          # targets kept in one group, all kinds (UN-RFC 0017 section 2.2)
PIN, UNPIN = "pin", "unpin"


@dataclass(frozen=True)
class Marker:
    message_id: str
    target: str
    action: str               # "pin" or "unpin"
    author_key: str           # the key as text
    date: int                 # the marker's Date, unix seconds
    supersedes: tuple[str, ...] = ()   # the markers it replaces (section 3.1)

    @property
    def newest_first(self) -> tuple[int, str]:
        """Sort key: the latest Date first, on a tie the lower Message-ID (UN-RFC
        0042 section 5.2, which section 4.2 uses)."""
        return (-self.date, self.message_id)


def max_pins(manifest_data: dict) -> int:
    """The manifest's ``max_pins`` (section 4.1); ValueError if not 0-25."""
    value = manifest_data.get("max_pins", MAX_PINS_DEFAULT)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_PINS_MAX:
        raise ValueError(f"max_pins must be an integer from 0 to {MAX_PINS_MAX}")
    return value


def current(markers, allowed) -> dict[str, Marker]:
    """For each target, the marker that decides (section 4.2): among those whose
    author is in ``allowed`` (owner and moderators now), one no other of them names
    in Supersedes; of several, the latest Date, then the lower Message-ID."""
    by_target: dict[str, list[Marker]] = {}
    for m in markers:
        if m.author_key in allowed:
            by_target.setdefault(m.target, []).append(m)
    out = {}
    for target, ms in by_target.items():
        named = {s for m in ms for s in m.supersedes}
        heads = [m for m in ms if m.message_id not in named] or ms
        out[target] = min(heads, key=lambda m: m.newest_first)
    return out


def in_force(markers, *, owner: str, moderators, limit: int, withdrawn=()) -> list[Marker]:
    """The pins in force, newest first (section 4.2). ``owner`` and ``moderators``
    are keys as text from the current manifest; ``withdrawn``: targets withdrawn by
    a valid cancel."""
    gone = set(withdrawn)
    pins = [m for m in current(markers, {owner, *moderators}).values()
            if m.action == PIN and m.target not in gone]
    pins.sort(key=lambda m: m.newest_first)
    return pins[:max(0, min(limit, KEPT_PER_GROUP))]


def pin_article(identity: crypto.Identity, group_id: str, target: str, *, unpin: bool = False,
                note: str = "", replaces=(), pow_bits: int = 18,
                now: datetime | None = None) -> Article:
    """A signed pin or unpin of ``target`` (a Message-ID with its angle brackets).
    ``replaces``: the pin or unpin of the same target it replaces, newest first
    (section 3.1)."""
    if len(note) > MAX_NOTE:
        raise ValueError(f"a pin's note is at most {MAX_NOTE} characters")
    body = (note.strip() + "\n") if note.strip() else ""
    extra = [("Control", f"{UNPIN if unpin else PIN} {target}")]
    if replaces:
        extra.append(("Supersedes", " ".join(list(replaces)[:32])))
    art = new_article(group_id, None, body, now=now, extra=extra)
    return art.finalize(identity, pow_bits)
