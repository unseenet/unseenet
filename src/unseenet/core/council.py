"""Council groups: groups owned by a council of keys (UN-RFC 0054 Part I).

Belongs here: a council group's ID (section 3), reading a council manifest
(section 4) and counting the chain of council manifests from the identical
copies its members posted (section 5) - genesis, quorum, one change at a time,
the current manifest and forks. Pure functions: the node and the client feed
in the manifest articles they hold and get the chain back.

Not here: the posting rules of a council group (section 6) belong to the node,
and the reasons for an admission or removal (Part II) to the replicas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import crypto
from .article import Article, ArticleError
from .encoding import DS, H, b32, b64
from .groups import (_NAME_RE, canonical_json, format_expires, parse_canonical_json,
                     parse_expires, split_group_id)

DS_COUNCIL = "UNSEENET-COUNCIL-1"
COUNCIL_TYPES = ("open", "channel")       # section 4
MAX_MEMBERS = 16                          # section 4
DEFAULT_MIN_LEVEL = 4
DEFAULT_MAX_PROBATION = 1
ADMISSION_GAP = timedelta(days=30)        # section 5, item 2
PROBATION = timedelta(days=180)           # section 5, item 2
MIN_FULL = 2                              # section 5, item 3


def council_fingerprint(genesis_body: str) -> str:
    """Section 3: the first 16 characters of b32(H(DS || genesis body))."""
    body = genesis_body[:-2] if genesis_body.endswith("\r\n") else genesis_body.rstrip("\n")
    return b32(H(DS(DS_COUNCIL) + body.encode("utf-8")))[:16]


def make_council_group_id(name: str, genesis_body: str) -> str:
    if not _NAME_RE.match(name):
        raise ValueError(f"bad group name: {name}")
    return f"{name}@{council_fingerprint(genesis_body)}"


def body_hash(body: str) -> str:
    """The ``prev`` of the next manifest: b64(H(DS || body)) (section 4)."""
    text = body[:-2] if body.endswith("\r\n") else body.rstrip("\n")
    return b64(H(DS(DS_COUNCIL) + text.encode("utf-8")))


# --- reading a council manifest (section 4) ---------------------------------

@dataclass(frozen=True)
class Member:
    key: bytes
    joined: datetime
    full: bool

    def as_json(self) -> dict:
        return {"full": self.full, "joined": format_expires(self.joined),
                "key": crypto.key_to_text(self.key)}


@dataclass
class CouncilManifest:
    group_id: str
    name: str
    type: str
    seq: int
    prev: str | None
    date: datetime
    members: list[Member]
    min_level: int
    max_probation: int
    sponsors: int
    succeeds: dict | None
    body: str                              # the canonical body, without line ends
    data: dict = field(default_factory=dict)

    @property
    def hash(self) -> str:
        return body_hash(self.body)

    @property
    def keys(self) -> list[bytes]:
        return [m.key for m in self.members]

    @property
    def full(self) -> list[bytes]:
        return [m.key for m in self.members if m.full]

    @property
    def on_probation(self) -> list[bytes]:
        return [m.key for m in self.members if not m.full]

    def member(self, key: bytes) -> Member | None:
        return next((m for m in self.members if m.key == key), None)

    @classmethod
    def from_body(cls, group_id: str, body: str) -> "CouncilManifest":
        data = parse_canonical_json(body)
        text = body.rstrip("\n").rstrip("\r")
        try:
            name, _fp = split_group_id(group_id)
            c = data["council"]
            if not isinstance(c, dict):
                raise ValueError("council is not an object")
            members = []
            for m in c["members"]:
                if not isinstance(m, dict) or not isinstance(m.get("full"), bool):
                    raise ValueError("bad member")
                members.append(Member(crypto.key_from_text(m["key"]),
                                      parse_expires(m["joined"]), m["full"]))
            seq = c["seq"]
            if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
                raise ValueError("bad seq")
            prev = c.get("prev")
            cm = cls(
                group_id=group_id, name=data["name"], type=data["type"], seq=seq,
                prev=prev, date=parse_expires(c["date"]), members=members,
                min_level=_int(c, "min_level", DEFAULT_MIN_LEVEL),
                max_probation=_int(c, "max_probation", DEFAULT_MAX_PROBATION),
                sponsors=_int(c, "sponsors", 0), succeeds=c.get("succeeds"),
                body=text, data=data)
        except (KeyError, TypeError, ValueError, crypto.CryptoError) as exc:
            raise ArticleError("syntax", f"bad council manifest: {exc}") from exc
        if "owner" in data:
            raise ArticleError("syntax", "a council manifest has no owner")
        if data.get("v") != 1 or cm.name != name or cm.type not in COUNCIL_TYPES:
            raise ArticleError("syntax", "bad council manifest fields")
        if data.get("serial") != seq:
            raise ArticleError("syntax", "a council manifest's serial is its council.seq")
        if not 0 < len(members) <= MAX_MEMBERS or len(set(cm.keys)) != len(members):
            raise ArticleError("syntax", f"a council has 1 to {MAX_MEMBERS} distinct members")
        if (seq == 1) != (prev is None) or (prev is not None and not isinstance(prev, str)):
            raise ArticleError("syntax", "prev is required from seq 2, and only then")
        if seq != 1 and cm.succeeds is not None:
            raise ArticleError("syntax", "succeeds is for the genesis only")
        if cm.min_level < 0 or cm.max_probation < 0 or cm.sponsors < 0:
            raise ArticleError("syntax", "council numbers are not negative")
        return cm

    @classmethod
    def from_article(cls, art: Article) -> "CouncilManifest":
        if art.control != ["manifest"]:
            raise ArticleError("syntax", "not a manifest")
        return cls.from_body(art.group, art.body)


def _int(c: dict, key: str, default: int) -> int:
    v = c.get(key, default)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ValueError(f"{key} is not an integer")
    return v


def is_council_manifest(art: Article) -> bool:
    """A manifest without ``owner`` but with ``council``: read as section 4 says."""
    if art.control != ["manifest"]:
        return False
    try:
        data = parse_canonical_json(art.body)
    except ArticleError:
        return False
    return "council" in data and "owner" not in data


# --- making one -------------------------------------------------------------

def council_body(name: str, gtype: str, *, seq: int, date: datetime, members: list[Member],
                 prev: str | None = None, min_level: int | None = None,
                 max_probation: int | None = None, sponsors: int | None = None,
                 succeeds: dict | None = None, fields: dict | None = None) -> str:
    """The canonical body of a council manifest. ``fields``: the other manifest
    fields of UN-RFC 0004 section 3.1 (``title``, ``posters``, ``min_pow``, ...)."""
    c: dict = {"date": format_expires(date), "members": [m.as_json() for m in members],
               "seq": seq}
    if prev is not None:
        c["prev"] = prev
    if min_level is not None:
        c["min_level"] = min_level
    if max_probation is not None:
        c["max_probation"] = max_probation
    if sponsors is not None:
        c["sponsors"] = sponsors
    if succeeds is not None:
        c["succeeds"] = succeeds
    data = dict(fields or {})
    for k in ("owner", "council", "serial", "name", "type", "v"):
        data.pop(k, None)
    data.update({"v": 1, "name": name, "type": gtype, "serial": seq, "council": c})
    return canonical_json(data)


def next_body(prev: CouncilManifest, *, date: datetime, members: list[Member] | None = None,
              **changes) -> str:
    """The body of the manifest after ``prev``: same fields, ``seq`` + 1, ``prev`` its
    hash, and the given changes (``members``, ``min_level``, other manifest fields)."""
    c = prev.data["council"]
    fields = {k: v for k, v in prev.data.items() if k != "council"}
    for k in list(changes):
        if k not in ("min_level", "max_probation", "sponsors"):
            fields[k] = changes.pop(k)
    return council_body(
        prev.name, prev.type, seq=prev.seq + 1, date=date,
        members=prev.members if members is None else members, prev=prev.hash,
        min_level=changes.get("min_level", c.get("min_level")),
        max_probation=changes.get("max_probation", c.get("max_probation")),
        sponsors=changes.get("sponsors", c.get("sponsors")), fields=fields)


def council_article(member: crypto.Identity, group_id: str, body: str, pow_bits: int = 18,
                    now: datetime | None = None) -> Article:
    """One member's copy of a council manifest (its ``Author-Key`` is the member)."""
    from .article import new_article
    art = new_article(group_id, None, body, now=now,
                      extra=[("Control", "manifest"), ("Content-Type", "application/json")])
    return art.finalize(member, pow_bits)


# --- counting (section 5) ---------------------------------------------------

def change_ok(prev: CouncilManifest, m: CouncilManifest, last_admission: datetime) -> str | None:
    """Section 5, items 2 and 3: why ``m`` may not follow ``prev``, or None."""
    if m.date < prev.date:
        return "date earlier than the previous manifest's"
    old = {x.key: x for x in prev.members}
    new = {x.key: x for x in m.members}
    added = [k for k in new if k not in old]
    removed = [k for k in old if k not in new]
    changed = [k for k in new if k in old and new[k] != old[k]]
    if len(added) + len(removed) + len(changed) > 1:
        return "more than one change of members"
    if added:
        x = new[added[0]]
        if x.full or x.joined != m.date:
            return "an admitted member starts on probation, joined on the manifest's date"
        if m.date < last_admission + ADMISSION_GAP:
            return "less than 30 days since the last admission"
        if len(prev.on_probation) >= prev.max_probation:
            return "as many members on probation as max_probation"
    if changed:
        a, b = old[changed[0]], new[changed[0]]
        if not (not a.full and b.full and a.joined == b.joined):
            return "a member's fields change only by promotion"
        if m.date < a.joined + PROBATION:
            return "promotion less than 180 days after joining"
    if len(m.full) < MIN_FULL:
        return "fewer than 2 full members left"
    return None


def quorum(eligible: int) -> int:
    """Section 5, item 4: the larger of 2 and a majority of ``eligible``."""
    return max(2, eligible // 2 + 1)


@dataclass
class Chain:
    """The counted council manifests of one group, oldest first."""
    group_id: str
    counted: list[CouncilManifest] = field(default_factory=list)
    signers: list[set[bytes]] = field(default_factory=list)   # who made each one count
    disputed: bool = False          # a fork: two bodies counted for one seq
    fork_seq: int | None = None
    last_admission: datetime | None = None   # for the 30 days of section 5, item 2

    @property
    def current(self) -> CouncilManifest | None:
        return self.counted[-1] if self.counted else None


def count_chain(group_id: str, copies: list[tuple[bytes, str]]) -> Chain:
    """Section 5: the chain that ``copies`` - (author key, body) of every council
    manifest article held for ``group_id`` - make count. Copies that are not council
    manifests of this group, or that no rule lets count, are ignored."""
    by_seq: dict[int, dict[str, tuple[CouncilManifest, set[bytes]]]] = {}
    for author, body in copies:
        try:
            m = CouncilManifest.from_body(group_id, body)
        except ArticleError:
            continue
        slot = by_seq.setdefault(m.seq, {}).setdefault(m.body, (m, set()))
        slot[1].add(author)
    chain = Chain(group_id)
    _, fp = split_group_id(group_id)

    genesis = [(m, s) for m, s in by_seq.get(1, {}).values()
               if council_fingerprint(m.body) == fp and _genesis_counts(m, s)]
    if not genesis:
        return chain
    # the fingerprint pins the genesis body, so at most one can match
    chain.counted.append(genesis[0][0])
    chain.signers.append(genesis[0][1] & set(genesis[0][0].keys))
    last_admission = chain.last_admission = genesis[0][0].date

    seq = 2
    while seq in by_seq:
        prev = chain.counted[-1]
        winners = []
        for m, signed in by_seq[seq].values():
            if m.prev != prev.hash or m.type != prev.type or m.name != prev.name:
                continue
            if change_ok(prev, m, last_admission) is not None:
                continue
            eligible = [k for k in prev.full if k in m.keys]
            got = signed & set(eligible)
            if len(got) >= quorum(len(eligible)):
                winners.append((m, got))
        if not winners:
            break
        if len(winners) > 1:
            chain.disputed, chain.fork_seq = True, seq
            break
        m, got = winners[0]
        if any(k not in prev.keys for k in m.keys):
            last_admission = chain.last_admission = m.date
        chain.counted.append(m)
        chain.signers.append(got)
        seq += 1
    return chain


def _genesis_counts(m: CouncilManifest, signed: set[bytes]) -> bool:
    """Section 5: every member posted it, all full, joined on its date, at least 2."""
    return (len(m.members) >= MIN_FULL
            and all(x.full and x.joined == m.date for x in m.members)
            and set(m.keys) <= signed)


def copies_to_keep(chain: Chain, copies: list[tuple[bytes, str, str]]) -> set[str]:
    """Section 6, keeping the chain: the Message-IDs of enough identical copies of every
    counted manifest to make it count again. ``copies``: (author, body, Message-ID)."""
    keep: set[str] = set()
    for m, signers in zip(chain.counted, chain.signers):
        for author, body, mid in copies:
            if author in signers and body.rstrip("\n").rstrip("\r") == m.body:
                keep.add(mid)
    return keep
