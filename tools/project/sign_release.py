#!/usr/bin/env python3
"""Sign a stable release with the project key, so sticks will update to it.

    python tools/project/sign_release.py v0.3.0

Run it when the release's workflows are done (portable and image have attached
their files and SHA256SUMS.txt). It downloads SHA256SUMS.txt from the release,
checks that it lists the update zip, asks for the owner vault's passphrase,
signs, and uploads SHA256SUMS.txt.sig. The project key never leaves this
computer; only the signature is uploaded.

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

REPO = "unseenet/unseenet"


def gh(*args: str) -> None:
    r = subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gh {args[0]} {args[1]} failed: {r.stderr.strip()}")


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("v"):
        sys.exit(__doc__.strip().splitlines()[2].strip())
    tag = sys.argv[1]
    with tempfile.TemporaryDirectory(prefix="unseenet-sign-") as tmp:
        d = Path(tmp)
        gh("release", "download", tag, "-p", update.SUMS, "-D", tmp)
        sums = (d / update.SUMS).read_bytes()
        name, version = update.update_zip_in(update.parse_sums(sums))
        if version != tag[1:]:
            sys.exit(f"{update.SUMS} lists {name}, not version {tag[1:]}")
        print(f"{tag}: {len(update.parse_sums(sums))} files, update zip {name}")
        identity = open_owner_session().identity()
        sig = update.signature_text(sums, identity)
        update.check_signature(sums, sig, "stable")      # the key sticks trust
        (d / update.SIG).write_text(sig)
        gh("release", "upload", tag, str(d / update.SIG), "--clobber")
        print(f"Signed: {update.SIG} is on the {tag} release. Sticks can update to it.")
        # and tell the clients, through the network (#264): the checksums and the
        # signature, posted by the project key itself in unseenet.releases
        subject, body = update.release_post(sums, sig, "stable")
        art = new_article(RELEASES_GROUP, subject, body, from_name="Unseenet project")
        art = art.finalize(identity, _owner.POW_BITS)
        if asyncio.run(post_everywhere([art.to_bytes()])) == 0:
            print("No node took the post in unseenet.releases: run this again later.")
        else:
            print("Posted in unseenet.releases: clients will offer the update.")


if __name__ == "__main__":
    main()
