#!/usr/bin/env python3
"""Set where releases are fetched from, in the network (#902, UN-RFC 0062 section 6.3).

    python tools/project/release_sources.py check sources.json   # what it would post
    python tools/project/release_sources.py post sources.json    # sign (and post) it
    python tools/project/release_sources.py sign sources.post --seed-file /media/usb1/reserve1.key
    python tools/project/release_sources.py post --moved-to unseenet.lists@<fp> sources.json

``sources.json`` holds the addresses, in the order they are tried::

    {"files": ["http://abc...xyz.onion/releases/{repo}/{tag}/{name}",
               "https://github.com/unseenet/{repo}/releases/download/{tag}/{name}"],
     "index": ["https://pypi.org/simple/"]}

``files``: release files (zips, images, wheels, checksums), with {repo}, {tag} and {name};
``index``: package indexes for servers' pip. ``https://``, or ``http://`` to an onion
address. The time is added here: the newest list wins everywhere, so a list posted
later replaces this one. Servers and clients keep the newest list they saw, so post a
new one *before* a source goes away when you can - and after, when you could not.

The list is signed like a release: by as many of the project's keys as its key list's
threshold (two of three once the key list is pinned, ``release_keys.py``). ``post``
signs with the vault's key; if that is not enough, it writes ``sources.post``, and
``sign`` adds the next key's signature (a reserve key with ``--seed-file``) and posts
it once there are enough.

``--moved-to`` makes the last list: from then on the list council's sources list
(UN-RFC 0020 section 6.8) is used, and the project's own lists are not.

It grants nothing over what is installed: every file must still match the checksums the
project's keys signed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import _owner  # noqa: F401  (puts src/ on the path)
from _owner import open_owner_session, post_everywhere

from unseenet import release_sources as rs
from unseenet.core.article import new_article
from unseenet.known_nodes import RELEASES_GROUP


def load(path: Path, moved_to: str | None = None) -> rs.Sources:
    data = json.loads(path.read_text())
    data = {"v": 1, "files": data.get("files"), "index": data.get("index"),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if moved_to:
        data["moved_to"] = moved_to
    return rs.from_dict(data)


def show(sources: rs.Sources) -> None:
    print("Release files, in this order:")
    for f in sources.files:
        print(f"  {f}")
    print("Package indexes:")
    for i in sources.index:
        print(f"  {i}")
    if sources.moved_to:
        print(f"Moved to: {sources.moved_to} - the project's last list of sources")
    print(f"Time: {sources.updated}")


def signer(seed_file: str | None, s):
    if not seed_file:
        return s.identity()
    from unseenet.core.crypto import Identity
    return Identity.from_seed(bytes.fromhex(Path(seed_file).read_text().strip()))


def finish(body: str, s, out: Path) -> None:
    """Post the list if it has enough signatures; else keep it for the next signer."""
    if rs.parse_post(body) is None:
        out.write_text(body)
        print(f"Signed, but it needs another of the project's keys. Written to {out}; next:")
        print(f"  python tools/project/release_sources.py sign {out} --seed-file <a reserve key>")
        return
    art = new_article(RELEASES_GROUP, rs.HEAD, body, from_name="Unseenet project")
    art = art.finalize(s.identity(), _owner.POW_BITS)
    if asyncio.run(post_everywhere([art], session=s)) == 0:
        out.write_text(body)
        sys.exit(f"No node took the list: it is in {out}; post it later with 'sign {out}'.")
    print("Posted in unseenet.releases: servers and clients use it from their next look.")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "post"):
        c = sub.add_parser(name)
        c.add_argument("file", type=Path)
        c.add_argument("--moved-to", metavar="GROUP",
                       help="the last list: the list council keeps the sources from now on")
        c.add_argument("--seed-file", help="sign with a reserve key instead of the vault's")
    c = sub.add_parser("sign", help="add the next key's signature to a written post")
    c.add_argument("file", type=Path)
    c.add_argument("--seed-file", help="sign with a reserve key instead of the vault's")
    args = p.parse_args(argv)
    if args.cmd == "sign":
        body = args.file.read_text()
        s = open_owner_session()
        try:
            body = rs.add_signature(body, signer(args.seed_file, s))
        except rs.SourcesError as exc:
            sys.exit(f"{args.file}: {exc}")
        finish(body, s, args.file)
        return
    try:
        sources = load(args.file, args.moved_to)
    except (OSError, ValueError) as exc:
        sys.exit(f"{args.file}: {exc}")
    show(sources)
    if args.cmd == "check":
        return
    s = open_owner_session()
    _, body = rs.make_post(sources, signer(args.seed_file, s))
    finish(body, s, args.file.with_suffix(".post"))


if __name__ == "__main__":
    main()
