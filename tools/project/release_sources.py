#!/usr/bin/env python3
"""Set where releases are fetched from, in the network (#902).

    python tools/project/release_sources.py check sources.json   # what it would post
    python tools/project/release_sources.py post sources.json    # sign and post it

``sources.json`` holds the addresses, in the order they are tried::

    {"files": ["http://abc...xyz.onion/releases/{repo}/{tag}/{name}",
               "https://github.com/unseenet/{repo}/releases/download/{tag}/{name}"],
     "index": ["https://pypi.org/simple/"]}

``files``: release files (zips, images, wheels, checksums), with {repo}, {tag} and {name};
``index``: package indexes for servers' pip. ``https://``, or ``http://`` to an onion
address. The time is added here: the newest list wins everywhere, so a list posted
later replaces this one. The project key signs it (asked for once) and it is posted in
unseenet.releases. Servers and clients keep the newest list they saw, so post a new
one *before* a source goes away when you can - and after, when you could not.

It grants nothing over what is installed: every file must still match the checksums the
project key signed. GitHub stays the last resort whatever the list says.
"""

from __future__ import annotations

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


def load(path: Path) -> rs.Sources:
    data = json.loads(path.read_text())
    data = {"v": 1, "files": data.get("files"), "index": data.get("index"),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return rs.from_dict(data)


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("check", "post"):
        sys.exit("\n".join(x.strip() for x in __doc__.strip().splitlines()[2:4]))
    try:
        sources = load(Path(sys.argv[2]))
    except (OSError, ValueError) as exc:
        sys.exit(f"{sys.argv[2]}: {exc}")
    print("Release files, in this order:")
    for f in sources.files:
        print(f"  {f}")
    print("  (then GitHub, always)")
    print("Package indexes:")
    for i in sources.index:
        print(f"  {i}")
    print(f"Time: {sources.updated}")
    if sys.argv[1] == "check":
        return
    s = open_owner_session()
    subject, body = rs.make_post(sources, s.identity())
    assert rs.parse_post(body) == sources, "the signed list does not check out"
    art = new_article(RELEASES_GROUP, subject, body, from_name="Unseenet project")
    art = art.finalize(s.identity(), _owner.POW_BITS)
    if asyncio.run(post_everywhere([art], session=s)) == 0:
        sys.exit("No node took the list: run this again later.")
    print("Posted in unseenet.releases: servers and clients use it from their next look.")


if __name__ == "__main__":
    main()
