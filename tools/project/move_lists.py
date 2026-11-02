#!/usr/bin/env python3
"""Move the project's node list to its list council (UN-RFC 0020 section 10, #56).

    python3 tools/project/move_lists.py unseenet.lists@<fp> [--dry-run] [--force]

The last step the project key takes in the node list. Run it once the list council's
genesis counts (every founding replica has posted its copy: ``unseenet council show``),
its import is posted, and its replicas have posted a node list of their own.

It posts a last manifest for unseenet.nodes, signed by the project key, with
``moved_to`` (the list council's Group ID) and ``moved_on`` (now). Clients that read it
take the council's node list from then on; the old group's lists are read only until the
council has one. From then on the project key has no part in the node list. Retire the
GitHub workflows that kept it (node-request, node-health) afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

import _owner
from _owner import open_owner_session, post_everywhere

from unseenet import names as nm
from unseenet.core import lists as ls
from unseenet.core.groups import manifest_article
from unseenet.known_nodes import NODES_GROUP


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("council", help="the list council's Group ID, unseenet.lists@<fp>")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="also if the council does not count yet or has posted no list")
    args = p.parse_args()
    if "@" not in args.council:
        sys.exit("give the council's group: unseenet.lists@<its fingerprint>")

    s = open_owner_session()
    owner = s.identity()
    entry = s.data["groups"].get(NODES_GROUP, {})
    current = entry.get("manifest")
    if not entry.get("owner") or not current:
        sys.exit(f"{NODES_GROUP} is not in the owner vault")
    if current.get(nm.MOVED_TO):
        sys.exit(f"{NODES_GROUP} says already that it moved to {current[nm.MOVED_TO]}")
    chain = await s.council_chain(args.council)
    if chain.current is None and not args.force:
        sys.exit(f"{args.council} does not count yet: not every founding member has posted "
                 "its copy of the genesis (unseenet council show ...). --force to go on anyway.")
    if chain.current is not None:
        lc = ls.list_council(chain.current.data)
        if lc is None or "nodes" not in lc.lists:
            sys.exit(f"{args.council} keeps no node list")
        print(f"{args.council}: {len(chain.current.keys)} members, node list {lc.lists['nodes']}")
        if await s._council_node_list(args.council) is None and not args.force:
            sys.exit("The council's replicas have not posted a node list yet (the first comes "
                     "two days after the genesis). --force to go on anyway.")
    data = dict(current)
    data.update({"serial": int(current["serial"]) + 1, nm.MOVED_TO: args.council,
                 nm.MOVED_ON: nm.rfc3339(datetime.now(timezone.utc))})
    print(f"{NODES_GROUP}: manifest serial {data['serial']}, moved_to {args.council}")
    if args.dry_run:
        print("--dry-run: nothing posted.")
        return
    raw = manifest_article(owner, NODES_GROUP, data, pow_bits=_owner.POW_BITS)
    if await post_everywhere([raw], session=s) == 0:
        sys.exit("No node took the manifest. Run this again later.")
    entry["manifest"] = data
    s.save()
    await s.close()
    print("Done. Clients take the council's node list from now on.")


if __name__ == "__main__":
    asyncio.run(main())
