#!/usr/bin/env python3
"""The project's names: @unseenet, and the names it gives under it (UN-RFC 0019).

    python3 tools/project/give_names.py [--dry-run]

The project key holds @unseenet. This opens the owner vault and:

- renews @unseenet when it runs out within 60 days (a `renew` claim to the
  registrar; the answer comes to the project's inbox);
- gives every name in NAMES below to its key for five years (section 5.4),
  unless it already has one from us that lasts more than a year;
- says which names could not be delivered yet: a name is sent to the key's
  personal inbox, and a service makes its inbox the first time it posts with
  core 0.6 or later (#592). Run this again after that.

Run it once a year and whenever NAMES changes (backup/LÆS-MIG.md). Names given
are kept in the owner vault, so take a backup afterwards. --dry-run says what
it would do and changes nothing.

Only the project's own services are named here. Gateways are not: they post
other people's messages, which must show their senders, not the gateway.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from _owner import builtin_list, open_owner_session  # noqa: E402

from unseenet.client import naming  # noqa: E402

PARENT = "unseenet"
LIFETIME = timedelta(days=5 * 365)          # the longest section 5.4 allows
GIVE_AGAIN = timedelta(days=365)            # renew a name with less than this left
RENEW_PARENT = timedelta(days=60)

# name under @unseenet -> key. Bots that repeat others' content end in -bot, so
# nasa-bot@unseenet is not mistaken for NASA itself.
NAMES = {
    "help": "ed25519:6gf6zqd6hzligjk57kdbna3z7uwlnipfgg47v765kitkn2avdxfa",            # unseenet-helpbot
    "wikipedia-bot": "ed25519:2xx732vxtge5ficz7ihbi75uctegsmyzc5bmllwett62etjtfuza",   # alt.news.wikipedia
    "onthisday-bot": "ed25519:ame5agdrby6zyjqusfnpyicxg4nygfai3lqwewz2ctkkjuid3hxa",   # alt.history.onthisday
    "globalvoices-bot": "ed25519:ojyu2pv2v3aye2tw4xbel3ha5loujwxqjao5wnoe55dw7zc4fw7q",
    "theconversation-bot": "ed25519:7ky3decxcamoqttl2fqysiie24ptdxt4mld5yrxdb2ftbheukydq",
    "eff-bot": "ed25519:uangztkgxp6ql2nxj6fy34d2bjspykt5taxfi7i4urrcm2o4kvca",         # alt.privacy.eff
    "nasa-bot": "ed25519:ftseuejwlor33343q7d6on3zq4yow2dn5ro7zbltfbufilacu3eq",        # alt.space.nasa
}


async def run(dry: bool) -> None:
    s = open_owner_session()
    for node in builtin_list()[1]:
        if node.address not in s.nodes:
            s.add_node(node.address)
    try:
        print("Reading names over Tor ...", flush=True)
        await naming.refresh(s)
        now = datetime.now(timezone.utc)
        held = {c.name: c for c in naming.my_names(s)}
        if PARENT not in held:
            print(f"The project key does not hold @{PARENT} (or the registrar's group "
                  "could not be read). Nothing given.")
            return
        left = held[PARENT].expires - now
        print(f"@{PARENT}: held, runs out {held[PARENT].expires:%Y-%m-%d}")
        if left < RENEW_PARENT:
            print(f"  renewing @{PARENT}")
            if not dry:
                await naming.claim(s, PARENT, "renew")

        given = {c.name: c for c in naming.names_given(s)}
        waiting = []
        for local, key in NAMES.items():
            name = f"{local}@{PARENT}"
            cur = given.get(name)
            if cur and cur.key == key and cur.expires - now > GIVE_AGAIN:
                print(f"{name}: given, lasts to {cur.expires:%Y-%m-%d}")
                continue
            if not await naming.has_inbox(s, key):
                waiting.append(name)
                print(f"{name}: not given yet - {key[:20]}... has no inbox")
                continue
            print(f"{name}: giving to {key[:20]}... for five years")
            if not dry:
                await naming.give_subname(s, name, key, LIFETIME)
        if waiting:
            print(f"\n{len(waiting)} name(s) wait for their service to post with core 0.6 "
                  "or later. Run this again then.")
        if dry:
            print("\n--dry-run: nothing claimed, given or stored.")
    finally:
        if not dry:
            s.save()
        await s.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="say what would be done, change nothing")
    asyncio.run(run(ap.parse_args().dry_run))


if __name__ == "__main__":
    main()
