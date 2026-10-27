#!/usr/bin/env python3
"""The project's spam report issuer (UN-RFC 0045, #122): a key of its own, not the
project key, that publishes reports in `reports@<its fingerprint>`.

    python3 tools/project/report_issuer.py [--dry-run]

Reports are daily work; the project key must stay offline. So the issuer is a
separate identity in a vault of its own, ~/.unseenet/issuer.vault (made here, with
a passphrase you choose; it is asked for in the terminal, never stored). This:

- makes the vault and the identity "Unseenet spam reports" if they do not exist;
- starts (or updates) its reports group: what it reports, and where to object -
  the project's contact inbox, contact@ph5fc5hop5232qsz (team_contact.py);
- prints its key, and what to do next.

Nobody follows the issuer because it exists: nodes follow it only if their
operator names it in [[follow_reports]], readers only if they choose it or a
hierarchy they read names it. Naming it for the project's hierarchies
(`report_issuers` in their lists) is a separate decision.

Publishing a report, from the reports people send to the contact inbox:
    unseenet --vault ~/.unseenet/issuer.vault reports received
    unseenet --vault ~/.unseenet/issuer.vault reports received --publish 1 [--key]

Take a backup afterwards (backup/LÆS-MIG.md): issuer.vault is new.
--dry-run says what it would do and changes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

from _owner import FP, builtin_list  # noqa: E402  (also puts src/ on the path)

from unseenet.client.session import Session, SessionError  # noqa: E402
from unseenet.core.vault import Vault, VaultError  # noqa: E402

VAULT = Path.home() / ".unseenet" / "issuer.vault"
NAME, DISPLAY = "reports", "Unseenet spam reports"
POLICY = ("Spam reports from the Unseenet project: floods of the same text, phishing and "
          "malware, in the hierarchies the project looks after. Reports name posts, and keys "
          "for at most a year; they are made by people, not programs. Nothing is hidden for "
          "anyone who does not follow this issuer.")
CONTACT = f"contact@{FP}"


def open_vault(dry: bool) -> Session | None:
    new = not VAULT.exists()
    if new and dry:
        print(f"{VAULT}: would be made, with the identity '{DISPLAY}'")
        return None
    pw = getpass.getpass(f"{'New passphrase' if new else 'Passphrase'} for {VAULT}: ")
    if new and getpass.getpass("Again: ") != pw:
        sys.exit("The passphrases differ; nothing made.")
    try:
        s = Session(Vault.open(VAULT, pw), status=lambda *_: None)
    except VaultError as exc:
        sys.exit(f"Cannot open the vault: {exc}")
    if not s.data.get("identities"):
        s.new_identity(NAME, DISPLAY)
        print(f"Made {VAULT} with the identity '{DISPLAY}'")
    return s


async def run(dry: bool) -> None:
    s = open_vault(dry)
    if s is None:
        print("--dry-run: nothing made.")
        return
    for node in builtin_list()[1]:
        if node.address not in s.nodes:
            s.add_node(node.address)
    try:
        key = s.identity().key_text
        print(f"Issuer key: {key}\nReports group: {s.my_reports_group()}")
        if dry:
            print("--dry-run: the reports group is not started or changed.")
            return
        print("Starting its reports group over Tor (its key ripens first, a few minutes) ...", flush=True)
        try:
            await s.start_reports(POLICY, CONTACT)
        except SessionError as exc:
            sys.exit(f"Not started: {exc}")
        print(f"""
Done. Next:
- backup: ./lav-backup.sh in ~/Unseenet/backup (issuer.vault is new; see LÆS-MIG.md)
- a name: add  "reports": "{key}"  to NAMES in give_names.py and run it
- to have it hide spam for readers of a hierarchy you maintain (a decision of its own):
    unseenet --vault ~/.unseenet/owner.vault reports hierarchy <hierarchy> {key}
- to have a node act on its reports, in node.toml:
    [[follow_reports]]
    issuer = "{key}"
    posts = "hide"
    keys = "surcharge\"""")
    finally:
        s.save()
        await s.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="say what would be done, change nothing")
    asyncio.run(run(ap.parse_args().dry_run))


if __name__ == "__main__":
    main()
