"""Make a new release key for development builds and put it in GitHub secrets.

    python tools/project/new_release_key.py [REPO ...]

CI signs the SHA256SUMS.txt of development builds with this key (secret
UNSEENET_RELEASE_KEY, a hex seed). The seed goes straight from memory to
``gh secret set`` in every repository given - by default the build
repositories unseenet-portable and unseenet-bootable (#549, #550), which share
one key - and is never written to a file or shown; the public key is printed,
to be added to DEV_RELEASE_KEYS in src/unseenet/update.py.

Run it again to replace a lost or leaked key. Sticks on the dev channel then
need one release signed with the project key (tools/project/sign_release.py)
that pins the new public key; they always trust the project key.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from unseenet.core.crypto import Identity  # noqa: E402

REPOS = ["unseenet/unseenet-portable", "unseenet/unseenet-bootable"]
SECRET = "UNSEENET_RELEASE_KEY"


def main() -> None:
    repos = sys.argv[1:] or REPOS
    key = Identity.generate()
    for repo in repos:
        r = subprocess.run(["gh", "secret", "set", SECRET, "-R", repo],
                           input=key.seed.hex(), text=True, capture_output=True)
        if r.returncode != 0:
            sys.exit(f"gh secret set failed for {repo}: {r.stderr.strip()}")
        print(f"{SECRET} is set in {repo}.")
    print(f"Public key, for DEV_RELEASE_KEYS in src/unseenet/update.py:\n{key.key_text}")


if __name__ == "__main__":
    main()
