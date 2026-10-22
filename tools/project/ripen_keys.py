#!/usr/bin/env python3
"""Ripen the project's keys in the owner vault and publish their chains (UN-RFC 0025).

    python3 tools/project/ripen_keys.py [--to N] [--only NAME ...] [--vault PATH]

Nodes from 0.4.0 on take articles only from keys that have done the work of
ripening, manifests included: the project key must be ripe before it can
change any of the project's groups. This ripens every identity in the owner
vault and the keys it keeps beside them (github_poster, registrar_inbox, whose
chains go to ~/.unseenet/ripening/), or only those named, to level --to (0 by
default: enough to post, about 7-11 minutes per key on one core) and posts each key's ripe@ manifest to the
project's nodes over Tor. A chain already published, from another machine or
an earlier run, is taken over instead of computed again; a stopped run goes on
where it was.

The CI key (github_poster) can also be ripened without the vault, from its
public key: see tools/ripening/README.md.
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import time

from _owner import VAULT, Path, builtin_list, open_owner_session  # noqa: E402

from unseenet.client.session import Session  # noqa: E402
from unseenet.core import crypto  # noqa: E402
from unseenet.core import ripening as rp  # noqa: E402


def _lv(level) -> str:
    return "-" if level is None else str(level)


async def ripen(s, name: str, to: int) -> None:
    key = s.identity(name).key_text
    if await s.adopt_published_ripening(name):
        print(f"{name}: took over the published chain", flush=True)
    print(f"{name} ({key}): level {_lv(s.ripening(name).level)}", flush=True)
    start = time.monotonic()
    while s.ripening(name).level is None or s.ripening(name).level < to:
        if not await s.ripen_segment(name):
            break
        chain = s.ripening(name)
        print(f"  t = {chain.t:,} after {time.monotonic() - start:.0f} s: level {_lv(chain.level)}",
              flush=True)
        if chain.level is not None and chain.level != s.published_level(name):
            await s.publish_ripening(name)              # each new level, at once
    if s.ripening(name).level != s.published_level(name):
        await s.publish_ripening(name)
    print(f"{name}: level {_lv(s.ripening(name).level)}, published "
          f"{_lv(s.published_level(name))}", flush=True)


# Keys the vault keeps beside its identities (create_groups.py, setup_registrar.py).
EXTRA_KEYS = ("github_poster", "registrar_inbox")
STATE_DIR = Path.home() / ".unseenet" / "ripening"
REPO_CHAINS = Path(__file__).resolve().parents[1] / "ripening"


async def ripen_extra(key: str, seed_hex: str, to: int) -> None:
    """A key that is not an identity: its own session, its chain in STATE_DIR."""
    ident = crypto.Identity.from_seed(bytes.fromhex(seed_hex))
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = STATE_DIR / f"{ident.fingerprint}.state.json"
    known = REPO_CHAINS / state.name                    # the CI key's chain is in the repo
    if not state.exists() and known.exists():
        shutil.copyfile(known, state)
    s = Session.from_key(ident, state, name=key, status=lambda *_: None)
    for node in builtin_list()[1]:
        if node.address not in s.nodes:
            s.add_node(node.address)
    try:
        await ripen(s, key, to)
    finally:
        s.save()
        await s.close()


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--to", type=int, default=0, choices=range(5), help="the level to reach")
    p.add_argument("--only", nargs="*", default=None, help="only these identities")
    p.add_argument("--vault", type=Path, default=VAULT)
    args = p.parse_args()
    if not rp.available():
        raise SystemExit("key ripening needs chiavdf (pip install chiavdf)")
    s = open_owner_session(args.vault)
    for node in builtin_list()[1]:
        if node.address not in s.nodes:
            s.add_node(node.address)
    names = list(s.data["identities"])
    extra = [k for k in EXTRA_KEYS if isinstance(s.data.get(k), dict) and "seed" in s.data[k]]
    if args.only:
        unknown = set(args.only) - set(names) - set(extra)
        if unknown:
            raise SystemExit(f"not in the vault: {', '.join(sorted(unknown))} "
                             f"(it has {', '.join(names + extra)})")
        extra = [k for k in extra if k in args.only]
        names = [n for n in names if n in args.only]
    try:
        for name in names:
            await ripen(s, name, args.to)
    finally:
        s.save()
        await s.close()
    for key in extra:
        await ripen_extra(key, s.data[key]["seed"], args.to)


if __name__ == "__main__":
    asyncio.run(main())
