"""The root list of hierarchies (UN-RFC 0018, section 4).

The project's root list is kept in the repository (``hierarchies.json``,
changed by pull request) and posted to the channel group
``unseenet.hierarchies`` by the same automation that posts the node list
(UN-RFC 0010). This module reads and checks a root list; deciding what a
client shows for a group (section 8) builds on it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources

from .core import crypto
from .core.groups import split_group_id

HIERARCHIES_GROUP = "unseenet.hierarchies@ph5fc5hop5232qsz"
POLICIES = ("governed", "free", "reserved")
MAX_ENTRIES = 200
MAX_SIZE = 32768                                   # one article (UN-RFC 0002 section 2)
_COMPONENT = re.compile(r"^[a-z0-9][a-z0-9+_-]*$")  # UN-RFC 0004 section 1


@dataclass(frozen=True)
class Hierarchy:
    name: str
    policy: str
    maintainer: str = ""
    list: str = ""
    title: str = ""
    description: str = ""


def _entry(item: dict) -> Hierarchy:
    """One entry; raises ValueError if it is malformed (section 4.1)."""
    name, policy = item.get("name"), item.get("policy")
    if not isinstance(name, str) or not _COMPONENT.match(name) or len(name) > 128:
        raise ValueError(f"bad hierarchy name {name!r}")
    if policy not in POLICIES:
        raise ValueError(f"{name}: unknown policy {policy!r}")
    title, description = item.get("title", ""), item.get("description", "")
    if not isinstance(title, str) or len(title) > 64:
        raise ValueError(f"{name}: title must be a string of at most 64 characters")
    if not isinstance(description, str) or len(description) > 200:
        raise ValueError(f"{name}: description must be a string of at most 200 characters")
    maintainer, lst = item.get("maintainer", ""), item.get("list", "")
    if policy == "governed":
        try:
            key = crypto.key_from_text(maintainer)
            _, fp = split_group_id(lst)
        except (crypto.CryptoError, ValueError, TypeError) as exc:
            raise ValueError(f"{name}: governed needs a maintainer key and a list group") from exc
        if crypto.fingerprint(key) != fp:
            raise ValueError(f"{name}: the list group is not owned by the maintainer")
    return Hierarchy(name, policy, maintainer if policy == "governed" else "",
                     lst if policy == "governed" else "", title, description)


def parse_root_list(text: str, *, strict: bool = False) -> tuple[str, dict[str, Hierarchy]]:
    """(updated, hierarchies by name) from a root list.

    Raises ValueError if the list as a whole is invalid: not JSON, `v` not 1,
    or a name listed twice. A malformed entry makes its name `reserved`, as
    section 4.1 says; with ``strict=True`` (for the project's own file) it is
    an error instead, so a mistake is caught before the list is posted.
    """
    if len(text.encode()) > MAX_SIZE:
        raise ValueError(f"the root list must fit in {MAX_SIZE} octets")
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("hierarchies"), list):
        raise ValueError("not a version 1 root list")
    items = data["hierarchies"]
    if len(items) > MAX_ENTRIES:
        raise ValueError(f"at most {MAX_ENTRIES} hierarchies")
    names = [i.get("name") for i in items if isinstance(i, dict)]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"listed more than once: {', '.join(sorted(map(str, dupes)))}")
    out: dict[str, Hierarchy] = {}
    for item in items:
        if not isinstance(item, dict):
            if strict:
                raise ValueError(f"entry is not an object: {item!r}")
            continue
        try:
            h = _entry(item)
        except ValueError:
            if strict:
                raise
            name = item.get("name")
            if isinstance(name, str) and _COMPONENT.match(name):
                out[name] = Hierarchy(name, "reserved")
            continue
        out[h.name] = h
    return str(data.get("updated", ""))[:32], out


def builtin_root_list() -> tuple[str, dict[str, Hierarchy]]:
    """The project's root list as shipped with this version."""
    return parse_root_list(resources.files("unseenet").joinpath("hierarchies.json").read_text(),
                           strict=True)


# --- hierarchy lists (section 5) ----------------------------------------------------

CHECKGROUPS_GROUP = "unseenet.checkgroups@ph5fc5hop5232qsz"   # the project's list for unseenet.*
MAX_DEPTH = 4                                                  # section 5.3

# ISO 3166-1 alpha-2 country codes: regional hierarchies (section 4.2). Other
# two-letter names are reserved.
COUNTRY_CODES = frozenset("""
ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn bo
bq br bs bt bv bw by bz ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz de dj
dk dm do dz ec ee eg eh er es et fi fj fk fm fo fr ga gb gd ge gf gg gh gi gl gm gn gp
gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im in io iq ir is it je jm jo jp ke kg
kh ki km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me mf mg mh mk ml
mm mn mo mp mq mr ms mt mu mv mw mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pe
pf pg ph pk pl pm pn pr ps pt pw py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl
sm sn so sr ss st sv sx sy sz tc td tf tg th tj tk tl tm tn to tr tt tv tw tz ua ug um
us uy uz va vc ve vg vi vn vu wf ws ye yt za zm zw""".split())


@dataclass(frozen=True)
class Block:
    key: str
    reason: str
    since: str = ""
    until: str = ""


@dataclass(frozen=True)
class HierarchyList:
    hierarchy: str
    updated: str
    groups: dict[str, str]                     # name -> endorsed Group ID
    sub: dict[str, Hierarchy]                  # full name -> governed or free sub-hierarchy
    blocked: tuple[Block, ...] = ()            # section 5.4


MAX_BLOCK_REASON = 200


def _blocks(items) -> tuple[Block, ...]:
    """Valid entries of ``blocked`` (section 5.4); a key listed twice counts for neither."""
    found: dict[str, Block] = {}
    twice: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key, reason = item.get("key"), item.get("reason")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= MAX_BLOCK_REASON:
            continue
        try:
            crypto.key_from_text(key)
        except (crypto.CryptoError, TypeError, ValueError):
            continue
        if key in found:
            twice.add(key)
        found[key] = Block(key, reason.strip(), str(item.get("since", ""))[:40],
                           str(item.get("until", ""))[:40])
    return tuple(b for k, b in found.items() if k not in twice)


def _expired(b: Block, now) -> bool:
    if not b.until:
        return False
    from datetime import datetime
    try:
        until = datetime.fromisoformat(b.until.replace("Z", "+00:00"))
    except ValueError:
        return True                                # unreadable: ignore the entry
    if until.tzinfo is None:
        return True
    return until <= now


def _within(name: str, hierarchy: str) -> bool:
    return name == hierarchy or name.startswith(hierarchy + ".")


def parse_hierarchy_list(text: str, hierarchy: str) -> HierarchyList:
    """A maintainer's list for ``hierarchy`` (section 5.1). ValueError if invalid as a whole."""
    if len(text.encode()) > MAX_SIZE:
        raise ValueError(f"a hierarchy list must fit in {MAX_SIZE} octets")
    data = json.loads(text)
    if (not isinstance(data, dict) or data.get("v") != 1 or data.get("hierarchy") != hierarchy
            or not isinstance(data.get("groups"), list)):
        raise ValueError(f"not a version 1 hierarchy list for {hierarchy}")
    sub: dict[str, Hierarchy] = {}
    for item in data.get("sub") or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"]
        if not _within(name, hierarchy) or name == hierarchy or item.get("policy") not in ("governed", "free"):
            continue
        try:
            components = name.split(".")
            if not all(_COMPONENT.match(c) for c in components):
                continue
            h = _entry({**item, "name": components[-1]})         # the same checks as the root list
        except ValueError:
            continue
        sub[name] = Hierarchy(name, h.policy, h.maintainer, h.list, h.title, h.description)
    seen: dict[str, str] = {}
    twice: set[str] = set()
    for item in data["groups"]:
        try:
            name, _ = split_group_id(item["group"])
        except (KeyError, TypeError, ValueError):
            continue
        if not _within(name, hierarchy) or any(_within(name, s) for s in sub):
            continue
        if name in seen:
            twice.add(name)
        seen[name] = item["group"]
    groups = {n: g for n, g in seen.items() if n not in twice}       # endorsed twice: neither counts
    return HierarchyList(hierarchy, str(data.get("updated", ""))[:32], groups, sub,
                         _blocks(data.get("blocked")))


def builtin_checkgroups() -> HierarchyList:
    """The project's list for unseenet.* as shipped with this version."""
    return parse_hierarchy_list(resources.files("unseenet").joinpath("checkgroups.json").read_text(),
                                "unseenet")


# --- what a group name means (section 8.1) -------------------------------------------

def policy_of(top: str, root: dict[str, Hierarchy]) -> Hierarchy:
    """The policy of a top-level hierarchy, listed or not (section 4.2)."""
    if top in root:
        return root[top]
    if len(top) == 2:
        return Hierarchy(top, "free" if top in COUNTRY_CODES else "reserved")
    return Hierarchy(top, "free")                     # unclaimed: behaves as free


def deciding(name: str, root: dict[str, Hierarchy],
             lists: dict[str, HierarchyList]) -> tuple[Hierarchy, HierarchyList | None]:
    """The deepest known hierarchy that decides ``name``, and its list if governed."""
    h = policy_of(name.split(".")[0], root)
    for _ in range(MAX_DEPTH + 1):
        if h.policy != "governed":
            return h, None
        lst = lists.get(h.name)
        if lst is None:
            return h, None                            # governed, but its list is not known
        deeper = [s for s in lst.sub.values() if _within(name, s.name)]
        if not deeper:
            return h, lst
        h = max(deeper, key=lambda s: len(s.name))
    return Hierarchy(h.name, "reserved"), None        # deeper than section 5.3 allows


def chain(name: str, root: dict[str, Hierarchy],
          lists: dict[str, HierarchyList]) -> list[HierarchyList]:
    """The known lists of every governed hierarchy from the top down to the one
    that decides ``name`` (section 5.4)."""
    out: list[HierarchyList] = []
    h = policy_of(name.split(".")[0], root)
    for _ in range(MAX_DEPTH + 1):
        if h.policy != "governed":
            break
        lst = lists.get(h.name)
        if lst is None:
            break
        out.append(lst)
        deeper = [s for s in lst.sub.values() if _within(name, s.name)]
        if not deeper:
            break
        h = max(deeper, key=lambda s: len(s.name))
    return out


def blocks_for(name: str, root: dict[str, Hierarchy], lists: dict[str, HierarchyList],
               now=None) -> dict[str, tuple[str, str]]:
    """{key: (hierarchy, reason)} of the identities blocked for a group name: the
    blocks of every maintainer on the way down; the highest one is reported."""
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    out: dict[str, tuple[str, str]] = {}
    for lst in chain(name, root, lists):
        for b in lst.blocked:
            if b.key not in out and not _expired(b, now):
                out[b.key] = (lst.hierarchy, b.reason)
    return out


def sub_lists_needed(name: str, root: dict[str, Hierarchy],
                     lists: dict[str, HierarchyList]) -> list[Hierarchy]:
    """Governed sub-hierarchies above ``name`` whose lists are not known yet."""
    out = []
    for lst in chain(name, root, lists):
        for s in lst.sub.values():
            if s.policy == "governed" and _within(name, s.name) and s.name not in lists:
                out.append(s)
    return out


@dataclass(frozen=True)
class GroupName:
    status: str            # "endorsed", "unendorsed", "free", "reserved"
    short: bool            # may be shown without the fingerprint
    hierarchy: str


def name_status(group_id: str, root: dict[str, Hierarchy], lists: dict[str, HierarchyList],
                known: set[str]) -> GroupName:
    """How a client may show a group (section 8.1). ``known`` is every Group ID the
    client knows of, so that it can tell whether a free name is unique."""
    name, _ = split_group_id(group_id)
    h, lst = deciding(name, root, lists)
    if h.policy == "governed":
        if lst is not None and lst.groups.get(name) == group_id:
            return GroupName("endorsed", True, h.name)
        return GroupName("unendorsed", False, h.name)
    if h.policy == "reserved":
        return GroupName("reserved", False, h.name)
    same = {g for g in known | {group_id} if g.rpartition("@")[0] == name}
    return GroupName("free", len(same) == 1, h.name)
