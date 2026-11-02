#!/usr/bin/env python3
"""Move one of the project's lists to its list council (UN-RFC 0020 section 10, #56).

    python3 tools/project/move_lists.py unseenet.lists@<fp> [--list nodes|root|entrances|gateways] [--dry-run] [--force]

The last step the project key takes in that list. Run it once the list council counts
(``unseenet council show``), keeps that list, its import is posted, and its replicas have
posted a list of their own.

It posts a last manifest for the project's group (unseenet.nodes, unseenet.hierarchies
for ``--list root``, unseenet.entrances for ``--list entrances``), signed by the project key, with ``moved_to`` (the list council's
Group ID) and ``moved_on`` (now). Clients that read it take the council's list from then
on; the old group's lists are read only until the council has one. From then on the
project key has no part in that list. For the node list, retire the GitHub workflows that
kept it (node-request, node-health) afterwards; for the entrance list, entrance-request
and entrance-health.

``--list gateways`` moves the gateway directory (UN-RFC 0038 section 6.1): unseenet.gateways
gets ``moved_to`` naming the council's open directory (its ``announce.gateways``, made with
``unseenet council add-directory``) - the directory itself, not the council, since anybody
announces there and nothing needs counting. Clients and gateways read and post there.
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
from unseenet.core.gateways import DIRECTORY_GROUP
from unseenet.core.groups import manifest_article
from unseenet import hierarchies as hz
from unseenet.known_nodes import ENTRANCES_GROUP, NODES_GROUP, parse_entrance_list, parse_node_list

GROUPS = {"nodes": (NODES_GROUP, parse_node_list), "root": (hz.HIERARCHIES_GROUP, hz.parse_root_list),
          "entrances": (ENTRANCES_GROUP, parse_entrance_list), "gateways": (DIRECTORY_GROUP, None)}


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("council", help="the list council's Group ID, unseenet.lists@<fp>")
    p.add_argument("--list", choices=sorted(GROUPS), default="nodes", help="which list (default nodes)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="also if the council does not count yet or has posted no list")
    args = p.parse_args()
    if "@" not in args.council:
        sys.exit("give the council's group: unseenet.lists@<its fingerprint>")

    group, parse = GROUPS[args.list]
    s = open_owner_session()
    owner = s.identity()
    entry = s.data["groups"].get(group, {})
    current = entry.get("manifest")
    if not entry.get("owner") or not current:
        sys.exit(f"{group} is not in the owner vault")
    if current.get(nm.MOVED_TO):
        sys.exit(f"{group} says already that it moved to {current[nm.MOVED_TO]}")
    chain = await s.council_chain(args.council)
    if chain.current is None and not args.force:
        sys.exit(f"{args.council} does not count yet: not every founding member has posted "
                 "its copy of the genesis (unseenet council show ...). --force to go on anyway.")
    target = args.council
    if args.list == "gateways":                  # an open directory, not a list
        lc = ls.list_council(chain.current.data) if chain.current is not None else None
        target = (lc.announce.get("gateways") if lc is not None else None) or ""
        if not target:
            sys.exit(f"{args.council} keeps no gateway directory yet (unseenet council "
                     "add-directory ... gateways, and its proposal)")
        print(f"{args.council}: gateway directory {target}")
    elif chain.current is not None:
        lc = ls.list_council(chain.current.data)
        if lc is None or args.list not in lc.lists:
            sys.exit(f"{args.council} keeps no {args.list} list")
        print(f"{args.council}: {len(chain.current.keys)} members, {args.list} list "
              f"{lc.lists[args.list]}")
        if await s._council_list(args.council, args.list, parse) is None and not args.force:
            sys.exit(f"The council's replicas have not posted a {args.list} list yet (the first "
                     "comes two days after it was added). --force to go on anyway.")
    data = dict(current)
    data.update({"serial": int(current["serial"]) + 1, nm.MOVED_TO: target,
                 nm.MOVED_ON: nm.rfc3339(datetime.now(timezone.utc))})
    print(f"{group}: manifest serial {data['serial']}, moved_to {target}")
    if args.dry_run:
        print("--dry-run: nothing posted.")
        return
    raw = manifest_article(owner, group, data, pow_bits=_owner.POW_BITS)
    if await post_everywhere([raw], session=s) == 0:
        sys.exit("No node took the manifest. Run this again later.")
    entry["manifest"] = data
    s.save()
    await s.close()
    print(f"Done. Clients take the council's {args.list} "
          f"{'directory' if args.list == 'gateways' else 'list'} from now on.")


if __name__ == "__main__":
    asyncio.run(main())
