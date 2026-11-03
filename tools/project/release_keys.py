#!/usr/bin/env python3
"""The project's key list: who signs its releases, and how many must (UN-RFC 0062 3-5).

    python tools/project/release_keys.py new-key /media/usb1/reserve1.key
    python tools/project/release_keys.py make --keys <project> <reserve1> <reserve2> \
        --threshold 2 --channel dev=1 > keys-1.json
    python tools/project/release_keys.py post keys-2.json [--seed-file /media/usb1/reserve1.key]
    python tools/project/release_keys.py post keys-2.signed --seed-file /media/usb2/reserve2.key
    python tools/project/release_keys.py chain              # the chain, for PROJECT_CHAIN

``new-key`` makes a reserve key: its seed goes to the file (readable only by you - keep
it on removable media, offline, one key per medium), its key is printed. Nothing else
keeps it.

``make`` writes a key list's body. The first (``--seq 1``, the default) is pinned in the
client: put its body in ``PROJECT_FIRST`` in ``src/unseenet/release_keys.py`` by pull
request, and post it. From then on stable releases need ``threshold`` signatures
(``sign_release.py`` adds them one key at a time). A later list (``--seq 2 --prev
keys-1.json``) counts once ``threshold`` keys of the list before it have each posted
it with ``post`` - the old keys vote the new ones in; the channel's owner cannot.

``post`` adds the signer's vote to the list (UN-RFC 0062 section 3.1: a signature on
the list, carried in the body), writes the list with its votes so far to
``<name>.signed``, and posts that in unseenet.releases (``Subject: release-keys <seq>``)
- signed by the project key from the owner vault, or by a reserve key with
``--seed-file``. The next signer runs ``post`` on the ``.signed`` file; each post
carries every vote so far. A key that posts must be a poster in the channel's manifest
(``create_groups.py``): the nodes take posts in a channel from its owner and posters
only - but the votes count whoever posts them.

``chain`` reads the channel and prints every list counted after the first, with its
votes (section 3.2). Put it in ``PROJECT_CHAIN`` in ``src/unseenet/release_keys.py`` by
pull request once a new list counts: clients then count it without the channel, and CI
posts it every month and with each release (``tools/announce.py keys``), so it never
expires on the nodes.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import _owner  # noqa: F401  (puts src/ on the path)
from _owner import POW_BITS, open_owner_session, post_everywhere

from unseenet import release_keys as rk
from unseenet.core.article import new_article
from unseenet.core.crypto import Identity
from unseenet.known_nodes import RELEASES_GROUP


def new_key(path: Path) -> None:
    if path.exists():
        sys.exit(f"{path} exists: a reserve key is never overwritten")
    ident = Identity.generate()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(ident.seed.hex() + "\n")
    print(ident.key_text)


def make(args) -> None:
    channels = {}
    for c in args.channel or []:
        name, _, n = c.partition("=")
        channels[name] = int(n)
    prev = rk.parse(Path(args.prev).read_text()) if args.prev else None
    if (args.seq == 1) != (prev is None):
        sys.exit("--prev is the list before it: needed from --seq 2 on, and only then")
    try:
        sys.stdout.write(rk.make_body(args.seq, args.keys, args.threshold, channels, prev))
    except rk.KeyListProblem as exc:
        sys.exit(f"not a valid key list: {exc}")


def post(args) -> None:
    path = Path(args.body)
    text = path.read_text()
    kl = rk.parse(rk.split_signed(text)[0])
    s = open_owner_session()
    signer = s.identity()
    others = ()
    if args.seed_file:
        signer = Identity.from_seed(bytes.fromhex(Path(args.seed_file).read_text().strip()))
        others = (signer,)
    if signer.key_text not in kl.keys and kl.seq > 1:
        print(f"Note: {signer.key_text} is not in this list - its vote counts only if it is "
              "in the list before it.")
    text = rk.add_vote(text, signer)
    out = path if path.suffix == ".signed" else path.with_suffix(".signed")
    out.write_text(text)
    votes = len(rk.split_signed(text)[1])
    art = new_article(RELEASES_GROUP, f"{rk.SUBJECT} {kl.seq}", text,
                      from_name="Unseenet project").finalize(signer, POW_BITS)
    if asyncio.run(post_everywhere([art], session=s, others=others)) == 0:
        sys.exit(f"No node took it: run this again later (the votes are in {out}).")
    print(f"Posted key list {kl.seq} ({len(kl.keys)} keys, threshold {kl.threshold}) "
          f"with {votes} vote(s), the last by {signer.key_text}. The votes are in {out}; "
          f"the next signer runs: post {out} --seed-file <their key>")


def chain(args) -> None:
    s = open_owner_session()
    messages = asyncio.run(s.fetch_group(RELEASES_GROUP))
    votes = [v for m in messages if m.readable and getattr(m, "author_key", None)
             for v in rk.votes_from(m.author_key, getattr(m, "subject", "") or "", m.body)]
    text = rk.chain_text(votes + rk.votes_from(None, rk.CHAIN_SUBJECT, rk.PROJECT_CHAIN))
    if not text:
        sys.exit("No list counts after the first: there is no chain yet.")
    sys.stdout.write(text)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("new-key", help="make a reserve key; its seed goes to the file")
    k.add_argument("path", type=Path)
    m = sub.add_parser("make", help="write a key list's body")
    m.add_argument("--seq", type=int, default=1)
    m.add_argument("--keys", nargs="+", required=True)
    m.add_argument("--threshold", type=int, required=True)
    m.add_argument("--channel", action="append", help="a channel's own threshold: dev=1")
    m.add_argument("--prev", help="the list before it (a file with its body)")
    o = sub.add_parser("post", help="vote for a key list and post it in unseenet.releases")
    o.add_argument("body", help="the list (keys-N.json), or keys-N.signed with votes so far")
    o.add_argument("--seed-file", help="sign with a reserve key instead of the project key")
    sub.add_parser("chain", help="print the lists counted after the first, with their votes")
    args = p.parse_args(argv)
    {"new-key": lambda: new_key(args.path), "make": lambda: make(args),
     "post": lambda: post(args), "chain": lambda: chain(args)}[args.cmd]()


if __name__ == "__main__":
    main()
