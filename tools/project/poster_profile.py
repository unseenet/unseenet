#!/usr/bin/env python3
"""Publish the GitHub poster's public profile and picture (UN-RFC 0022).

    python3 tools/project/poster_profile.py [--about FILE] [--picture FILE] [--dry-run]

The GitHub poster (github_poster in the owner vault, UNSEENET_ANNOUNCE_SEED on
GitHub) posts the project's announcements, node list and root list. Readers
see its profile when they click its name, so it should say what it is. This
publishes a profile with the bot mark (UN-RFC 0030), the About text from FILE
as Markdown (default: poster_profile.md beside this script), the project's
links, and optionally a picture (default: assets/icon-512.png).

The seed goes from the vault straight into a session and is never shown or
written to a file. The profile and picture are posted over Tor to the
project's nodes. --dry-run checks the profile and prints it, posting nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil

from _owner import ROOT, Path, builtin_list, open_owner_session  # noqa: E402

from unseenet.client.session import Session  # noqa: E402
from unseenet.core import crypto  # noqa: E402
from unseenet.core import profiles as prof  # noqa: E402

HERE = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".unseenet" / "ripening"   # as ripen_keys.py
REPO_CHAINS = HERE.parent / "ripening"
LINKS = [{"kind": "web", "value": "https://unseenet.org"},
         {"kind": "github", "value": "https://github.com/unseenet"}]


async def publish(seed_hex: str, obj: dict, picture: Path | None, alt: str) -> None:
    """The poster's own session (its chain in STATE_DIR), as ripen_keys.py does."""
    ident = crypto.Identity.from_seed(bytes.fromhex(seed_hex))
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = STATE_DIR / f"{ident.fingerprint}.state.json"
    known = REPO_CHAINS / state.name                    # the CI key's chain is in the repo
    if not state.exists() and known.exists():
        shutil.copyfile(known, state)
    s = Session.from_key(ident, state, name="github_poster", status=lambda *_: None)
    for node in builtin_list()[1]:
        if node.address not in s.nodes:
            s.add_node(node.address)
    try:
        await s.publish_profile(obj)
        print("profile published", flush=True)
        if picture:
            await s.publish_picture_file(picture, alt)
            print("picture published", flush=True)
    finally:
        s.save()
        await s.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--about", type=Path, default=HERE / "poster_profile.md",
                    help="Markdown file with the About text")
    ap.add_argument("--picture", type=Path, default=ROOT / "assets" / "icon-512.png",
                    help="picture file (cut square, made small, no metadata)")
    ap.add_argument("--no-picture", action="store_true", help="leave the picture as it is")
    ap.add_argument("--alt", default="The Unseenet logo: a closed eye over a chain of nodes")
    ap.add_argument("--dry-run", action="store_true", help="check and print, post nothing")
    args = ap.parse_args()
    obj = prof.check_profile(prof.make_profile(
        about=args.about.read_text(encoding="utf-8"), links=LINKS, lang=["en"],
        bot=True, markdown=True))
    picture = None if args.no_picture else args.picture
    if picture and not picture.exists():
        raise SystemExit(f"no such picture: {picture}")
    if args.dry_run:
        print(json.dumps(obj, indent=2, ensure_ascii=False))
        print(f"picture: {picture or '(unchanged)'}")
        return
    s = open_owner_session()
    entry = s.data.get("github_poster")
    if not entry or not entry.get("seed"):
        raise SystemExit("The owner vault has no github_poster key.")
    asyncio.run(publish(entry["seed"], obj, picture, args.alt))


if __name__ == "__main__":
    main()
