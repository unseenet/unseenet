"""Hierarchy claims and the root list a list council keeps (UN-RFC 0020 sections 5.2, 6.2).

A top-level hierarchy is claimed as a name is (UN-RFC 0054 section 8): a commit and,
between one hour and seven days later, a reveal, both by the claiming key in the
council's claims group. The council does not judge claims; its replicas apply the same
rules in the order of the commits, and so post the same root list:

- a free name goes to the first counting claim, for a year from its commit, renewed by
  the maintainer's ``renew``;
- a name equal to a top-level domain (``dk``, ``com``) goes only to a key the domain's
  registry names in DNS (``_unseenet.nic.<tld>``, as for names, UN-RFC 0019 section 4.5),
  and lapses when the record has been gone for 30 days;
- reserved names are never granted; a key holds at most 3 hierarchies and must be
  ripened to the council's ``min_level``;
- ``change`` moves a hierarchy to a new maintainer, ``release`` gives it up.

Belongs here: the claim body, its commit and reveal, and the rules - pure, over what a
caller read and the DNS answers it got. Not here: reading, asking DNS, posting
(``replica/lists.py``)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from .. import hierarchies as hz
from .. import names as nm
from . import crypto
from .groups import canonical_json, parse_canonical_json, split_group_id

DS_HIERARCHY_COMMIT = "UNSEENET-HIERARCHY-COMMIT-1"
ACTIONS = ("claim", "renew", "change", "release")
MAX_PER_KEY = 3                          # section 5.2
LIFETIME = timedelta(days=365)           # section 6.2: a year from its commit
DNS_GONE = timedelta(days=30)            # a TLD grant lapses when the record is gone this long
MAX_NAME = 32
MAX_TITLE = 64                           # the root list's limits (UN-RFC 0018 section 4.1)
MAX_CHARTER = 200
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def check_name(name) -> str:
    if not isinstance(name, str) or not _NAME.match(name) or len(name) > MAX_NAME:
        raise nm.NameProblem(f"not a top-level hierarchy name: {name!r}")
    return name


def make_claim(action: str, name: str, *, list: str | None = None, title: str | None = None,
               charter: str | None = None, maintainer: str | None = None) -> str:
    """The canonical claim body (section 5.2)."""
    d: dict = {"v": 1, "action": action, "name": name}
    for k, v in (("list", list), ("title", title), ("charter", charter),
                 ("maintainer", maintainer)):
        if v:
            d[k] = v
    body = canonical_json(d) + "\n"
    parse_claim(body)
    return body


def parse_claim(body: str) -> dict:
    """A hierarchy claim's fields, checked. Raises ``nm.NameProblem`` (so that the
    commit and reveal rules of the names treat it alike)."""
    try:
        d = parse_canonical_json(body if body.endswith("\n") else body + "\n")
    except ValueError as exc:
        raise nm.NameProblem("the claim is not canonical JSON") from exc
    if not isinstance(d, dict) or d.get("v") != 1 or d.get("action") not in ACTIONS:
        raise nm.NameProblem("not a version 1 hierarchy claim")
    if set(d) - {"v", "action", "name", "list", "title", "charter", "maintainer"}:
        raise nm.NameProblem("unknown fields in a hierarchy claim")
    check_name(d.get("name"))
    action = d["action"]
    if action in ("claim", "change"):
        try:
            split_group_id(d.get("list") or "")
        except (ValueError, TypeError) as exc:
            raise nm.NameProblem(f"a {action} names the hierarchy list group") from exc
    if action == "claim":
        t = d.get("title")
        if not isinstance(t, str) or not t.strip() or len(t) > MAX_TITLE:
            raise nm.NameProblem(f"a claim has a title of 1 to {MAX_TITLE} characters")
    if "charter" in d and (not isinstance(d["charter"], str) or len(d["charter"]) > MAX_CHARTER):
        raise nm.NameProblem(f"a charter is at most {MAX_CHARTER} characters")
    if action == "change":
        try:
            crypto.key_from_text(d.get("maintainer") or "")
        except (crypto.CryptoError, TypeError) as exc:
            raise nm.NameProblem("a change names the new maintainer key") from exc
    return d


def make_commit(claim_body: str, nonce: bytes | None = None) -> tuple[str, bytes]:
    return nm.make_commit(claim_body, nonce, parse=parse_claim, ds=DS_HIERARCHY_COMMIT)


def make_reveal(claim_body: str, nonce: bytes, reply_inbox: str) -> str:
    return nm.make_reveal(claim_body, nonce, reply_inbox, parse=parse_claim)


def read_claims(posts: list[nm.Post]) -> list[nm.PublicClaim]:
    """Every commit in the claims group, in order, each with its counting reveal."""
    return nm.read_public_claims(posts, parse=parse_claim, ds=DS_HIERARCHY_COMMIT)


def dns_key(claim_body: str, sender: str) -> str:
    """The key a TLD's record must name for this claim: the new maintainer's for a
    ``change``, else the claiming key's."""
    d = parse_claim(claim_body)
    return d.get("maintainer") or sender


def needs_dns(claim_body: str, tlds) -> bool:
    d = parse_claim(claim_body)
    return d["action"] in ("claim", "change") and d["name"] in tlds


# --- the rules (section 6.2) ---------------------------------------------------------

@dataclass
class Grant:
    name: str
    maintainer: str
    list: str
    title: str
    description: str = ""
    contact: str = ""
    granted: datetime | None = None
    expires: datetime | None = None          # None: held while DNS says so (a TLD)
    imported: bool = False

    def entry(self) -> dict:
        e = {"name": self.name, "policy": "governed", "maintainer": self.maintainer,
             "list": self.list, "title": self.title}
        if self.description:
            e["description"] = self.description
        if self.contact:
            e["contact"] = self.contact
        return e


@dataclass
class RootState:
    """What the rules made of the claims: the grants, and why each claim did what it did."""
    grants: dict[str, Grant] = field(default_factory=dict)
    why: dict[str, str] = field(default_factory=dict)      # commit id -> plain words


def _fp_of(group: str) -> str:
    return split_group_id(group)[1]


def apply_claims(claims: list[nm.PublicClaim], *, until: datetime, genesis: datetime,
                 imported: dict[str, hz.Hierarchy], reserved: set[str], removed: set[str],
                 tlds: set[str], level: dict[str, int | None], min_level: int,
                 dns: dict[str, bool], dns_gone: set[str]) -> RootState:
    """Apply the revealed claims whose commits are before ``until``, in order.

    ``imported``: the root list the council started from; its governed entries are held
    as if claimed on the ``genesis`` date. ``dns``: for each claim that needs it, by
    commit id, whether the TLD's record named the right key when a replica checked it.
    ``dns_gone``: TLD names whose record has been gone for 30 days."""
    st = RootState()
    for name, h in imported.items():
        if h.policy == "governed":
            st.grants[name] = Grant(name, h.maintainer, h.list, h.title, h.description,
                                    h.contact, genesis,
                                    None if name in tlds else genesis + LIFETIME, True)

    def held_by(key: str) -> int:
        return sum(1 for g in st.grants.values() if g.maintainer == key)

    for c in claims:
        if c.claim_body is None or c.date >= until:
            continue
        d = parse_claim(c.claim_body)
        name, key, action = d["name"], c.sender, d["action"]
        g = st.grants.get(name)
        if g is not None and g.expires is not None and g.expires <= c.date:
            del st.grants[name]                    # lapsed before this claim
            g = None

        def no(why):
            st.why[c.id] = f"{action} {name}: {why}"

        if action == "claim":
            if name in reserved or name in removed:
                no("the name is reserved")
                continue
            if g is not None:
                no(f"held by {g.maintainer}")
                continue
            lvl = level.get(key)
            if lvl is None or lvl < min_level:
                no(f"the key is not ripened to level {min_level}")
                continue
            if held_by(key) >= MAX_PER_KEY:
                no(f"the key holds {MAX_PER_KEY} hierarchies already")
                continue
            if _fp_of(d["list"]) != crypto.fingerprint(crypto.key_from_text(key)):
                no("the list group is not the claiming key's")
                continue
            tld = name in tlds
            if tld and not dns.get(c.id):
                no(f"{nm.tld_record_name(name)} does not name the key")
                continue
            st.grants[name] = Grant(name, key, d["list"], d["title"], d.get("charter", ""), "",
                                    c.date, None if tld else c.date + LIFETIME)
            st.why[c.id] = f"claim {name}: granted"
        elif g is None or g.maintainer != key:
            no("only its maintainer can do that")
        elif action == "renew":
            if g.expires is not None:
                g.expires = c.date + LIFETIME
            st.why[c.id] = f"renew {name}: until {(g.expires or c.date).date()}"
        elif action == "change":
            new = d["maintainer"]
            if _fp_of(d["list"]) != crypto.fingerprint(crypto.key_from_text(new)):
                no("the list group is not the new maintainer's")
                continue
            if name in tlds and not dns.get(c.id):
                no(f"{nm.tld_record_name(name)} does not name the new maintainer")
                continue
            g.maintainer, g.list, g.imported = new, d["list"], False
            st.why[c.id] = f"change {name}: to {new}"
        elif action == "release":
            del st.grants[name]
            st.why[c.id] = f"release {name}: free again"
    for name in list(st.grants):
        g = st.grants[name]
        if (g.expires is not None and g.expires <= until) or name in removed or (
                g.expires is None and name in dns_gone):
            del st.grants[name]
    return st


def root_list(day: date, seq: int, st: RootState, imported: dict[str, hz.Hierarchy],
              reserved: set[str]) -> str:
    """The root list (UN-RFC 0018 section 4) for ``day``: the grants, and the imported
    free and reserved entries, by name."""
    entries: dict[str, dict] = {}
    for name, h in imported.items():
        if h.policy in ("free", "reserved"):
            e = {"name": name, "policy": h.policy}
            for k in ("title", "description"):
                if getattr(h, k):
                    e[k] = getattr(h, k)
            entries[name] = e
    for name in reserved - set(entries):
        entries[name] = {"name": name, "policy": "reserved"}
    for name, g in st.grants.items():
        entries[name] = g.entry()
    items = [entries[k] for k in sorted(entries)][:hz.MAX_ENTRIES]
    body = canonical_json({"v": 1, "updated": f"council {seq} day {day.isoformat()}",
                           "hierarchies": items}) + "\n"
    hz.parse_root_list(body)                       # what clients will read
    return body


def end_of(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time(), timezone.utc)
