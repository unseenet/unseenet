#!/usr/bin/env python3
"""Wire up the project's registrar (UN-RFC 0019 sections 6.1 and 6.8).

    python tools/project/setup_registrar.py [--add KEY ...] [--remove KEY ...]
                                            [--show-inbox-seed] [--dry-run]

The registrar runs as replicas, each on its own machine, each with its own
registrar key (made there by `unseenet-registrar init`). All replicas share
one **inbox key**, which owns the claim inbox and opens claims but cannot sign
certificates. This script, run by the owner of unseenet.names:

1. makes the inbox key, if the owner vault has none, and keeps it there;
2. creates the claim inbox, owned by the inbox key, with min_pow 24, so that
   the nodes enforce the postage UN-RFC 0019 section 6.2 asks for;
3. publishes a new manifest for unseenet.names whose `claims` names the
   claim inbox and whose `posters` are the replicas' registrar keys:
   the ones already listed, plus --add, minus --remove.

--show-inbox-seed prints the inbox key's seed, to type into
`unseenet-registrar init` on a new replica's machine. Do it only there and
not where anything records your terminal.

Removing a registrar key makes the certificates it signed untrusted; the
same decisions signed by the other replicas stay valid (section 6.8).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import _owner
from _owner import open_owner_session, post_everywhere

from unseenet.core import crypto
from unseenet.core.groups import make_manifest, manifest_article, personal_inbox_id
from unseenet.names import CLAIM_POW, NAMES_GROUP


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--add", action="append", default=[], metavar="KEY", help="a replica's registrar key")
    p.add_argument("--remove", action="append", default=[], metavar="KEY", help="a key to take out")
    p.add_argument("--show-inbox-seed", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    for key in args.add + args.remove:
        try:
            crypto.key_from_text(key)
        except crypto.CryptoError:
            sys.exit(f"not a key: {key}")

    s = open_owner_session()
    owner = s.identity()
    entry = s.data["groups"].get(NAMES_GROUP, {})
    current = entry.get("manifest")
    if not entry.get("owner") or not current:
        sys.exit(f"{NAMES_GROUP} is not in the vault; run create_groups.py first.")

    new_inbox = "registrar_inbox" not in s.data
    if new_inbox:
        ident = crypto.Identity.generate()
        s.data["registrar_inbox"] = {"seed": ident.seed.hex(), "key": ident.key_text,
                                     "note": "Shared by the registrar's replicas; opens claims (UN-RFC 0019 6.8)"}
    inbox = crypto.Identity.from_seed(bytes.fromhex(s.data["registrar_inbox"]["seed"]))
    claims = personal_inbox_id(inbox.public_key)
    if args.show_inbox_seed:
        print(f"inbox key seed: {inbox.seed.hex()}")

    posters = [k for k in current.get("posters", []) if k not in args.remove]
    posters += [k for k in args.add if k not in posters]
    if not posters:
        sys.exit("That would leave no registrar key at all.")
    raws = []
    if not s.data["registrar_inbox"].get("posted"):
        raws.append(make_manifest(inbox, "inbox", "inbox", min_pow=CLAIM_POW, retention_days=30,
                                  pow_bits=_owner.POW_BITS))
        print(f"claim inbox {claims}: will create, min_pow {CLAIM_POW}")
    data = dict(current)
    if data.get("posters") != posters or data.get("claims") != claims:
        data.update({"serial": int(current["serial"]) + 1, "posters": posters, "claims": claims})
        raws.append(manifest_article(owner, NAMES_GROUP, data, pow_bits=_owner.POW_BITS))
        print(f"{NAMES_GROUP}: manifest serial {data['serial']}, claims {claims}")
        for k in posters:
            print(f"  registrar key {k}")
    if not raws:
        print("Nothing to change.")
        if new_inbox and not args.dry_run:
            s.save()
        return
    if args.dry_run:
        print("--dry-run: nothing posted or stored.")
        return
    s.save()                                    # the inbox key, before anything can fail
    if await post_everywhere(raws, session=s, others=[inbox]) == 0:
        sys.exit("No node took the manifests. Run this again later; the inbox key is kept.")
    s.data["registrar_inbox"]["posted"] = True
    entry["manifest"] = data
    s.save()
    await s.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
