"""Sign a development build's SHA256SUMS.txt in CI (the dev pre-release).

    UNSEENET_RELEASE_KEY=<hex seed> python tools/sign_sums.py zips/SHA256SUMS.txt

Writes SHA256SUMS.txt.sig next to it. The key is the release key, trusted only
for the dev channel (unseenet.update); stable releases are signed by the
maintainer with the project key (tools/project/sign_release.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unseenet import update  # noqa: E402
from unseenet.core.crypto import Identity  # noqa: E402


def main() -> None:
    seed = os.environ.get("UNSEENET_RELEASE_KEY", "").strip()
    if not seed:
        sys.exit("UNSEENET_RELEASE_KEY is not set")
    sums_path = Path(sys.argv[1])
    sums = sums_path.read_bytes()
    sig = update.signature_text(sums, Identity.from_seed(bytes.fromhex(seed)))
    update.check_signature(sums, sig, "dev")      # fails if the secret is not the pinned key
    update.update_zip_in(update.parse_sums(sums))  # and if the update zip is missing
    sums_path.with_name(update.SIG).write_text(sig)
    print(f"signed {sums_path}")


if __name__ == "__main__":
    main()
