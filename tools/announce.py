#!/usr/bin/env python3
"""Post the project's announcements to Unseenet, over Tor (used by GitHub Actions).

    python tools/announce.py nodes
        post src/unseenet/nodes.json to unseenet.nodes (UN-RFC 0010)
    python tools/announce.py hierarchies
        post src/unseenet/hierarchies.json to unseenet.hierarchies (UN-RFC 0018)
    python tools/announce.py checkgroups
        post src/unseenet/checkgroups.json, the project's list of its groups,
        to unseenet.checkgroups (UN-RFC 0018 section 5)
    python tools/announce.py release v0.2.0
        post that version's CHANGELOG section to unseenet.announce
    python tools/announce.py message --subject "..." --body-file text.txt
        post anything to unseenet.announce
    python tools/announce.py client-release dev SHA256SUMS.txt SHA256SUMS.txt.sig
        post a build's signed checksums to unseenet.releases, where clients learn
        that it exists (#264); the signature is checked first
    --dry-run  build and sign the article, print it, post nothing

The signing key comes from the environment, as a hex seed:
UNSEENET_ANNOUNCE_SEED. It is a *poster* in the project's channel groups, listed in
their manifests by the project key, which owns them and never leaves the
project's own vault. If this key leaks, the owner removes it from the
manifests and makes a new one; the groups and the project key are not at risk.

The article is posted to every known node that answers (the nodes replicate
it anyway; a duplicate is fine), so one node being down does not matter.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from unseenet.core import crypto  # noqa: E402
from unseenet.core.poster import Poster  # noqa: E402
from unseenet.hierarchies import (CHECKGROUPS_GROUP, HIERARCHIES_GROUP,  # noqa: E402
                                  parse_hierarchy_list, parse_root_list)
from unseenet.known_nodes import ANNOUNCE_GROUP, ENTRANCES_GROUP, NODES_GROUP, RELEASES_GROUP, parse_entrance_list, parse_node_list  # noqa: E402

FROM = "Unseenet project"
REPO = "https://github.com/unseenet/unseenet"
GROUP_MIN_POW = 20


def is_test_release(version: str) -> bool:
    """An alpha, beta or release candidate (PEP 440), e.g. 0.2.1a1."""
    return re.search(r"\d(a|b|rc)\d+$", version) is not None


def changelog_section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text()
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m and is_test_release(version):      # its notes are what is not released yet
        m = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m:
        sys.exit(f"CHANGELOG.md has no section for {version}")
    return m.group(1).strip() + "\n"


def release_post(tag: str) -> tuple[str, str]:
    version = tag.lstrip("v")
    if is_test_release(version):
        body = (f"Unseenet {version} is a test release: please try it and report what\n"
                f"you find. For everyday use, stay with the newest full release.\n\n"
                f"{changelog_section(version)}\n"
                f"Downloads:  {REPO}/releases/tag/{tag}\n"
                f"Check them against SHA256SUMS.txt from the same page.\n\n"
                f"With Python:  pipx install --pip-args=--pre \"unseenet[tui]\"\n")
        return f"Unseenet {version} - test release", body
    body = (f"Unseenet {version} is out.\n\n"
            f"{changelog_section(version)}\n"
            f"Downloads, with Tor inside for Windows, macOS and Linux, and the\n"
            f"all-in-one USB zip:\n  {REPO}/releases/tag/{tag}\n"
            f"Check them against SHA256SUMS.txt from the same page.\n\n"
            f"With Python:  pipx upgrade unseenet   (or: pipx install \"unseenet[tui]\")\n")
    return f"Unseenet {version} released", body


def nodes_post() -> tuple[str, str]:
    text = (ROOT / "src" / "unseenet" / "nodes.json").read_text()
    updated, nodes = parse_node_list(text)          # never post a list clients would reject
    return f"Known nodes, {updated} ({len(nodes)})", text if text.endswith("\n") else text + "\n"


def entrances_post() -> tuple[str, str]:
    text = (ROOT / "src" / "unseenet" / "entrances.json").read_text()
    updated, entrances = parse_entrance_list(text)   # never post a list clients would reject
    return f"Known web entrances, {updated} ({len(entrances)})", text if text.endswith("\n") else text + "\n"


def hierarchies_post() -> tuple[str, str]:
    text = (ROOT / "src" / "unseenet" / "hierarchies.json").read_text()
    updated, entries = parse_root_list(text, strict=True)   # never post a list with mistakes
    return f"Hierarchies, {updated} ({len(entries)})", text if text.endswith("\n") else text + "\n"


def checkgroups_post() -> tuple[str, str]:
    text = (ROOT / "src" / "unseenet" / "checkgroups.json").read_text()
    lst = parse_hierarchy_list(text, "unseenet")
    data = json.loads(text)
    if len(lst.groups) != len(data["groups"]):          # never post a list with mistakes
        raise SystemExit("checkgroups.json has an entry that does not count")
    return f"Groups of unseenet, {lst.updated} ({len(lst.groups)})", text if text.endswith("\n") else text + "\n"


async def post_everywhere(group: str, subject: str, body: str, key: crypto.Identity,
                          addresses: list[str], dry_run: bool) -> int:
    """Post to every node that answers, through the core's headless API (#166)."""
    poster = Poster(key, addresses, from_name=FROM, tor="own",
                    log=lambda msg: print("  " + msg, flush=True))
    art = poster.build(group, subject, body)
    if dry_run:
        print(art.finalize(key, 8).to_bytes().decode())
        return 0
    async with poster:
        result = await poster.post_article(art, GROUP_MIN_POW)
    return len(result.accepted)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=["nodes", "entrances", "hierarchies", "checkgroups", "release", "message",
                                    "client-release"])
    p.add_argument("tag", nargs="?", help="release: the tag, e.g. v0.2.0; client-release: the channel")
    p.add_argument("files", nargs="*", type=Path, help="client-release: SHA256SUMS.txt and its .sig")
    p.add_argument("--subject")
    p.add_argument("--body-file", type=Path)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.what == "nodes":
        group, (subject, body) = NODES_GROUP, nodes_post()
    elif args.what == "entrances":
        group, (subject, body) = ENTRANCES_GROUP, entrances_post()
    elif args.what == "hierarchies":
        group, (subject, body) = HIERARCHIES_GROUP, hierarchies_post()
    elif args.what == "checkgroups":
        group, (subject, body) = CHECKGROUPS_GROUP, checkgroups_post()
    elif args.what == "release":
        if not args.tag:
            sys.exit("release needs the tag")
        group, (subject, body) = ANNOUNCE_GROUP, release_post(args.tag)
    elif args.what == "client-release":
        from unseenet import update
        if args.tag not in ("stable", "dev") or len(args.files) != 2:
            sys.exit("client-release needs the channel, SHA256SUMS.txt and SHA256SUMS.txt.sig")
        group = RELEASES_GROUP
        subject, body = update.release_post(args.files[0].read_bytes(), args.files[1].read_text(), args.tag)
    else:
        if not (args.subject and args.body_file):
            sys.exit("message needs --subject and --body-file")
        body = args.body_file.read_text()
        group, subject, body = ANNOUNCE_GROUP, args.subject, body if body.endswith("\n") else body + "\n"

    seed = os.environ.get("UNSEENET_ANNOUNCE_SEED", "").strip()
    if args.dry_run and not seed:
        key = crypto.Identity.generate()
    elif not seed:
        sys.exit("UNSEENET_ANNOUNCE_SEED is not set")
    else:
        key = crypto.Identity.from_seed(bytes.fromhex(seed))
    print(f"Posting as {key.key_text} to {group}: {subject}", flush=True)

    _, nodes = parse_node_list((ROOT / "src" / "unseenet" / "nodes.json").read_text())
    ok = asyncio.run(post_everywhere(group, subject, body, key, [n.address for n in nodes], args.dry_run))
    if not args.dry_run and ok == 0:
        sys.exit("no node took the post")


if __name__ == "__main__":
    main()
