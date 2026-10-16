#!/usr/bin/env python3
"""The project's groups, created and owned by the project key.

    python tools/project/create_groups.py [--dry-run]

This is the list of every group the project owns, with its type, its posters,
its view and its rules, so that anyone can see how the project is set up and
do the same for their own. Missing groups are created. A group that exists
(the owner vault knows it) is left alone, except that it gets a new manifest
if its view differs from the one listed here: the groups that carry lists
and certificates for programs are `data` groups (UN-RFC 0008 section
3.1.1), which clients hide when people browse. Everything is posted over
Tor to the project's nodes. --dry-run signs everything and posts and stores
nothing.

Posters are keys the project key lets post in a channel, so that automation
never needs the project key itself:

- github_poster: the GitHub Actions key (repository secret
  UNSEENET_ANNOUNCE_SEED), which posts releases, the node list, the root list
  and the project's hierarchy list (tools/announce.py);
- registrar keys: see setup_registrar.py.
"""

from __future__ import annotations

import asyncio
import json
import sys

import _owner
from _owner import FP, open_owner_session, post_everywhere

from unseenet.core.groups import make_manifest, manifest_article

TALK = """The place to talk about Unseenet itself: the protocol (the UN-RFCs), the
node and client software, ideas, bugs and questions. Danish is fine too.
To try posting, use unseenet.test."""

ANNOUNCE = """Announcements from the Unseenet project: releases, security notices,
changes to the network. Only the project posts here - it is a channel.
Discussion belongs in unseenet@""" + FP + "."

NODES = """The list of known Unseenet nodes, for clients to read. Each post is one
complete list as JSON (UN-RFC 0010); the newest one counts. Only the project
posts here. To have a node listed, use the "Add my node" form on GitHub."""

HIERARCHIES = """The project's root list of hierarchies (UN-RFC 0018), for clients and
nodes to read. Each post is one complete list as JSON; the newest one counts.
It is kept in the project's repository and changed by pull request. To ask
for a hierarchy, use the "Request a hierarchy" form on GitHub, or write to
the project's inbox. Requests are discussed in unseenet.admin@""" + FP + "."

CHECKGROUPS = """The project's hierarchy list for unseenet.* (UN-RFC 0018 section 5): which
group each name in the unseenet hierarchy means. Each post is one complete
list as JSON; the newest one counts. Only the project posts here."""

NAMES = """The project's registrar for names of identities (UN-RFC 0019): the name
certificates its replicas have issued, and their revocation lists. Only the
registrar posts here. To claim a name, use your client; it writes to the
claim inbox named in this group's manifest. Names are first come, first
served; top-level domains and reserved names are not given out. Complaints
about impersonation go to unseenet.admin@""" + FP + "."

ADMIN = """Requests for hierarchies and the project's decisions on them (UN-RFC 0018
section 7), and complaints about names used to impersonate someone (UN-RFC
0019 section 6.7). Decisions are made in public, here or on GitHub. General
talk about Unseenet belongs in unseenet@""" + FP + "."

TEST = "Use this group to test posting, replies and your setup. Anything goes."

# name, type, view, title, description, rules, poster (a key in the vault), min_pow.
# unseenet and unseenet.test were made before this script, with fewer settings;
# they are listed so that the set is complete.
GROUPS = (
    ("unseenet", "open", "threads", "Unseenet - the project: protocol, software, ideas",
     "Talk about Unseenet itself.", TALK, None, 20),
    ("unseenet.test", "open", "threads", "Unseenet test posts - say hello",
     "For trying things out.", TEST, None, 20),
    ("unseenet.announce", "channel", "threads", "Unseenet announcements: releases and news",
     "Releases, security notices and network news from the Unseenet project.", ANNOUNCE,
     "github_poster", 20),
    ("unseenet.nodes", "channel", "data", "Known Unseenet nodes (for clients)",
     "The signed list of known nodes that clients read (UN-RFC 0010).", NODES, "github_poster", 20),
    ("unseenet.hierarchies", "channel", "data", "Hierarchies: the project's root list",
     "The signed list of hierarchies and their maintainers (UN-RFC 0018).", HIERARCHIES,
     "github_poster", 20),
    ("unseenet.checkgroups", "channel", "data", "The groups of the unseenet hierarchy",
     "The project's hierarchy list for unseenet.* (UN-RFC 0018).", CHECKGROUPS,
     "github_poster", 20),
    ("unseenet.names", "channel", "data", "Names: the project's registrar",
     "Name certificates and revocations for identities (UN-RFC 0019).", NAMES,
     "registrar_poster", 20),
    ("unseenet.admin", "open", "threads", "Hierarchy requests and name disputes",
     "Requests for hierarchies, decisions, and complaints about names.", ADMIN, None, 22),
)


async def main() -> None:
    dry = "--dry-run" in sys.argv[1:]
    s = open_owner_session()
    owner = s.identity()
    todo = []                                   # (article, type, new group?)
    for name, gtype, view, title, desc, rules, poster, min_pow in GROUPS:
        gid = f"{name}@{owner.fingerprint}"
        entry = s.data["groups"].get(gid, {})
        if entry.get("owner"):
            current = entry.get("manifest") or {}
            if not current or current.get("view", "threads") == view:
                print(f"{gid}: exists, unchanged")
                continue
            data = dict(current, view=view, serial=int(current["serial"]) + 1)
            todo.append((manifest_article(owner, gid, data, pow_bits=_owner.POW_BITS), gtype, False))
            print(f"{gid}: new manifest, serial {data['serial']}, view {view}")
            continue
        if poster and poster not in s.data:
            sys.exit(f"{gid} needs the {poster} key, which is not in the vault")
        posters = [s.data[poster]["key"]] if poster else []
        art = make_manifest(owner, name, gtype, title=title, description=desc, rules=rules,
                            posters=posters, min_pow=min_pow, retention_days=90,
                            view=None if view == "threads" else view, pow_bits=_owner.POW_BITS)
        todo.append((art, gtype, True))
        print(f"{gid}: will create ({gtype}, view {view}, posters {posters or 'none'})")
    if not todo or dry:
        print("Nothing to do." if not todo else "--dry-run: nothing posted or stored.")
        return
    if await post_everywhere([a.to_bytes() for a, _, _ in todo]) == 0:
        sys.exit("No node took the manifests; nothing stored. Try again later.")
    for art, gtype, new in todo:
        entry = s.group_entry(art.group)
        entry.update({"type": gtype, "owner": True, "owner_key": owner.key_text,
                      "manifest": json.loads(art.body)})
        if new:
            s.subscribe(art.group)
    s.save()
    await s.close()
    print("Done: " + ", ".join(a.group for a, _, _ in todo))


if __name__ == "__main__":
    asyncio.run(main())
