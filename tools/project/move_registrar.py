#!/usr/bin/env python3
"""Move the project's registrar to its council (UN-RFC 0054 section 14, #691).

    python3 tools/project/move_registrar.py unseenet.names@<fp> [--dry-run] [--force]

The last step the project key takes in the registrar. Run it once the council's
genesis counts (every founding replica has posted its copy: ``unseenet council show``)
and the replicas have re-issued the old group's certificates in the council's group.

It posts a last manifest for unseenet.names, signed by the project key, with
``moved_to`` (the council's Group ID) and ``moved_on`` (now). Clients that read it
take the council's group as the registrar from then on, and keep the old group's
certificates issued before ``moved_on`` until they expire. The manifest no longer
names a claims inbox, so nobody sends claims to the old registrar; its posters stay,
so the certificates they signed stay valid. Stop the old registrar replicas
(``unseenet-registrar``) afterwards. From then on the project key has no part in the
registrar.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

import _owner
from _owner import open_owner_session, post_everywhere

from unseenet import names as nm
from unseenet.core.groups import manifest_article


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("council", help="the council registrar's Group ID, unseenet.names@<fp>")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="also if the council does not count yet")
    args = p.parse_args()
    if not args.council.startswith("unseenet.names@") or args.council == nm.NAMES_GROUP:
        sys.exit("give the council's group: unseenet.names@<its fingerprint>")

    s = open_owner_session()
    owner = s.identity()
    entry = s.data["groups"].get(nm.NAMES_GROUP, {})
    current = entry.get("manifest")
    if not entry.get("owner") or not current:
        sys.exit(f"{nm.NAMES_GROUP} is not in the owner vault")
    if current.get(nm.MOVED_TO):
        sys.exit(f"{nm.NAMES_GROUP} says already that it moved to {current[nm.MOVED_TO]}")
    chain = await s.council_chain(args.council)
    if chain.current is None and not args.force:
        sys.exit(f"{args.council} does not count yet: not every founding member has posted "
                 "its copy of the genesis (unseenet council show ...). --force to go on anyway.")
    if chain.current is not None:
        print(f"{args.council}: {len(chain.current.keys)} members, manifest {chain.current.seq}")
    data = dict(current)
    data.update({"serial": int(current["serial"]) + 1, nm.MOVED_TO: args.council,
                 nm.MOVED_ON: nm.rfc3339(datetime.now(timezone.utc))})
    data.pop("claims", None)                 # no more claims to the old registrar
    print(f"{nm.NAMES_GROUP}: manifest serial {data['serial']}, moved_to {args.council}")
    if args.dry_run:
        print("--dry-run: nothing posted.")
        return
    raw = manifest_article(owner, nm.NAMES_GROUP, data, pow_bits=_owner.POW_BITS)
    if await post_everywhere([raw], session=s) == 0:
        sys.exit("No node took the manifest. Run this again later.")
    entry["manifest"] = data
    s.save()
    await s.close()
    print("Done. Stop the old registrar replicas: systemctl disable --now unseenet-registrar")


if __name__ == "__main__":
    asyncio.run(main())
