#!/usr/bin/env python3
"""Change the passphrase of the project's owner vault.

    python tools/project/change_passphrase.py [vault]

Asks for the old and the new passphrase in the terminal (they are never put
on a command line or in a file), encrypts the vault and any sidecar files
again under the new one, and checks that the new passphrase opens it before
it finishes. The new vault uses Argon2id's SENSITIVE limits (1 GiB, a few
seconds to open): the project key is opened rarely, and only here.

The old files are kept next to it as *.old-<time>, still under the OLD
passphrase. Delete them when you have opened the vault with the new one.
"""

from __future__ import annotations

import getpass
import os
import shutil
import sys
import time
from pathlib import Path

import nacl.pwhash

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from unseenet.core.vault import Vault, VaultError, _key  # noqa: E402

OPS = nacl.pwhash.argon2id.OPSLIMIT_SENSITIVE
MEM = nacl.pwhash.argon2id.MEMLIMIT_SENSITIVE
MIN_LENGTH = 16


def sidecars(path: Path) -> list[str]:
    prefix = path.name + "."
    return sorted(p.name[len(prefix):] for p in path.parent.glob(prefix + "*")
                  if ".old-" not in p.name)


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".unseenet" / "owner.vault"
    if not path.exists():
        sys.exit(f"{path} does not exist")

    try:
        old = Vault.open(path, getpass.getpass(f"Current passphrase for {path}: "))
    except VaultError as exc:
        sys.exit(f"Cannot open the vault: {exc}")
    names = sidecars(path)
    side = {n: old.read_sidecar(n) for n in names}

    print(f"\nChoose a new passphrase: at least {MIN_LENGTH} characters. A few random\n"
          "words are easier to type than symbols. Keep it in your password manager.")
    while True:
        new = getpass.getpass("New passphrase: ")
        if len(new) < MIN_LENGTH:
            print(f"Too short: {len(new)} characters, at least {MIN_LENGTH} please.")
            continue
        if getpass.getpass("Again: ") != new:
            print("They do not match, try again.")
            continue
        break

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backups = []
    for p in [path] + [old.sidecar_path(n) for n in names]:
        b = p.with_name(f"{p.name}.old-{stamp}")
        shutil.copy2(p, b)
        os.chmod(b, 0o600)
        backups.append(b)

    print("Encrypting with the new passphrase (this takes a few seconds) ...", flush=True)
    salt = os.urandom(16)
    nv = Vault(path, _key(new, salt, OPS, MEM), salt, OPS, MEM, old.data)
    for n, payload in side.items():
        nv.write_sidecar(n, payload)
    nv.save()

    print("Checking that the new passphrase opens it ...", flush=True)
    check = Vault.open(path, new)
    if check.data != old.data or any(check.read_sidecar(n) != side[n] for n in names):
        for b in backups:                       # put the old files back
            os.replace(b, b.with_name(b.name.rsplit(".old-", 1)[0]))
        sys.exit("The check FAILED; the old vault has been put back, nothing changed.")

    print(f"\nDone: {path} now opens with the new passphrase.")
    print("The old files, still under the OLD passphrase, are:")
    for b in backups:
        print(f"  {b}")
    print("Delete them once you have opened the vault with the new passphrase:")
    print("  rm " + " ".join(str(b) for b in backups))
    print("\nThen copy the new vault to your two USB sticks.")


if __name__ == "__main__":
    main()
