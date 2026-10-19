"""Search and filter a list of groups (#13), shared by the terminal and the web client.

A query is words and filters, all of which must match:

- a word matches the group's name, title or description, in any case;
- ``type:open``, ``type:moderated``, ``type:channel``, ``type:closed``, ``type:inbox``,
  ``type:local``, and ``type:chat`` for chat groups (a chat view, or chat lines
  only); several ``type:`` filters mean any of them;
- ``owner:me`` - groups one of your keys owns;
- ``subscribed`` (or ``is:subscribed``) and ``-subscribed`` (not yet);
- a wildmat with ``*`` or ``?`` over the name, e.g. ``dk.*`` or ``*.marsvin``.

The filter runs in the client, on the list it already has, so the node learns
nothing about what you look for. A ``type:`` filter needs each group's manifest;
a client fetches the ones it lacks in a few requests with XUN-MANIFESTS (UN-RFC
0041) and checks them like any manifest.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

TYPES = ("open", "moderated", "channel", "closed", "inbox", "local", "chat")
HELP = ("words, type:chat|open|moderated|channel|closed|local, owner:me, "
        "subscribed, dk.*")


@dataclass
class GroupFilter:
    words: list[str] = field(default_factory=list)
    types: set[str] = field(default_factory=set)
    owner_me: bool = False
    subscribed: bool | None = None
    patterns: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)     # filters not understood

    def __bool__(self) -> bool:
        return bool(self.words or self.types or self.owner_me
                    or self.subscribed is not None or self.patterns)

    @property
    def needs_manifests(self) -> bool:
        return bool(self.types)


def parse(query: str) -> GroupFilter:
    f = GroupFilter()
    for token in query.split():
        low = token.lower()
        if low.startswith("type:"):
            value = low[5:]
            if value in TYPES:
                f.types.add(value)
            else:
                f.unknown.append(token)
        elif low == "owner:me":
            f.owner_me = True
        elif low in ("subscribed", "is:subscribed"):
            f.subscribed = True
        elif low in ("-subscribed", "not:subscribed"):
            f.subscribed = False
        elif "*" in token or "?" in token:
            f.patterns.append(low)
        elif low.split(":", 1)[0] in ("owner", "is", "not") and ":" in low:
            f.unknown.append(token)          # a filter we do not know: not a word either
        else:
            f.words.append(low)
    return f


def _type_matches(types: set[str], gtype: str | None, data: dict) -> bool:
    for t in types:
        if t == "local" and data.get("local"):
            return True
        if t == "chat" and (data.get("view") == "chat" or data.get("kinds") == ["chat"]):
            return True
        if t == gtype:
            return True
    return False


def matches(f: GroupFilter, group_id: str, *, description: str = "", gtype: str | None = None,
            data: dict | None = None, subscribed: bool = False,
            my_fingerprints: tuple[str, ...] = ()) -> bool:
    """Whether a group matches. ``data`` is its manifest data if known; a group of
    unknown type never matches a ``type:`` filter."""
    data = data or {}
    name = group_id.rpartition("@")[0] or group_id
    if f.subscribed is not None and subscribed != f.subscribed:
        return False
    if f.owner_me and group_id.rpartition("@")[2] not in my_fingerprints:
        return False
    if f.patterns and not any(fnmatch.fnmatchcase(name.lower(), p) for p in f.patterns):
        return False
    if f.types and not _type_matches(f.types, gtype or data.get("type"), data):
        return False
    if f.words:
        text = " ".join((name, str(data.get("title", "")), str(data.get("description", "")),
                         description)).lower()
        if not all(w in text for w in f.words):
            return False
    return True
