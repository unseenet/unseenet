#!/usr/bin/env python3
"""The project's contact inbox as a team inbox (UN-RFC 0047, #341).

    python3 tools/project/team_contact.py [--dry-run] [--reader KEY ...]

Today every project node has a local `operator@ph5fc5hop5232qsz`, owned by the
project key: four mailboxes, read by opening the owner vault. This makes one
replicated team inbox instead, `contact@ph5fc5hop5232qsz`, owned by the project
key and read by the maintainer with a team key in his everyday client:

- creates the inbox if it does not exist (replicated, not local; pictures and PDFs),
  named "Unseenet (operator)" for replies;
- adds each --reader: a new team key goes to that person's inbox, to accept in
  their own client (the owner vault keeps none). Without --reader, and only while
  nobody reads it, the maintainer's own key (@andlo) is added, so running it
  again adds nobody twice;
- prints what to put in each node's node.toml: `contact` in `[operator]`.

Run it again to add a reader; removing one is `unseenet --vault owner.vault team
remove contact@... <team key>`. The owner key is needed only for these changes,
and to renew nothing: the inbox is not key-bound. Take a backup afterwards
(backup/LÆS-MIG.md): the vault now knows the inbox.

--dry-run says what it would do and changes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from _owner import FP, builtin_list, open_owner_session  # noqa: E402

from unseenet.client.session import SessionError  # noqa: E402

NAME = "contact"
TEAM_NAME = "Unseenet (operator)"
MAINTAINER = "ed25519:5snjknxh2rz2a7pteemybpv6ylgc6pcgohweejfjnlbasbc74mhq"   # @andlo, everyday


async def run(dry: bool, readers: list[str] | None) -> None:
    s = open_owner_session()
    for node in builtin_list()[1]:
        if node.address not in s.nodes:
            s.add_node(node.address)
    gid = f"{NAME}@{FP}"
    try:
        print(f"Reading {gid} over Tor ...", flush=True)
        m, node = None, None
        for address in s.nodes:                     # the first project node that answers
            try:
                m = await s.fetch_manifest(gid, node=address)
                node = address
                break
            except (OSError, ConnectionError, SessionError) as exc:
                print(f"  {address[:16]}...: not reached ({exc})", flush=True)
        if node is None:
            sys.exit("No project node answered over Tor; nothing done. Try again in a while.")
        s.pin_group(gid, node)                      # read and posted there from now on
        if m is None:
            print(f"{gid}: will create (replicated team inbox, '{TEAM_NAME}')")
            if not dry:
                made = await s.create_group(NAME, "inbox", node=node, title="Contact the Unseenet project",
                                            description="Questions, reports and node trouble. "
                                            "Read by the project's people; answered as the team.")
                assert made == gid
                await s.update_group(gid, team_name=TEAM_NAME)
        else:
            s.group_entry(gid).update({"manifest": dict(m.raw), "owner": True, "type": "inbox"})
            print(f"{gid}: exists, {len(m.raw.get('readers', []))} reader(s)")
        # who reads it cannot be seen (team keys): the maintainer only while nobody does
        if readers is None:
            readers = [] if (m is not None and m.raw.get("readers")) else [MAINTAINER]
            if not readers:
                print("It has readers already; add someone with --reader KEY.")
        for key in readers:
            print(f"Adding a reader: a new team key to {key[:24]}...'s inbox")
            if dry:
                continue
            try:
                team = await s.add_team_reader(gid, key, TEAM_NAME)
            except SessionError as exc:
                print(f"  not added: {exc}")
                continue
            print(f"  team key {team}: accept it in your own client "
                  "(Private posts -> 'Read this inbox with the team', or `unseenet team invitations`)")
        print(f"\nIn each project node's node.toml, [operator]:\n    contact = \"{gid}\"\n"
              "then restart the node. The old local operator@ inboxes can stay until "
              "nobody writes there any more.")
        if dry:
            print("\n--dry-run: nothing created, sent or stored.")
    finally:
        if not dry:
            s.save()
        await s.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="say what would be done, change nothing")
    ap.add_argument("--reader", action="append", metavar="KEY",
                    help="a person to read it (their own key); default: the maintainer")
    args = ap.parse_args()
    asyncio.run(run(args.dry_run, args.reader))


if __name__ == "__main__":
    main()
