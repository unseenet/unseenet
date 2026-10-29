#!/usr/bin/env python3
"""Sign a stable release with the project key, so sticks will update to it.

    python tools/project/sign_release.py v0.6.1

Since 0.6 a release is built in two repositories, each with its own SHA256SUMS.txt
(#546): unseenet-portable (the zips for folders and USB sticks) and
unseenet-bootable (the image and its update zip; it can come days later, when
Alpine has the newest Tor). This signs each that has the release and no
signature yet - run it again when the other one is out. For each it downloads
SHA256SUMS.txt, checks that it names this version, asks for the owner vault's
passphrase (once), signs, uploads SHA256SUMS.txt.sig and posts both in
unseenet.releases. The project key never leaves this computer.

Sticks on the stable channel accept only this signature (unseenet.update).
Run it again after files were added to the release: the sums change, and
the old signature no longer fits.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

import _owner  # noqa: F401  (puts src/ on the path)
from _owner import open_owner_session, post_everywhere

from unseenet import update
from unseenet.core.article import new_article
from unseenet.known_nodes import RELEASES_GROUP

REPOS = {"unseenet/unseenet-portable": "linux-x86_64",       # the zip that names the version
         "unseenet/unseenet-bootable": "x86_64-update"}


def gh(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["gh", *args, "-R", repo], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"gh {args[0]} {args[1]} -R {repo} failed: {r.stderr.strip()}")
    return r


def assets(repo: str, tag: str) -> list[str] | None:
    """The release's file names, or None when there is no such release (yet)."""
    r = gh(repo, "release", "view", tag, "--json", "assets", "--jq", ".assets[].name",
           check=False)
    return r.stdout.split() if r.returncode == 0 else None


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("v"):
        sys.exit(__doc__.strip().splitlines()[2].strip())
    tag = sys.argv[1]
    todo = []
    for repo, what in REPOS.items():
        names = assets(repo, tag)
        if names is None:
            print(f"{repo}: no {tag} release yet - run this again when it is out.")
        elif update.SUMS not in names:
            print(f"{repo}: {tag} has no {update.SUMS} yet - its build is still running?")
        elif update.SIG in names:
            print(f"{repo}: {tag} is signed already.")
        else:
            todo.append((repo, what))
    if not todo:
        return
    s = identity = None
    with tempfile.TemporaryDirectory(prefix="unseenet-sign-") as tmp:
        for repo, what in todo:
            d = Path(tmp) / repo.split("/")[1]
            d.mkdir()
            gh(repo, "release", "download", tag, "-p", update.SUMS, "-D", str(d))
            sums = (d / update.SUMS).read_bytes()
            name, version = update.asset_in(update.parse_sums(sums), what)
            if version != tag[1:]:
                sys.exit(f"{repo}: {update.SUMS} lists {name}, not version {tag[1:]}")
            print(f"{repo} {tag}: {len(update.parse_sums(sums))} files, {name}")
            if s is None:
                s = open_owner_session()
                identity = s.identity()
            sig = update.signature_text(sums, identity)
            update.check_release(sums, sig, "stable", what)     # as sticks will check it
            (d / update.SIG).write_text(sig)
            gh(repo, "release", "upload", tag, str(d / update.SIG), "--clobber")
            print(f"Signed: {update.SIG} is on {repo} {tag}.")
            # and tell the clients through the network (#264): the checksums and the
            # signature, posted by the project key itself in unseenet.releases
            subject, body = update.release_post(sums, sig, "stable")
            art = new_article(RELEASES_GROUP, subject, body, from_name="Unseenet project")
            art = art.finalize(identity, _owner.POW_BITS)
            if asyncio.run(post_everywhere([art], session=s)) == 0:
                print("No node took the post in unseenet.releases: run this again later.")
            else:
                print("Posted in unseenet.releases: clients will offer the update.")

if __name__ == "__main__":
    main()
