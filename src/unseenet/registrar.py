"""A registrar for names of identities: one replica (UN-RFC 0019, sections 6 and 6.8).

The registrar is a client, not a node: it reads its group and its claim inbox
through any node, over Tor, like everybody else. It keeps no state of its own
that matters - everything it decides is rebuilt from the certificates in its
group and the claims in its inbox - so a replica can be started on a new
machine at any time, and several replicas, each with its own registrar key,
reach the same decisions without talking to each other.

Keys, in the replica's vault:

- the **registrar key** (the vault's default identity): signs certificates;
  the group's manifest lists it as a poster;
- the **inbox key**: owns the claim inbox and opens claims; shared by all
  replicas; never signs certificates.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import names as nm
from .client.session import Message, Session, SessionError
from .core import crypto
from .core.article import new_article
from .core.groups import personal_inbox_id

log = logging.getLogger("unseenet.registrar")

SETTLE = timedelta(hours=1)               # section 6.8, rules 1 and 2
REPLY_WITHIN = timedelta(days=2)          # a new replica does not answer old claims again
FROM = "Unseenet registrar"
IANA_TLDS = "https://data.iana.org/TLD/tlds-alpha-by-domain.txt"
RESOLVERS = ("1.1.1.1", "8.8.8.8")
MAX_HANDLED = 20000


@dataclass
class Claim:
    id: str
    date: datetime
    sender: str
    reply_inbox: str
    body: str


@dataclass
class Outcome:
    issue_to: str | None = None           # issue a certificate to this key
    revoke: int | None = None             # revoke this serial
    refuse: str | None = None             # or refuse, with this reason


# --- the outside world ------------------------------------------------------------

def dig_txt(name: str) -> list[str]:
    """TXT records of ``name``; only records every resolver agrees on count."""
    answers = []
    for resolver in RESOLVERS:
        try:
            r = subprocess.run(["dig", "+short", "TXT", name, f"@{resolver}"],
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return []
        answers.append({"".join(p.strip('"') for p in line.split('" "'))
                        for line in r.stdout.splitlines() if line})
    return sorted(set.intersection(*answers)) if answers else []


class IanaTlds:
    """The IANA list of top-level domains, fetched when needed and kept for a day."""

    def __init__(self, cache: dict, fetch: Callable[[], str] | None = None):
        self.cache = cache                  # lives in the vault, so it survives restarts
        self.fetch = fetch or (lambda: urllib.request.urlopen(IANA_TLDS, timeout=60).read().decode())

    def __call__(self) -> set[str] | None:
        now = datetime.now(timezone.utc)
        fetched = self.cache.get("fetched")
        if not fetched or now - nm.parse_rfc3339(fetched) > timedelta(days=1):
            try:
                text = self.fetch()
                tlds = sorted(line.strip().lower() for line in text.splitlines()
                              if line.strip() and not line.startswith("#"))
                if len(tlds) > 100:                       # a sane list, not an error page
                    self.cache.update({"fetched": nm.rfc3339(now), "tlds": tlds})
            except OSError as exc:
                log.warning("could not fetch the TLD list: %s", exc)
        return set(self.cache["tlds"]) if self.cache.get("tlds") else None


# --- the registrar -------------------------------------------------------------------

class Registrar:
    def __init__(self, session: Session, group: str = nm.NAMES_GROUP, *,
                 tlds: Callable[[], set[str] | None] | None = None,
                 dns_txt: Callable[[str], list[str]] = dig_txt,
                 now: Callable[[], datetime] | None = None):
        self.s = session
        self.group = group
        self.me = session.identity()                        # the registrar key
        st = session.data.setdefault("registrar", {})
        for key, empty in (("seen", {}), ("handled", []), ("revoked", []), ("tld_cache", {})):
            st.setdefault(key, empty)
        self.st = st
        self.tlds = tlds or IanaTlds(st["tld_cache"])
        self.dns_txt = dns_txt
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.owner: str | None = None
        self.trusted: set[str] = set()
        self.claims_group: str | None = None
        self.certs: list[nm.Certificate] = []
        self.revoked: set[tuple[str, int]] = set()

    # --- reading the group ------------------------------------------------------------

    async def read_group(self) -> None:
        msgs = await self.s.fetch_group(self.group)
        manifest = self.s.manifest_data(self.group)
        self.owner = manifest.get("owner")
        self.trusted = {k for k in [self.owner, *manifest.get("posters", [])] if k}
        self.claims_group = manifest.get("claims")
        if self.me.key_text not in self.trusted:
            raise SessionError(f"this registrar key is not a poster in {self.group}")
        certs: dict[str, nm.Certificate] = {}
        newest: dict[str, tuple[datetime, set]] = {}
        for m in msgs:
            if m.author_key not in self.trusted:
                continue
            if m.subject.startswith("name "):
                try:
                    cert = nm.parse_certificate(m.body)
                except nm.NameProblem:
                    continue
                if cert.registrar in self.trusted:
                    certs[cert.to_json()] = cert
            elif m.subject == nm.REVOKED_SUBJECT and m.date:
                try:
                    revoked = nm.parse_revocations(m.body)
                except (nm.NameProblem, ValueError):
                    continue
                if m.author_key not in newest or m.date >= newest[m.author_key][0]:
                    newest[m.author_key] = (m.date, revoked)
        self.certs = list(certs.values())
        self.revoked = set().union(*(r for _, r in newest.values())) if newest else set()
        self.revoked |= {tuple(x) for x in self.st["revoked"]}

    # --- the state of a name at a point in the order of claims -----------------------

    def _before(self, name: str, when: datetime, claim_id: str) -> list[nm.Certificate]:
        return [c for c in self.certs
                if c.name == name and (c.issued, c.claim or "") < (when, claim_id)]

    def holder(self, name: str, when: datetime, claim_id: str) -> tuple[nm.Certificate | None, bool]:
        """The certificate that counts for ``name`` just before this claim, even if it
        expired less than the grace period ago; and whether the name is disputed."""
        live = [c for c in self._before(name, when, claim_id)
                if (c.name, c.serial) not in self.revoked and c.issued <= when < c.expires + nm.GRACE]
        return nm.current(live)

    def next_serial(self, name: str, when: datetime, claim_id: str) -> int:
        return 1 + max((c.serial for c in self._before(name, when, claim_id)), default=0)

    def names_held(self, key: str, when: datetime, claim_id: str) -> int:
        count = 0
        for name in {c.name for c in self.certs if c.key == key and c.kind == "registered"}:
            cur, _ = self.holder(name, when, claim_id)
            if cur and cur.key == key and when < cur.expires:
                count += 1
        return count

    # --- deciding (section 6) ----------------------------------------------------------

    def decide(self, c: Claim) -> tuple[str | None, Outcome]:
        try:
            data = nm.parse_claim(c.body)
        except nm.NameProblem as exc:
            return None, Outcome(refuse=str(exc))
        name, action = data["name"], data["action"]
        kind = nm.kind_of(name)
        cur, disputed = self.holder(name, c.date, c.id)
        if disputed:
            return name, Outcome(refuse="the name is disputed; ask in unseenet.admin")
        holder = cur.key if cur else None
        mine = holder == c.sender

        if action in ("transfer", "release"):
            if not mine:
                return name, Outcome(refuse="you do not hold this name")
            if action == "release":
                return name, Outcome(revoke=cur.serial)
            return name, Outcome(issue_to=data["to"], revoke=cur.serial)

        if holder and not mine:
            return name, Outcome(refuse="the name is taken")
        if action == "renew" and not mine:
            return name, Outcome(refuse="you do not hold this name; claim it instead")
        if kind == "registered":
            tlds = self.tlds()
            if tlds is None:
                return name, Outcome(refuse="the list of top-level domains is unavailable; try again later")
            if name in tlds:
                return name, Outcome(refuse="the name is an Internet top-level domain")
            if name in nm.RESERVED and c.sender != self.owner:
                return name, Outcome(refuse="the name is reserved")
            if not mine and self.names_held(c.sender, c.date, c.id) >= nm.MAX_NAMES_PER_KEY:
                return name, Outcome(refuse=f"a key can hold at most {nm.MAX_NAMES_PER_KEY} names")
        elif nm.dns_record_value(c.sender) not in self.dns_txt(nm.dns_record_name(name)):
            return name, Outcome(refuse=f"no TXT record {nm.dns_record_name(name)} with your key")
        return name, Outcome(issue_to=c.sender)

    # --- acting ---------------------------------------------------------------------------

    async def _post_json(self, subject: str, body: str) -> None:
        def build(bits):
            art = new_article(self.group, subject, body, from_name=FROM,
                              extra=[("Content-Type", "application/json")])
            return art.finalize(self.me, bits)
        await self.s._post_with_postage(self.group, build)

    async def issue(self, name: str, key: str, serial: int, *, claim: str | None,
                    claimed: datetime | None, when: datetime | None = None) -> nm.Certificate:
        cert = nm.make_certificate(self.me, name, key, serial, when, claim=claim, claimed=claimed)
        if any(c.to_json() == cert.to_json() for c in self.certs):
            return cert
        await self._post_json(nm.certificate_subject(name), cert.to_json() + "\n")
        self.certs.append(cert)
        log.info("issued %s to %s, serial %d", name, key, serial)
        return cert

    async def revoke(self, name: str, serial: int) -> None:
        entry = [name, serial]
        if entry in self.st["revoked"]:
            return
        self.st["revoked"].append(entry)
        self.revoked.add((name, serial))
        self._drop_expired_revocations()
        await self._post_json(nm.REVOKED_SUBJECT,
                              nm.make_revocations({tuple(x) for x in self.st["revoked"]}))
        log.info("revoked %s serial %d", name, serial)

    def _drop_expired_revocations(self) -> None:
        now = self.now()
        live = {(c.name, c.serial) for c in self.certs if now < c.expires}
        self.st["revoked"] = [x for x in self.st["revoked"] if tuple(x) in live]

    async def reply(self, c: Claim, subject: str, body: str, json_body: bool = False) -> None:
        if self.now() - c.date > REPLY_WITHIN:
            return
        try:
            await self.s.send_private(c.reply_inbox, subject, body,
                                      content_type="application/json" if json_body else None)
        except (SessionError, OSError, ConnectionError) as exc:
            log.warning("could not answer %s: %s", c.id, exc)

    # --- one round ------------------------------------------------------------------------

    async def read_claims(self) -> list[Claim]:
        if not self.claims_group:
            raise SessionError(f"{self.group} has no claims inbox in its manifest")
        msgs: list[Message] = await self.s.fetch_group(self.claims_group)
        now, seen, fresh = self.now(), self.st["seen"], not self.st["seen"]
        claims = []
        for m in msgs:
            if not (m.private and m.readable and m.sender_key and m.date):
                continue
            # a new replica counts what is already there as seen in time (section 6.8)
            seen.setdefault(m.message_id, nm.rfc3339(m.date if fresh else now))
            reply_to = m.reply_inbox or personal_inbox_id(crypto.key_from_text(m.sender_key))
            claims.append(Claim(m.message_id, m.date, m.sender_key, reply_to, m.body))
        if not seen:
            seen["-"] = nm.rfc3339(now)             # remember that we have started
        return sorted(claims, key=lambda c: (c.date, c.id))

    async def run_once(self) -> None:
        await self.read_group()
        now = self.now()
        handled = self.st["handled"]
        for c in await self.read_claims():
            if c.id in handled or c.date > now - SETTLE:
                continue
            handled.append(c.id)
            if nm.parse_rfc3339(self.st["seen"][c.id]) - c.date > SETTLE:
                await self.reply(c, "late", "Your claim arrived late; send it again.\n")
                continue
            name, out = self.decide(c)
            if out.refuse:
                await self.reply(c, f"name {name or '?'}: refused", out.refuse + "\n")
                continue
            if out.revoke is not None:
                await self.revoke(name, out.revoke)
            if out.issue_to:
                cert = await self.issue(name, out.issue_to, self.next_serial(name, c.date, c.id),
                                        claim=c.id, claimed=c.date)
                await self.reply(c, f"name {name}: issued", cert.to_json() + "\n", json_body=True)
            elif out.revoke is not None:
                await self.reply(c, f"name {name}: released", "The name is free again.\n")
        del handled[:-MAX_HANDLED]
        await self.converge()
        await self.renew_domains()
        self.s.save()

    async def converge(self) -> None:
        """Rule 4 of section 6.8: sign another replica's decision that wins over ours.

        Nothing is revoked: section 5.3 already makes the earlier claim win on every
        client, and a revocation would hit the winner too (it names a serial).
        """
        mine = {c.decision for c in self.certs if c.registrar == self.me.key_text}
        for c in [c for c in self.certs if c.registrar == self.me.key_text]:
            same = [o for o in self.certs if o.name == c.name and o.serial == c.serial]
            winner, disputed = nm.current(same)
            if disputed or winner is None or winner.decision in mine:
                continue
            await self.issue(winner.name, winner.key, winner.serial, claim=winner.claim,
                             claimed=winner.claimed, when=winner.issued)
            mine.add(winner.decision)

    async def renew_domains(self) -> None:
        """Monthly renewal of domain names whose record is still there (section 6.4)."""
        now = self.now()
        month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for name in sorted({c.name for c in self.certs if c.kind == "domain"}):
            cur, disputed = self.holder(name, month, "")
            if disputed or cur is None or now >= cur.expires or cur.issued >= month:
                continue
            if nm.dns_record_value(cur.key) not in self.dns_txt(nm.dns_record_name(name)):
                log.info("%s: TXT record gone, not renewed", name)
                continue
            await self.issue(name, cur.key, self.next_serial(name, month, ""),
                             claim=None, claimed=None, when=month)


async def run(session: Session, *, interval: float = 300, once: bool = False, **kw) -> None:
    reg = Registrar(session, **kw)
    try:
        while True:
            try:
                await reg.run_once()
            except (SessionError, OSError, ConnectionError, asyncio.IncompleteReadError) as exc:
                log.warning("round failed: %s", exc)
            if once:
                return
            await asyncio.sleep(interval)
    finally:
        await session.close()                  # stops Tor


# --- the program ---------------------------------------------------------------------------

def main(argv=None) -> None:
    """``unseenet-registrar``: set up and run one replica of a registrar."""
    import argparse
    import getpass
    import os
    from pathlib import Path

    from .core.vault import Vault, VaultError

    p = argparse.ArgumentParser(prog="unseenet-registrar", description=(
        "Run one replica of a registrar for names of identities (UN-RFC 0019). "
        "The replica's keys are kept in an encrypted vault; the passphrase is read from "
        "UNSEENET_REGISTRAR_PASSPHRASE, from --passphrase-file, or asked for."))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="make the replica's vault from its two keys")
    s.add_argument("vault", type=Path)
    s = sub.add_parser("run", help="handle claims and renewals")
    s.add_argument("vault", type=Path)
    s.add_argument("--group", default=nm.NAMES_GROUP, help="the registrar's group")
    s.add_argument("--node", action="append", default=[],
                   help="a node to use (repeat; default: the project's list of known nodes)")
    s.add_argument("--interval", type=float, default=300, help="seconds between rounds")
    s.add_argument("--once", action="store_true", help="one round, then stop")
    s.add_argument("--passphrase-file", type=Path, help="read the passphrase from this file")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "init":
        if args.vault.exists():
            p.error(f"{args.vault} exists already")
        print("Each replica has its own registrar key; all replicas share the inbox key.")
        print("Seeds are 64 hex characters and are not shown as you type.")
        idents = {}
        for role, prompt in (("registrar", "registrar key seed (Enter: make a new key here): "),
                             ("inbox", "inbox key seed (from the registrar group's owner): ")):
            seed = getpass.getpass(prompt).strip()
            if not seed and role == "registrar":
                idents[role] = crypto.Identity.generate()
                continue
            try:
                idents[role] = crypto.Identity.from_seed(bytes.fromhex(seed))
            except ValueError:
                p.error(f"that is not a {role} key seed")
        while True:
            pw = getpass.getpass("New vault passphrase (16 characters or more): ")
            if len(pw) >= 16 and getpass.getpass("Again: ") == pw:
                break
            print("Too short, or they do not match.")
        vault = Vault.open(args.vault, pw)
        for role, ident in idents.items():
            vault.data["identities"][role] = {"seed": ident.seed.hex(), "display": FROM}
        vault.data["default_identity"] = "registrar"
        vault.save()
        print(f"registrar key {idents['registrar'].key_text}")
        print(f"inbox key     {idents['inbox'].key_text}")
        print("Send the registrar key (above, it is public) to the registrar group's owner,")
        print("who lists it as a poster in the group's manifest. Then: unseenet-registrar run")
        return

    pw = (os.environ.get("UNSEENET_REGISTRAR_PASSPHRASE")
          or (args.passphrase_file.read_text().strip() if args.passphrase_file else None)
          or getpass.getpass("Vault passphrase: "))
    try:
        session = Session(Vault.open(args.vault, pw), status=lambda m: log.info("%s", m))
    except VaultError as exc:
        p.error(str(exc))
    for node in args.node or [n.address for n in session.known_nodes()]:
        session.add_node(node)
    log.info("registrar %s for %s", session.identity().key_text, args.group)
    try:
        asyncio.run(run(session, interval=args.interval, once=args.once, group=args.group))
    except KeyboardInterrupt:
        pass
    finally:
        session.save()


if __name__ == "__main__":
    main()
