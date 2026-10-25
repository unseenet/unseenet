#!/usr/bin/env python3
"""Give another of the project's repositories the GitHub poster key.

    python tools/project/share_poster.py unseenet/unseenet-entrance

The GitHub poster is the key the project key lists as a poster in its
channels (create_groups.py). It is kept in the owner vault and as the secret
UNSEENET_ANNOUNCE_SEED of unseenet/unseenet. This puts the same secret into
the repository given, so that its CI can post too: unseenet-entrance posts new
versions of the web client in unseenet.releases, and unseenet-portable
announces its development builds there (#549), and unseenet-bootable its
images (#550).

The seed goes straight from the vault to ``gh secret set`` and is never shown
or written to a file. To take it away again, delete the secret on GitHub; if
it may have leaked, make a new poster and change the channels' manifests.
"""

from __future__ import annotations

import re
import subprocess
import sys

import _owner  # noqa: F401  (puts src/ on the path)
from _owner import open_owner_session

from unseenet.core import crypto

SECRET = "UNSEENET_ANNOUNCE_SEED"
ALLOWED = {"unseenet/unseenet", "unseenet/unseenet-entrance", "unseenet/unseenet-portable",
           "unseenet/unseenet-bootable"}


def main() -> None:
    if len(sys.argv) != 2 or not re.fullmatch(r"[\w.-]+/[\w.-]+", sys.argv[1]):
        sys.exit(__doc__.strip().splitlines()[2].strip())
    repo = sys.argv[1]
    if repo not in ALLOWED:
        sys.exit(f"{repo} is not one of the project's repositories that post: {', '.join(sorted(ALLOWED))}")
    s = open_owner_session()
    entry = s.data.get("github_poster")
    if not entry or not entry.get("seed"):
        sys.exit("The owner vault has no github_poster key.")
    key = crypto.Identity.from_seed(bytes.fromhex(entry["seed"]))
    r = subprocess.run(["gh", "secret", "set", SECRET, "-R", repo],
                       input=key.seed.hex(), text=True, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"gh secret set failed: {r.stderr.strip()}")
    print(f"{SECRET} is set in {repo}: it can post as {key.key_text}.")


if __name__ == "__main__":
    main()
