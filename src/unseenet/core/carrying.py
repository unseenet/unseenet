"""What a node carries (UN-RFC 0055 sections 2-4): pattern lists over group names, the
``carries`` object of node information, and the network's own groups every node carries.

Belongs here: the pure rules - matching a pattern list, checking and building
``carries``, and which groups are the network's own (the infrastructure groups and the
endorsed groups of ``unseenet.*``, given the hierarchy list for ``unseenet``).

Not here: reading the newest hierarchy list from a node's store
(``node/server/carrying.py``), peering (``node/peering.py``)."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable

from ..known_nodes import (ANNOUNCE_GROUP, CANARY_GROUP, DATA_GROUPS, ENTRANCES_GROUP,
                           NODES_GROUP, RELEASES_GROUP)

MAX_PATTERNS = 64                # section 3.1
ALL = ("*",)

# Section 4: the infrastructure groups that exist today, by the Group IDs the reference
# client pins. Council successors and new ones (unseenet.nodes.announce, the scribes)
# count once the council of unseenet.* endorses them in its hierarchy list (4.1).
INFRASTRUCTURE = frozenset({NODES_GROUP, ENTRANCES_GROUP, ANNOUNCE_GROUP, RELEASES_GROUP,
                            CANARY_GROUP, *DATA_GROUPS})


class CarriesProblem(ValueError):
    pass


def group_name(group_id: str) -> str:
    return group_id.rpartition("@")[0] or group_id


def matches(patterns: Iterable[str], name: str) -> bool:
    """Section 2: the last pattern that matches decides; ``!`` excludes; a name no
    pattern matches is not carried."""
    result = False
    for pat in patterns:
        neg = pat.startswith("!")
        if fnmatch.fnmatchcase(name, pat[1:] if neg else pat):
            result = not neg
    return result


def check_patterns(patterns) -> list[str]:
    """A valid pattern list: 1 to 64 non-empty strings without commas or spaces."""
    if isinstance(patterns, str):
        patterns = [p.strip() for p in patterns.split(",")]
    if not isinstance(patterns, (list, tuple)) or not 1 <= len(patterns) <= MAX_PATTERNS:
        raise CarriesProblem(f"carries: a list of 1 to {MAX_PATTERNS} patterns")
    out = []
    for p in patterns:
        if not isinstance(p, str) or not p.lstrip("!") or any(c in p for c in ", \t@"):
            raise CarriesProblem(f"carries: {p!r} is not a pattern over group names "
                                 "(such as alt.* or !dk.politik.*)")
        out.append(p)
    return out


def carries_object(patterns, *, files: bool, sites: bool, new: bool,
                   closed: bool = True, key_bound: str = "all") -> dict:
    """The ``carries`` field of node information and announcements (section 3.1)."""
    out: dict = {"groups": list(patterns)}
    if files:
        out["files"] = True
    if sites:
        out["sites"] = True
    if not closed:
        out["closed"] = False
    if key_bound != "all":
        out["key_bound"] = key_bound
    if not new:
        out["new"] = False
    return out


def read_carries(info: dict | None) -> list[str]:
    """The pattern list a peer or announced node gives; without ``carries`` it is
    ``["*"]``, what nodes did before (section 3.1). A bad one is read as nothing but
    the network's own groups."""
    c = (info or {}).get("carries")
    if c is None:
        return list(ALL)
    try:
        return check_patterns(c.get("groups") if isinstance(c, dict) else None)
    except CarriesProblem:
        return []


def network_groups(endorsed: Iterable[str] = ()) -> frozenset[str]:
    """Section 4: the groups every node carries - the infrastructure groups and the
    groups the hierarchy list for ``unseenet`` endorses (4.1). Only endorsed Group
    IDs count, never a name: anybody may create ``unseenet.something@...``."""
    return INFRASTRUCTURE | {g for g in endorsed if group_name(g).split(".")[0] == "unseenet"}


def carries(group_id: str, patterns: Iterable[str], network: frozenset[str]) -> bool:
    """Whether a node with ``patterns`` carries an ordinary group (section 2). Key-bound
    and local groups follow their own rules (UN-RFC 0040 section 8, section 3.3)."""
    return group_id in network or matches(patterns, group_name(group_id))
