"""Council proposals, hearings and objections (UN-RFC 0061).

Belongs here: a proposal's body and id (section 4), objections (section 6), who is an
**active** member (section 2), when a proposal counts (section 4), its hearing and its
outcome (sections 5 and 7), and the next council manifest a passed ``manifest``
proposal makes. Pure functions over the articles a caller read, so that clients
showing a hearing and the replicas deciding it count the same way.

Not here: reading and posting (the replica, ``replica/run.py``; the client,
``client/session/council.py``), the levels of ripened keys (handed in).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import council as cn
from . import crypto
from .encoding import DS, H, b32
from .groups import canonical_json, parse_canonical_json

DS_PROPOSAL = "UNSEENET-PROPOSAL-1"
PROPOSAL = "proposal"
OBJECTION = "objection"
DAYS_DEFAULT, DAYS_MIN, DAYS_MAX = 14, 14, 60
URGENT_DAYS = 3
COUNT_WITHIN = timedelta(days=7)            # section 4: the quorum within 7 days
ACTIVE_WITHIN = timedelta(days=90)          # section 2
GRACE = timedelta(hours=24)                 # section 7: late arrivals
MAX_REASON = 2000
MAX_OBJECTION_REASON = 1000
CHANGE_KINDS = ("manifest", "list", "endorse", "retire", "rfc")
APPLIED_KINDS = ("manifest",)               # what this software can apply yet
# what a ``manifest`` proposal may change: council parameters, ``founding.until``, and
# the manifest's own fields - never the members, which the rules alone change
COUNCIL_PARAMS = ("min_level", "max_probation", "sponsors")
FIXED_FIELDS = ("v", "name", "type", "serial", "council", "owner")


class ProposalProblem(ValueError):
    pass


def proposal_id(body: str) -> str:
    """Section 4: the first 16 characters of b32(H(DS || body))."""
    text = body.rstrip("\n").rstrip("\r")
    return b32(H(DS(DS_PROPOSAL) + text.encode("utf-8")))[:16]


def make_proposal(council: str, seq: int, change: dict, reason: str, *,
                  days: int | None = None, urgent: bool = False) -> tuple[str, str]:
    """(id, body) of a proposal. Checks the form, not whether the change would count."""
    body = canonical_json(_proposal_data(council, seq, change, reason, days, urgent)) + "\n"
    return proposal_id(body), body


def _proposal_data(council, seq, change, reason, days, urgent) -> dict:
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise ProposalProblem("seq is the current council manifest's")
    if not isinstance(change, dict) or len(change) != 1 or next(iter(change)) not in CHANGE_KINDS:
        raise ProposalProblem(f"change is one of {', '.join(CHANGE_KINDS)}")
    if "manifest" in change:
        check_manifest_change(change["manifest"])
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON:
        raise ProposalProblem(f"a reason of 1 to {MAX_REASON} characters")
    data = {"change": change, "council": council, "reason": reason, "seq": seq, "v": 1}
    if days is not None:
        if not isinstance(days, int) or isinstance(days, bool) or not DAYS_MIN <= days <= DAYS_MAX:
            raise ProposalProblem(f"a hearing lasts {DAYS_MIN} to {DAYS_MAX} days")
        data["days"] = days
    if urgent:
        data["urgent"] = True
    return data


def check_manifest_change(m) -> None:
    """A ``manifest`` change: ``{"fields": {...}, "council": {...}}`` - manifest fields to
    set (``title``, ``posters``, the groups of section 3, ...) and council parameters
    (``min_level``, ``max_probation``, ``sponsors``, ``until`` to extend the founding
    period). The members are never in it."""
    if not isinstance(m, dict) or not set(m) <= {"fields", "council"} or not m:
        raise ProposalProblem("a manifest change has fields and/or council")
    fields = m.get("fields", {})
    if not isinstance(fields, dict) or any(k in FIXED_FIELDS for k in fields):
        raise ProposalProblem(f"fields cannot set {', '.join(FIXED_FIELDS)}")
    c = m.get("council", {})
    if not isinstance(c, dict) or not set(c) <= {*COUNCIL_PARAMS, "until"}:
        raise ProposalProblem(f"council can set {', '.join(COUNCIL_PARAMS)} and until")
    for k in COUNCIL_PARAMS:
        if k in c and (not isinstance(c[k], int) or isinstance(c[k], bool) or c[k] < 0):
            raise ProposalProblem(f"{k} is a number of 0 or more")


@dataclass(frozen=True)
class Proposal:
    id: str
    council: str
    seq: int
    change: dict
    reason: str
    days: int
    urgent: bool
    body: str

    @property
    def kind(self) -> str:
        return next(iter(self.change))


def parse_proposal(body: str) -> Proposal:
    try:
        data = parse_canonical_json(body if body.endswith("\n") else body + "\n")
    except ValueError as exc:
        raise ProposalProblem("not canonical JSON") from exc
    if data.get("v") != 1:
        raise ProposalProblem("not a version 1 proposal")
    unknown = set(data) - {"v", "council", "seq", "change", "days", "urgent", "reason"}
    if unknown:
        raise ProposalProblem(f"unknown fields {sorted(unknown)}")
    if data.get("urgent", True) is not True and "urgent" in data:
        raise ProposalProblem("urgent is true or absent")
    _proposal_data(data.get("council"), data.get("seq"), data.get("change"),
                   data.get("reason"), data.get("days"), data.get("urgent", False))
    text = body.rstrip("\n").rstrip("\r")
    return Proposal(proposal_id(text), data["council"], data["seq"], data["change"],
                    data["reason"], data.get("days", DAYS_DEFAULT), bool(data.get("urgent")),
                    text)


def objection_body(proposal: str, reason: str = "", withdrawn: bool = False) -> str:
    if len(reason) > MAX_OBJECTION_REASON:
        raise ProposalProblem(f"a reason of at most {MAX_OBJECTION_REASON} characters")
    data: dict = {"proposal": proposal, "v": 1}
    if reason:
        data["reason"] = reason
    if withdrawn:
        data["withdrawn"] = True
    return canonical_json(data) + "\n"


# --- what was posted ----------------------------------------------------------------------

@dataclass(frozen=True)
class Item:
    """An article in a council's proposals or talk group, as the rules read it."""
    message_id: str
    subject: str
    author: str
    date: datetime
    body: str


def active_members(cur: cn.CouncilManifest, items: list[Item], at: datetime) -> set[str]:
    """Section 2: the full members that posted in the proposals or talk group in the
    90 days before ``at``."""
    full = {crypto.key_to_text(k) for k in cur.full}
    return {i.author for i in items if i.author in full and at - ACTIVE_WITHIN <= i.date <= at}


@dataclass
class Hearing:
    proposal: Proposal
    first: datetime                     # the first copy's Date
    counted: datetime                   # the Date of the copy that made it count
    signers: list[str]
    active: int                         # F: active members when the hearing began
    ends: datetime                      # without extension
    objections: dict[str, str] = field(default_factory=dict)   # objector -> reason

    @property
    def days(self) -> int:
        return URGENT_DAYS if self.proposal.urgent else self.proposal.days


def quorum(active: int) -> int:
    """Section 4: the larger of 2 and a majority of the active members."""
    return max(2, active // 2 + 1)


def hearings(chain: cn.Chain, proposals: list[Item], talk: list[Item]) -> list[Hearing]:
    """Every proposal for the council of ``chain`` that counts (section 4): within 7
    days of its first copy, at least ``quorum`` active members posted exactly that body,
    and its ``seq`` was the current manifest's when it counted - the next manifest is
    dated later. An urgent proposal needs two thirds of the active members."""
    cur = chain.current
    if cur is None:
        return []
    group_id = chain.group_id
    everything = proposals + talk
    copies: dict[str, list[Item]] = {}
    for i in proposals:
        if i.subject.startswith(PROPOSAL + " "):
            copies.setdefault(i.body.rstrip("\n").rstrip("\r"), []).append(i)
    out = []
    for body, items in copies.items():
        try:
            p = parse_proposal(body)
        except ProposalProblem:
            continue
        if p.council != group_id or any(i.subject != f"{PROPOSAL} {p.id}" for i in items):
            continue
        items = sorted(items, key=lambda i: (i.date, i.message_id))
        first = items[0].date
        active = active_members(cur, everything, first)
        need = quorum(len(active))
        if p.urgent:
            need = max(need, -(-2 * len(active) // 3))
        seen: list[str] = []
        for i in items:
            if i.date > first + COUNT_WITHIN or i.author not in active or i.author in seen:
                continue
            seen.append(i.author)
            if len(seen) >= need:
                if not _current_then(chain, p.seq, i.date):
                    break
                began = active_members(cur, everything, i.date)      # F (section 7)
                h = Hearing(p, first, i.date, list(seen), len(began),
                            i.date + timedelta(days=URGENT_DAYS if p.urgent else p.days))
                out.append(h)
                break
    return sorted(out, key=lambda h: (h.counted, h.proposal.id))


def _current_then(chain: cn.Chain, seq: int, when: datetime) -> bool:
    """Whether manifest ``seq`` counted and was still current at ``when``."""
    if not 1 <= seq <= len(chain.counted):
        return False
    return seq == len(chain.counted) or chain.counted[seq].date > when


def count_objections(h: Hearing, objections: list[Item], level: dict[str, int | None],
                     min_level: int, until: datetime) -> dict[str, str]:
    """Section 6: the keys whose objection counts - dated within the hearing (up to
    ``until``), the key ripened to ``min_level``, the newest one by that key not
    withdrawn. Returns objector -> reason."""
    newest: dict[str, tuple[datetime, str, dict]] = {}
    for i in objections:
        if i.subject != f"{OBJECTION} {h.proposal.id}" or not h.counted <= i.date <= until:
            continue
        try:
            data = parse_canonical_json(i.body if i.body.endswith("\n") else i.body + "\n")
        except ValueError:
            continue
        if data.get("v") != 1 or data.get("proposal") != h.proposal.id:
            continue
        if i.author not in newest or (i.date, i.message_id) > newest[i.author][:2]:
            newest[i.author] = (i.date, i.message_id, data)
    out = {}
    for key, (_, _, data) in newest.items():
        if data.get("withdrawn") is True or (level.get(key) or -1) < min_level:
            continue
        out[key] = str(data.get("reason", ""))[:MAX_OBJECTION_REASON]
    return out


@dataclass(frozen=True)
class Outcome:
    state: str                   # "open", "extended", "passed", "failed"
    objections: int              # O
    active: int                  # F
    closes: datetime             # when the (possibly extended) hearing ends
    applies: datetime | None     # 00:00 UTC of the day it applies, when passed


def outcome(h: Hearing, objections: list[Item], level: dict[str, int | None],
            min_level: int, now: datetime) -> Outcome:
    """Section 7: after the hearing and 24 hours for late arrivals, more objections
    than active members fail it; more than half extend it once (urgent ones never);
    otherwise it passes, applied 00:00 UTC of the day after the hearing ended."""
    f = h.active
    first_end = h.ends
    if now < first_end + GRACE:
        o = len(count_objections(h, objections, level, min_level, first_end))
        return Outcome("open", o, f, first_end, None)
    o = len(count_objections(h, objections, level, min_level, first_end))
    if o > f:
        return Outcome("failed", o, f, first_end, None)
    if o * 2 > f and not h.proposal.urgent:
        second_end = first_end + timedelta(days=h.days)
        o2 = len(count_objections(h, objections, level, min_level, second_end))
        if now < second_end + GRACE:
            return Outcome("extended", o2, f, second_end, None)
        if o2 > f:
            return Outcome("failed", o2, f, second_end, None)
        return Outcome("passed", o2, f, second_end, _day(second_end) + timedelta(days=1))
    return Outcome("passed", o, f, first_end, _day(first_end) + timedelta(days=1))


def _day(t: datetime) -> datetime:
    return t.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def applied_body(cur: cn.CouncilManifest, p: Proposal, date: datetime) -> str:
    """The council manifest a passed ``manifest`` proposal makes after ``cur``, dated
    ``date``: the same members, with the proposed fields and parameters."""
    m = p.change["manifest"]
    changes = dict(m.get("fields", {}))
    c = m.get("council", {})
    for k in COUNCIL_PARAMS:
        if k in c:
            changes[k] = c[k]
    founding = None
    if "until" in c:
        if cur.founding is None:
            raise ProposalProblem("this council has no founding period to extend")
        from .groups import parse_expires
        f = cur.founding
        founding = cn.Founding(f.founder, parse_expires(c["until"]), f.size, f.max_probation,
                               f.renounced)
    return cn.next_body(cur, date=max(date, cur.date), founding=founding, **changes)
