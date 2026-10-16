"""Make a new release key for development builds and put it in GitHub secrets.

    python tools/project/new_release_key.py

CI signs the SHA256SUMS.txt of development builds with this key (secret
UNSEENET_RELEASE_KEY, a hex seed). The seed goes straight from memory to
``gh secret set`` and is never written to a file or shown; the public key is
printed, to be pinned as DEV_RELEASE_KEY in src/unseenet/update.py.

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

REPO = "unseenet/unseenet"
SECRET = "UNSEENET_RELEASE_KEY"


def main() -> None:
    key = Identity.generate()
    r = subprocess.run(["gh", "secret", "set", SECRET, "-R", REPO],
                       input=key.seed.hex(), text=True, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"gh secret set failed: {r.stderr.strip()}")
    print(f"{SECRET} is set in {REPO}.")
    print(f"Public key, for DEV_RELEASE_KEY in src/unseenet/update.py:\n{key.key_text}")


if __name__ == "__main__":
    main()
