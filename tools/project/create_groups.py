#!/usr/bin/env python3
"""The project's groups, created and owned by the project key.

    python tools/project/create_groups.py [--dry-run]

This is the list of every group the project owns, with its type, its posters
and its rules, so that anyone can see how the project is set up and do the
same for their own. Groups that already exist (the owner vault knows them)
are skipped; only missing ones are created and posted over Tor to the
project's nodes. --dry-run signs everything and posts and stores nothing.

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

from unseenet.core.groups import make_manifest

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

# name, type, title, description, rules, poster (a key in the vault), min_pow.
# unseenet and unseenet.test were made before this script, with fewer settings;
# they are listed so that the set is complete.
GROUPS = (
    ("unseenet", "open", "Unseenet - the project: protocol, software, ideas",
     "Talk about Unseenet itself.", TALK, None, 20),
    ("unseenet.test", "open", "Unseenet test posts - say hello",
     "For trying things out.", TEST, None, 20),
    ("unseenet.announce", "channel", "Unseenet announcements: releases and news",
     "Releases, security notices and network news from the Unseenet project.", ANNOUNCE,
     "github_poster", 20),
    ("unseenet.nodes", "channel", "Known Unseenet nodes (for clients)",
     "The signed list of known nodes that clients read (UN-RFC 0010).", NODES, "github_poster", 20),
    ("unseenet.hierarchies", "channel", "Hierarchies: the project's root list",
     "The signed list of hierarchies and their maintainers (UN-RFC 0018).", HIERARCHIES,
     "github_poster", 20),
    ("unseenet.checkgroups", "channel", "The groups of the unseenet hierarchy",
     "The project's hierarchy list for unseenet.* (UN-RFC 0018).", CHECKGROUPS,
     "github_poster", 20),
    ("unseenet.names", "channel", "Names: the project's registrar",
     "Name certificates and revocations for identities (UN-RFC 0019).", NAMES,
     "registrar_poster", 20),
    ("unseenet.admin", "open", "Hierarchy requests and name disputes",
     "Requests for hierarchies, decisions, and complaints about names.", ADMIN, None, 22),
)


async def main() -> None:
    dry = "--dry-run" in sys.argv[1:]
    s = open_owner_session()
    owner = s.identity()
    todo = []
    for name, gtype, title, desc, rules, poster, min_pow in GROUPS:
        gid = f"{name}@{owner.fingerprint}"
        if s.data["groups"].get(gid, {}).get("owner"):
            print(f"{gid}: exists, skipped")
            continue
        if poster and poster not in s.data:
            sys.exit(f"{gid} needs the {poster} key, which is not in the vault")
        posters = [s.data[poster]["key"]] if poster else []
        art = make_manifest(owner, name, gtype, title=title, description=desc, rules=rules,
                            posters=posters, min_pow=min_pow, retention_days=90,
                            pow_bits=_owner.POW_BITS)
        todo.append((art, gtype))
        print(f"{gid}: will create ({gtype}, posters {posters or 'none'})")
    if not todo or dry:
        print("Nothing to create." if not todo else "--dry-run: nothing posted or stored.")
        return
    if await post_everywhere([a.to_bytes() for a, _ in todo]) == 0:
        sys.exit("No node took the manifests; nothing stored. Try again later.")
    for art, gtype in todo:
        s.group_entry(art.group).update({"type": gtype, "owner": True, "owner_key": owner.key_text,
                                         "manifest": json.loads(art.body)})
        s.subscribe(art.group)
    s.save()
    await s.close()
    print("Created: " + ", ".join(a.group for a, _ in todo))


if __name__ == "__main__":
    asyncio.run(main())
