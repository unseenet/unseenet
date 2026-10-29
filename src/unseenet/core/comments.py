"""How long a thread takes comments, and closing one (UN-RFC 0030 sections 3.1-3.3).

An entry's own deadline (``Comment-Days`` on its root) and the group's ``comment_days``
give a thread its deadline - the shorter of the two, from the root's Date. Comments on
one entry can also be closed and opened again with markers (``comments-close`` and
``comments-open``), replaced with Supersedes as pins are (UN-RFC 0033): which marker
decides is worked out twice, among the entry's author's own and among the owner's and
moderators', and comments are closed when either current marker is a close. Nodes and
clients use the same functions, so they come to the same result.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import crypto
from . import pins as pn
from .article import Article, new_article, parse_date

HEADER = "Comment-Days"
CLOSE, OPEN = "comments-close", "comments-open"
ACTIONS = (CLOSE, OPEN)
MAX_NOTE = 256                # characters of a marker's note (section 3.2)


def parse_days(value) -> int:
    """A ``Comment-Days`` value: a whole number of days, 0 or more. ValueError if not."""
    text = str(value).strip()
    if not text.isdigit() or (len(text) > 1 and text[0] == "0") or len(text) > 6:
        raise ValueError("Comment-Days is a whole number of days, 0 or more")
    return int(text)


def own_days(art: Article) -> int | None:
    """The entry's own ``Comment-Days``, None when it has none. ValueError if malformed."""
    value = art.get(HEADER)
    return None if value is None else parse_days(value)


def shorter(*days) -> int | None:
    """The shortest of the given days that are set; None when none is."""
    given = [d for d in days if d is not None]
    return min(given) if given else None


def deadline(root_date: datetime, group_days: int | None, entry_days: int | None) -> datetime | None:
    """Section 3.1: when comments on a thread close - the shorter of the entry's own
    days and the group's, from the root's Date. None: no deadline."""
    days = shorter(group_days, entry_days)
    return None if days is None else root_date + timedelta(days=days)


def closed_by_time(when: datetime, root_date: datetime, group_days: int | None,
                   entry_days: int | None) -> bool:
    """Whether a comment dated ``when`` comes too late (section 3.1). ``0`` days is no
    comments at all, even within the same second."""
    days = shorter(group_days, entry_days)
    return days is not None and (days == 0 or when > root_date + timedelta(days=days))


def root_closed_by_time(root: Article, group_days: int | None, when: datetime) -> bool:
    """``closed_by_time`` for a root article as held (a malformed own value is none)."""
    try:
        entry = own_days(root)
    except ValueError:
        entry = None
    return closed_by_time(when, parse_date(root["Date"]), group_days, entry)


def root_deadline(root: Article, group_days: int | None) -> datetime | None:
    """``deadline`` for a root article as held (a malformed own value counts as none)."""
    try:
        entry = own_days(root)
    except ValueError:
        entry = None
    return deadline(parse_date(root["Date"]), group_days, entry)


def deciding_close(markers, target: str, target_author: str, privileged) -> pn.Marker | None:
    """Section 3.2: the close that keeps comments on ``target`` closed, or None when
    they are open. ``markers``: comment markers (``pins.Marker`` with action ``CLOSE``
    or ``OPEN``); ``target_author``, ``privileged`` (owner and moderators now): keys as
    text. The owner's and moderators' close wins over the author's open; either chain's
    close closes."""
    mine = [m for m in markers if m.target == target and m.action in ACTIONS]
    by_mods = pn.current(mine, set(privileged)).get(target)
    by_author = pn.current(mine, {target_author}).get(target)
    for m in (by_mods, by_author):
        if m is not None and m.action == CLOSE:
            return m
    return None


def may_mark(author: str, target_author: str, owner: str, moderators) -> bool:
    """Who may write a valid marker for an entry: its author, the owner, a moderator."""
    return author in (target_author, owner) or author in set(moderators)


def marker_article(identity: crypto.Identity, group_id: str, target: str, *, close: bool,
                   note: str = "", replaces=(), pow_bits: int = 18,
                   now: datetime | None = None) -> Article:
    """A signed ``comments-close`` (``close``) or ``comments-open`` of ``target``, the thread
    root, with an optional note for readers; ``replaces``: the current marker of the
    same chain, which it names in Supersedes (section 3.2)."""
    note = note.strip()
    if len(note) > MAX_NOTE:
        raise ValueError(f"a note is at most {MAX_NOTE} characters")
    extra = [("Control", f"{CLOSE if close else OPEN} {target}")]
    if replaces:
        extra.append(("Supersedes", " ".join(list(replaces)[:32])))
    art = new_article(group_id, None, (note + "\n") if note else "", now=now, extra=extra)
    return art.finalize(identity, pow_bits)
