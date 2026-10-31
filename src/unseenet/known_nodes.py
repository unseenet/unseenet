"""Nodes a client can start with, and the signed list that keeps them current.

A new client has to connect *somewhere* before it can learn anything, so it
ships with a list of known nodes (``nodes.json``, kept in the repository and
changed by pull request). Once connected, it reads the newest list from the
project's channel group ``unseenet.nodes`` (UN-RFC 0010). That list is:

- **signed**: only the group's owner - the project key pinned below, whose
  fingerprint is in the group ID - and the posters in its signed manifest
  can post there, and the client checks it again itself;
- **fetched over Tor**, from whichever node the client already uses, so
  nobody sees a request to GitHub or anywhere else.

It is a starting point, not a directory: anyone can run a node, and a client
can use any node it is told about (an ``unseenet:`` address can name one).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources

# The Unseenet project's key. It owns the project's groups; its fingerprint
# ph5fc5hop5232qsz is part of their IDs.
PROJECT_KEY = "ed25519:det5dxevwbk36eds2indrzlazyri3fq3bgdzw6kx4ems3o267sya"
NODES_GROUP = "unseenet.nodes@ph5fc5hop5232qsz"
# Known web entrances (UN-RFC 0043 section 8.1), for web clients and the jump page.
ENTRANCES_GROUP = "unseenet.entrances@ph5fc5hop5232qsz"
ANNOUNCE_GROUP = "unseenet.announce@ph5fc5hop5232qsz"
# Signed versions of programs that update through the network (UN-RFC 0043 7.3).
RELEASES_GROUP = "unseenet.releases@ph5fc5hop5232qsz"
# Daily canary posts that check listed nodes are connected (UN-RFC 0021).
CANARY_GROUP = "unseenet.canary@ph5fc5hop5232qsz"
# The project's groups for programs, not people (UN-RFC 0008 section 3.1.1). Their
# manifests say "view": "data"; listing them here lets a client hide them before it
# has read the manifests.
DATA_GROUPS = frozenset({
    NODES_GROUP,
    ENTRANCES_GROUP,
    RELEASES_GROUP,
    CANARY_GROUP,
    "unseenet.hierarchies@ph5fc5hop5232qsz",
    "unseenet.checkgroups@ph5fc5hop5232qsz",
    "unseenet.names@ph5fc5hop5232qsz",
    "unseenet.gateways@ph5fc5hop5232qsz",
})

# The project's groups a new client starts with, so there is something to read.
HELP_GROUP = "unseenet.help@ph5fc5hop5232qsz"
# The groups a new client follows, in versions: a vault takes each version's groups
# once, so groups added later reach those who started earlier too - and a group they
# left is never added again (#388). Add a version; never change an earlier one.
STARTER_GROUP_VERSIONS = (
    ("unseenet@ph5fc5hop5232qsz", ANNOUNCE_GROUP, HELP_GROUP,          # 1
     "unseenet.test@ph5fc5hop5232qsz"),
    ("unseenet.chat@ph5fc5hop5232qsz",),                                # 2 (#388)
    ("unseenet.demo.site@lcgptqqjydt2sevj", "unseenet.demo.feed@lcgptqqjydt2sevj"),      # 3: the demo (#385, #388)
    ("unseenet.help.news@ph5fc5hop5232qsz",),                          # 4: the help bot's news (helpbot#21)
    ("test.unseenet@ph5fc5hop5232qsz", "demo.unseenet.site@lcgptqqjydt2sevj",  # 5: moved out of
     "demo.unseenet.feed@lcgptqqjydt2sevj"),                           # unseenet.* (UN-RFC 0055 4.1)
)
# Starter groups that moved (old -> new): a new vault never gets the old one, and a vault
# that follows the old one follows the new one in its place.
MOVED_STARTER_GROUPS = {
    "unseenet.test@ph5fc5hop5232qsz": "test.unseenet@ph5fc5hop5232qsz",
    "unseenet.demo.site@lcgptqqjydt2sevj": "demo.unseenet.site@lcgptqqjydt2sevj",
    "unseenet.demo.feed@lcgptqqjydt2sevj": "demo.unseenet.feed@lcgptqqjydt2sevj",
}
STARTER_GROUPS = tuple(g for version in STARTER_GROUP_VERSIONS for g in version
                       if g not in MOVED_STARTER_GROUPS)

_ADDRESS = re.compile(r"^([a-z2-7]{56}\.onion|[A-Za-z0-9.-]+)(:\d{1,5})?$")
MAX_NODES = 200


@dataclass(frozen=True)
class KnownNode:
    name: str
    address: str
    description: str = ""
    node_key: str = ""
    operator: str = ""


def parse_node_list(text: str) -> tuple[str, list[KnownNode]]:
    """(updated, nodes) from a UN-RFC 0010 node list. Raises ValueError if malformed."""
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("nodes"), list):
        raise ValueError("not a version 1 node list")
    nodes = []
    for item in data["nodes"][:MAX_NODES]:
        if not isinstance(item, dict):
            continue
        address = str(item.get("address", "")).strip()
        if not _ADDRESS.match(address):
            continue                  # one bad entry does not spoil the list
        nodes.append(KnownNode(name=str(item.get("name", address))[:64],
                               address=address,
                               description=str(item.get("description", ""))[:200],
                               node_key=str(item.get("node_key", ""))[:80],
                               operator=str(item.get("operator", ""))[:80]))
    if not nodes:
        raise ValueError("the list has no usable nodes")
    return str(data.get("updated", ""))[:32], nodes


_ONION = re.compile(r"^[a-z2-7]{56}\.onion$")
MAX_ENTRANCES = 200


def parse_entrance_list(text: str) -> tuple[str, list[dict]]:
    """(updated, entrances) from a list of web entrances (UN-RFC 0043 section 8.1).
    Each entrance has an https ``url``, an ``onion`` address, or both. Raises
    ValueError if the list is malformed or has no usable entrance."""
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("entrances"), list):
        raise ValueError("not a version 1 entrance list")
    out = []
    for item in data["entrances"][:MAX_ENTRANCES]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        onion = str(item.get("onion", "")).strip().lower()
        if url and not re.match(r"^https://[^/\s]+/?$", url):
            url = ""
        if onion and not _ONION.match(onion):
            onion = ""
        if not (url or onion):
            continue
        out.append({"name": str(item.get("name", url or onion))[:64], "url": url, "onion": onion,
                    "operator": str(item.get("operator", ""))[:80],
                    "contact": str(item.get("contact", ""))[:120],
                    "description": str(item.get("description", ""))[:200]})
    if not out:
        raise ValueError("the list has no usable entrances")
    return str(data.get("updated", ""))[:32], out


def builtin_list() -> tuple[str, list[KnownNode]]:
    """The list that came with this version of the client."""
    return parse_node_list(resources.files("unseenet").joinpath("nodes.json").read_text())


def builtin_entrances() -> list[dict]:
    """The web entrances that came with this version of the client (UN-RFC 0043 8.1);
    an empty list if the built-in list cannot be read."""
    try:
        return parse_entrance_list(
            resources.files("unseenet").joinpath("entrances.json").read_text())[1]
    except (OSError, ValueError):
        return []


KNOWN_NODES: tuple[KnownNode, ...] = tuple(builtin_list()[1])
