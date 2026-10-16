#!/usr/bin/env python3
"""Post the project's announcements to Unseenet, over Tor (used by GitHub Actions).

    python tools/announce.py nodes
        post src/unseenet/nodes.json to unseenet.nodes (UN-RFC 0010)
    python tools/announce.py release v0.2.0
        post that version's CHANGELOG section to unseenet.announce
    python tools/announce.py message --subject "..." --body-file text.txt
        post anything to unseenet.announce
    --dry-run  build and sign the article, print it, post nothing

The signing key comes from the environment, as a hex seed:
UNSEENET_ANNOUNCE_SEED. It is a *poster* in the two channel groups, listed in
their manifests by the project key, which owns them and never leaves the
project's own vault. If this key leaks, the owner removes it from the
manifests and makes a new one; the groups and the project key are not at risk.

The article is posted to every known node that answers (the nodes replicate
it anyway; a duplicate is fine), so one node being down does not matter.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from unseenet.core import crypto  # noqa: E402
from unseenet.core.article import new_article  # noqa: E402
from unseenet.core.tor import TorProcess, open_connection  # noqa: E402
from unseenet.known_nodes import ANNOUNCE_GROUP, NODES_GROUP, parse_node_list  # noqa: E402
from unseenet.nntp import Client  # noqa: E402

FROM = "Unseenet project"
REPO = "https://github.com/unseenet/unseenet"
GROUP_MIN_POW = 20


def changelog_section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text()
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m:
        sys.exit(f"CHANGELOG.md has no section for {version}")
    return m.group(1).strip() + "\n"


def release_post(tag: str) -> tuple[str, str]:
    version = tag.lstrip("v")
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


async def post_everywhere(group: str, subject: str, body: str, key: crypto.Identity,
                          addresses: list[str], dry_run: bool) -> int:
    def build(bits: int) -> bytes:
        art = new_article(group, subject, body, from_name=FROM)
        return art.finalize(key, bits).to_bytes()

    if dry_run:
        print(build(8).decode())
        return 0
    ok = 0
    with tempfile.TemporaryDirectory(prefix="unseenet-announce-") as tmp:
        tor = TorProcess(Path(tmp), TorProcess.find_binary())
        print("Starting Tor ...", flush=True)
        await tor.start(timeout=180)
        raw = None
        try:
            for address in addresses:
                try:
                    reader, writer = await asyncio.wait_for(open_connection(address, tor.socks_port), 120)
                    client = Client(reader, writer)
                    code, text = await client._response()
                    await client.fetch_capabilities()
                    node_min = int(client.capability("UNSEENET-MINPOW") or 20)
                    if raw is None:                       # one article, the same everywhere
                        raw = build(max(node_min, GROUP_MIN_POW))
                    code, text = await client.post(raw)
                    await client.quit()
                except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
                    print(f"  {address}: not reached ({exc})", flush=True)
                    continue
                if code == 240 or "duplicate" in text:
                    ok += 1
                    print(f"  {address}: posted ({code} {text})", flush=True)
                else:
                    print(f"  {address}: REFUSED {code} {text}", flush=True)
        finally:
            await tor.stop()
    return ok


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=["nodes", "release", "message"])
    p.add_argument("tag", nargs="?", help="release: the tag, e.g. v0.2.0")
    p.add_argument("--subject")
    p.add_argument("--body-file", type=Path)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.what == "nodes":
        group, (subject, body) = NODES_GROUP, nodes_post()
    elif args.what == "release":
        if not args.tag:
            sys.exit("release needs the tag")
        group, (subject, body) = ANNOUNCE_GROUP, release_post(args.tag)
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
