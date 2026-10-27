#!/usr/bin/env python3
"""Put the project's spam report issuer beside your own identity in your everyday vault.

    python3 tools/project/issuer_to_vault.py [VAULT]

VAULT is your everyday client's vault, by default ~/Unseenet/klient/unseenet.vault.
This copies, from ~/.unseenet/issuer.vault (report_issuer.py):

- the issuer's identity, as a second identity named "reports" - your own stays the
  one in use, so nothing you post changes;
- its reports group (that it owns reports@...), and its ripening chain, so it need
  not ripen again.

Then the reports sent to the contact inbox (which you read with a team key) offer
*Publish a spam report… as reports@unseenet* where you read them, in the GUI, the
TUI and `unseenet reports received --publish N`. Both passphrases are asked for in
the terminal. The issuer's key is then in two vaults: take a backup of both
(backup/LÆS-MIG.md); if your everyday vault is lost, make a new issuer with
report_issuer.py and name it where the old one was named.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

from _owner import ROOT  # noqa: E402,F401  (puts src/ on the path)

from unseenet.core import reports as rpt  # noqa: E402
from unseenet.core.vault import Vault, VaultError  # noqa: E402

ISSUER = Path.home() / ".unseenet" / "issuer.vault"
NAME = "reports"


def open_vault(path: Path, what: str) -> Vault:
    try:
        return Vault.open(path, getpass.getpass(f"Passphrase for {what} ({path}): "))
    except VaultError as exc:
        sys.exit(f"Cannot open {path}: {exc}")


def main() -> None:
    target = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else \
        Path.home() / "Unseenet" / "klient" / "unseenet.vault"
    if not ISSUER.exists():
        sys.exit(f"{ISSUER} does not exist: run report_issuer.py first.")
    if not target.exists():
        sys.exit(f"{target} does not exist.")
    src = open_vault(ISSUER, "the issuer vault (#4)")
    dst = open_vault(target, "your everyday vault (#3)")
    [(_, ident)] = list(src.data["identities"].items())[:1]
    from unseenet.core import crypto
    key = crypto.Identity.from_seed(bytes.fromhex(ident["seed"]))
    have = dst.data.setdefault("identities", {})
    same = [n for n, e in have.items() if e.get("seed") == ident["seed"]]
    if same:
        print(f"The issuer is already in {target} as {same[0]!r}; its group and chain are refreshed.")
        name = same[0]
    else:
        if NAME in have:
            sys.exit(f"{target} has another identity named {NAME!r}; nothing changed.")
        name = NAME
        have[name] = dict(ident)
    gid = rpt.reports_group(key.public_key)
    if gid in src.data.get("groups", {}):
        dst.data.setdefault("groups", {})[gid] = dict(src.data["groups"][gid])
    chain = src.data.get("ripening", {}).get(key.key_text)
    if chain:
        dst.data.setdefault("ripening", {})[key.key_text] = dict(chain)
    if not dst.data.get("default_identity"):            # your own stays the one in use
        dst.data["default_identity"] = next(n for n in have if n != name)
    dst.save()
    print(f"Added {key.key_text} as {name!r} to {target}.\n"
          f"Your own identity is still the one in use. Reports sent to the contact inbox "
          f"now offer to be published as the issuer. Take a backup: ./lav-backup.sh")


if __name__ == "__main__":
    main()
