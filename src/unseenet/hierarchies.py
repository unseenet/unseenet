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
