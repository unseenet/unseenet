"""The rules every replica computes the same way (UN-RFC 0054 sections 9-13, 19, 20).

Belongs here: the outcome of a decision and its hash, shadow reports, when a shadow is
eligible, and the one next council manifest - a removal, a promotion, an admission, a
founder admission or a renunciation - with its date taken from the articles, never from
when a replica noticed. Pure functions: ``run.py`` reads the groups and hands in what
it read, so that every replica, given the same articles, computes the same body.

Not here: reading and posting (``run.py``), deciding a claim (``registrar.Registrar``),
counting the chain (``core.council``).

Two points the RFC leaves to the implementation, chosen so that the result depends on
public articles alone:

- **Which day a decision belongs to** is the UTC day of its commit's ``Date``. A day is
  *settled* when every commit of it has been revealed or has lapsed - 7 days and an
  hour after it ends - so a shadow posts its report for day *D* on day *D* + 8
  (``REPORT_LAG``), and only such a report counts for *D*. A report posted later is
  not counted, so nobody can fill in the past.
- **The 60 days of section 11** are the 60 settled days before the day being judged:
  on day *E*, the days *E* - 68 to *E* - 9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .. import names as nm
from ..core import council as cn
from ..core import crypto
from ..core.groups import canonical_json, parse_canonical_json

DAY = timedelta(days=1)
REPORT_LAG = 8                   # days: a report for day D is posted on day D + 8
WINDOW = 60                      # section 11, item 2: ...
NEED = 55                        # ... a report on at least 55 of the last 60 days
FOUNDER_SHADOW = 7               # section 19, item 3: a shadow on each of the last 7 days
SILENT = timedelta(days=90)      # section 12, item 3
LOSSES = 3                       # section 12, item 2: at least 3 ...
LOSS_WINDOW = timedelta(days=30)  # ... in 30 days ...
CONVERGE = timedelta(hours=48)   # ... not signed the winner within 48 hours
SPONSOR_WINDOW = timedelta(days=180)   # section 11.1

# subjects (sections 9, 10, 11.1, 13.1, 19, 20)
ALIVE = "alive"
SHADOW = "shadow"
SPONSOR = "sponsor"
UNSPONSOR = "unsponsor"
OBJECT = "object"
ADMIT = "admit"
RENOUNCE = "renounce"
RESIGN = "resign"


def day_of(t: datetime) -> datetime:
    """00:00 UTC of ``t``'s day."""
    return t.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def day_text(d: datetime) -> str:
    return f"{d:%Y-%m-%d}"


# --- decisions and their outcome hash (section 10) ------------------------------------

def outcome(issue: tuple[str, str, int, datetime] | None = None, revoke: int | None = None) -> dict:
    """The outcome of a decision as section 10 hashes it: an issue (name, key, serial,
    expires), a revocation, or a refusal - whose reason is left out."""
    if issue is not None:
        name, key, serial, expires = issue
        return {"issue": [name, key, serial, nm.rfc3339(expires)]}
    if revoke is not None:
        return {"revoke": revoke}
    return {"refuse": True}


@dataclass(frozen=True)
class Decision:
    commit: str                  # the commit's Message-ID
    day: datetime                # 00:00 UTC of the commit's Date
    hash: str                    # outcome hash (section 10)
    dns: bool                    # depends on DNS: it concerns a domain name

    def as_json(self) -> list:
        return [self.commit, day_text(self.day), self.hash, self.dns]

    @classmethod
    def from_json(cls, x: list) -> "Decision":
        return cls(x[0], datetime.strptime(x[1], "%Y-%m-%d").replace(tzinfo=timezone.utc),
                   x[2], bool(x[3]))


# --- shadow reports (section 10) ------------------------------------------------------------

def report_subject(day: datetime) -> str:
    return f"{SHADOW} {day_text(day)}"


def report_body(day: datetime, decisions: list[Decision]) -> str:
    """The report for ``day``: the decisions on that day's commits, in the order of
    section 8 (the caller's order)."""
    return canonical_json({"date": nm.rfc3339(day),
                           "decisions": [[d.commit, d.hash] for d in decisions if d.day == day],
                           "v": 1}) + "\n"


@dataclass
class Report:
    author: str
    day: datetime
    posted: datetime
    decisions: dict[str, str]    # commit Message-ID -> outcome hash


def parse_report(p: nm.Post) -> Report | None:
    """A shadow report, or None. It counts only for its own day, and only if it was
    posted on the day it was due (``REPORT_LAG``)."""
    if not p.subject.startswith(SHADOW + " "):
        return None
    try:
        data = parse_canonical_json(p.body if p.body.endswith("\n") else p.body + "\n")
        day = nm.parse_rfc3339(data["date"])
        items = data["decisions"]
        if data.get("v") != 1 or day != day_of(day) or not isinstance(items, list):
            return None
        decisions = {}
        for x in items:
            if not (isinstance(x, list) and len(x) == 2 and all(isinstance(v, str) for v in x)):
                return None
            decisions[x[0]] = x[1]
    except (ValueError, KeyError, TypeError):
        return None
    if day_of(p.date) != day + REPORT_LAG * DAY:
        return None
    return Report(p.author, day, p.date, decisions)


def reports_by_key(posts: list[nm.Post]) -> dict[str, dict[datetime, Report]]:
    """Every counting report, per shadow key and covered day (the first one posted)."""
    out: dict[str, dict[datetime, Report]] = {}
    for p in sorted(posts, key=lambda p: (p.date, p.message_id)):
        r = parse_report(p)
        if r is not None:
            out.setdefault(r.author, {}).setdefault(r.day, r)
    return out


def day_agrees(report: Report | None, mine: list[Decision]) -> bool | None:
    """Section 11, items 3 and 4 for one day: None if there is no report; False if it
    leaves out a claim that was handled that day, or disagrees on a decision that does
    not depend on DNS; True otherwise."""
    if report is None:
        return None
    for d in mine:
        theirs = report.decisions.get(d.commit)
        if theirs is None or (not d.dns and theirs != d.hash):
            return False
    return True


def window(e: datetime, days: int = WINDOW) -> list[datetime]:
    """The settled days judged on day ``e``: the ``days`` days before ``e`` - 8."""
    last = e - (REPORT_LAG + 1) * DAY
    return [last - i * DAY for i in range(days)]


@dataclass
class Judge:
    """Judges shadows against this replica's own decisions. ``known_from``: the first
    day this replica has decisions for; a day before it cannot be judged, and a shadow
    is then not eligible on this replica's word (it waits for days it can judge)."""
    decisions: list[Decision]
    reports: dict[str, dict[datetime, Report]]
    known_from: datetime

    def __post_init__(self):
        self.by_day: dict[datetime, list[Decision]] = {}
        for d in self.decisions:
            self.by_day.setdefault(d.day, []).append(d)

    def first_report(self, key: str) -> datetime | None:
        days = self.reports.get(key)
        return min(days) if days else None

    def ran(self, key: str, e: datetime, days: int, need: int) -> bool:
        """At least ``need`` of the ``days`` settled days before ``e`` reported, none of
        them disagreeing, and every day judged known here."""
        w = window(e, days)
        if w[-1] < self.known_from:
            return False
        got = 0
        reports = self.reports.get(key, {})
        for d in w:
            agrees = day_agrees(reports.get(d), self.by_day.get(d, []))
            if agrees is False:
                return False
            got += agrees is True
        return got >= need

    def eligible_since(self, key: str, today: datetime, days: int = WINDOW,
                       need: int = NEED) -> datetime | None:
        """The first day up to ``today`` on which the shadow met items 2 to 4 and has
        gone on meeting them, or None."""
        first = self.first_report(key)
        if first is None:
            return None
        since = None
        e = first + (REPORT_LAG + 1) * DAY + (need - 1) * DAY
        while e <= today:
            if self.ran(key, e, days, need):
                since = since or e
            else:
                since = None
            e += DAY
        return since


# --- removal (section 12) ---------------------------------------------------------------------

@dataclass(frozen=True)
class Cert:
    """A certificate as posted: who signed it and when it was posted (its article's Date)."""
    cert: nm.Certificate
    posted: datetime


SURE_AFTER = nm.REVEAL_WITHIN + nm.LAPSE_SETTLE + DAY   # a commit not seen by then never counted


def unexplained(cert: Cert, decisions: dict[str, tuple[str, bool]], genesis: datetime,
                now: datetime | None = None) -> bool:
    """Section 12, item 1: a certificate no counting claim explains, leaving DNS aside.
    ``decisions``: commit Message-ID -> (the issue outcome this replica computed, as JSON
    text, or "" if it gave no certificate; depends on DNS or is otherwise this replica's
    own - a commit it saw late). Certificates issued before
    the council's genesis are its re-issues (section 14, step 2) and renewals of domain
    names have no claim: both are left out."""
    c = cert.cert
    if c.claim is None or c.issued < genesis or c.kind == "domain":
        return False
    mine = decisions.get(c.claim)
    if mine is None:
        # not a counting commit - unless this replica has not got to it yet (its node
        # may lag): judged only once the commit would surely have been handled
        return now is None or c.claimed is None or now - c.claimed > SURE_AFTER
    issued, dns = mine
    if dns:
        return False
    want = canonical_json(outcome((c.name, c.key, c.serial, c.expires)))
    return issued != want or c.issued != c.claimed


def lost_alone(member: str, certs: list[Cert]) -> list[datetime]:
    """Section 12, item 2: when each of ``member``'s certificates on decisions that
    depend on DNS lost (UN-RFC 0019 section 5.3) and ``member`` had not signed the
    winning decision 48 hours later - the time 48 hours after it lost, oldest first."""
    out = []
    by_slot: dict[tuple[str, int], list[Cert]] = {}
    for x in certs:
        by_slot.setdefault((x.cert.name, x.cert.serial), []).append(x)
    for slot, xs in by_slot.items():
        winner, disputed = nm.current([x.cert for x in xs])
        if winner is None or disputed:
            continue
        mine = [x for x in xs if x.cert.registrar == member and x.cert.kind == "domain"
                and x.cert.decision != winner.decision]
        if not mine:
            continue
        won_at = min(x.posted for x in xs if x.cert.decision == winner.decision)
        lost_at = max(won_at, min(x.posted for x in mine))
        signed = [x.posted for x in xs if x.cert.registrar == member
                  and x.cert.decision == winner.decision]
        if not signed or min(signed) > lost_at + CONVERGE:
            out.append(lost_at + CONVERGE)
    return sorted(out)


def removal_reason(member: bytes, cur: cn.CouncilManifest, *, certs: list[Cert],
                   decisions: dict[str, tuple[str, bool]], genesis: datetime,
                   last_post: dict[str, datetime], resigned: dict[str, datetime],
                   now: datetime | None = None) -> tuple[datetime, str] | None:
    """The earliest reason section 12 gives to remove ``member``, as (the moment it
    arose, why), or None. ``last_post``: each key's last article in the registrar's
    group; ``resigned``: each key's first ``resign`` article there (section 20)."""
    key = crypto.key_to_text(member)
    found: list[tuple[datetime, str]] = []
    for x in certs:
        if x.cert.registrar == key and unexplained(x, decisions, genesis, now):
            found.append((x.posted, f"signed a certificate no claim explains ({x.cert.name}, "
                                    f"serial {x.cert.serial})"))
    losses = lost_alone(key, certs)
    for i in range(LOSSES - 1, len(losses)):
        if losses[i] - losses[i - LOSSES + 1] <= LOSS_WINDOW:
            found.append((losses[i], "lost alone on decisions that depend on DNS 3 times in 30 days"))
            break
    joined = cur.member(member).joined
    last = max(last_post.get(key, joined), joined)
    found.append((last + SILENT, "silent for 90 days"))
    if key in resigned:
        found.append((resigned[key], "stepped down"))
    return min(found) if found else None


# --- the next council manifest (sections 11, 12, 19) --------------------------------------------

@dataclass
class Change:
    kind: str                    # "removal", "promotion", "admission", "renunciation"
    key: str | None              # the member or newcomer; None for a renunciation
    date: datetime
    body: str
    why: str
    by_founder: bool = False

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.key or '-'}"


@dataclass
class World:
    """Everything public a replica read, for computing the next manifest."""
    chain: cn.Chain
    judge: Judge
    certs: list[Cert]
    decisions: dict[str, tuple[str, bool]]
    last_post: dict[str, datetime]
    resigned: dict[str, datetime]
    level: dict[str, int | None]                       # ripening level of each key
    sponsors: dict[str, set[str]] = field(default_factory=dict)   # shadow -> sponsoring members
    admits: list[tuple[datetime, str]] = field(default_factory=list)  # founder's ``admit``
    renounced: datetime | None = None                   # founder's ``renounce``
    now: datetime | None = None                         # when the replica looks


def next_change(w: World, today: datetime) -> Change | None:
    """The one manifest that should follow the current one now, or None. Removals
    first, then promotions, then admissions by section 11, then founder admissions
    (section 19), then a renunciation. Its date is never before the current
    manifest's, and never after ``today``."""
    cur = w.chain.current
    if cur is None or w.chain.disputed:
        return None
    genesis = w.chain.counted[0].date
    later = lambda t: max(day_of(t), cur.date)          # noqa: E731

    # removals: the reason that arose first
    reasons = []
    for m in cur.members:
        r = removal_reason(m.key, cur, certs=w.certs, decisions=w.decisions, genesis=genesis,
                           last_post=w.last_post, resigned=w.resigned, now=w.now)
        if r is not None and later(r[0]) <= today:
            reasons.append((r[0], crypto.key_to_text(m.key), r[1], m.key))
    for when, key, why, pk in sorted(reasons):
        members = [x for x in cur.members if x.key != pk]
        d = later(when)
        body = cn.next_body(cur, date=d, members=members)
        if _counts(cur, body, w):
            return Change("removal", key, d, body, why)

    # promotions
    for m in sorted(cur.members, key=lambda x: (x.joined, x.key)):
        if m.full:
            continue
        d = later(m.joined + (cn.FOUNDER_PROBATION if m.by == cn.FOUNDER else cn.PROBATION))
        if d > today:
            continue
        members = [cn.Member(x.key, x.joined, True, x.by) if x.key == m.key else x
                   for x in cur.members]
        body = cn.next_body(cur, date=d, members=members)
        if _counts(cur, body, w):
            return Change("promotion", crypto.key_to_text(m.key), d, body, "probation is over")

    last_adm = w.chain.last_admission or genesis
    members_now = {crypto.key_to_text(k) for k in cur.keys}

    # admissions by section 11: the eligible shadow whose first report is the oldest
    if len(cur.on_probation) < cur.max_probation and len(cur.members) < cn.MAX_MEMBERS:
        queue = []
        for key in w.judge.reports:
            if key in members_now or (w.level.get(key) or -1) < cur.min_level:
                continue
            if cur.sponsors and len(w.sponsors.get(key, set()) & _full(cur)) < cur.sponsors:
                continue
            since = w.judge.eligible_since(key, today)
            if since is not None:
                queue.append((w.judge.first_report(key), key, since))
        for _, key, since in sorted(queue):
            d = later(max(since, last_adm + cn.ADMISSION_GAP))
            if d > today:
                continue
            ch = _admit(cur, w, key, d, by=None)
            if ch is not None:
                return ch

    # founder admissions (section 19)
    f = cur.founding
    if f is not None and not f.renounced:
        for asked, key in sorted(w.admits):
            if key in members_now or (w.level.get(key) or -1) < cur.min_level:
                continue
            if len(cur.on_probation) >= f.max_probation or len(cur.members) >= cn.MAX_MEMBERS:
                break
            ran = _ran_founder(w.judge, key, today)
            if ran is None:
                continue
            d = later(max(day_of(asked), ran, last_adm + cn.FOUNDER_GAP))
            if d > today or not cur.founding_lasts(d):
                continue
            ch = _admit(cur, w, key, d, by=cn.FOUNDER)
            if ch is not None:
                return ch

        # renouncing
        if w.renounced is not None:
            d = later(w.renounced)
            if d <= today:
                body = cn.next_body(cur, date=d, founding=cn.Founding(
                    f.founder, f.until, f.size, f.max_probation, True))
                if _counts(cur, body, w):
                    return Change("renunciation", None, d, body, "the founder renounced")
    return None


def _full(cur: cn.CouncilManifest) -> set[str]:
    return {crypto.key_to_text(k) for k in cur.full}


def _admit(cur, w: World, key: str, d: datetime, by: str | None) -> Change | None:
    members = [*cur.members, cn.Member(crypto.key_from_text(key), d, False, by)]
    body = cn.next_body(cur, date=d, members=members)
    if not _counts(cur, body, w):
        return None
    why = ("the founder asked, and it ran as a shadow for 7 days" if by
           else "it ran as a shadow, agreeing with the council, for 60 days")
    return Change("admission", key, d, body, why, by_founder=bool(by))


def _ran_founder(judge: Judge, key: str, today: datetime) -> datetime | None:
    """Section 19, item 3: the first day up to ``today`` from which the shadow had
    reported, agreeing, on each of the last 7 settled days."""
    return judge.eligible_since(key, today, FOUNDER_SHADOW, FOUNDER_SHADOW)


def _counts(cur: cn.CouncilManifest, body: str, w: World) -> bool:
    """Whether the body would count after ``cur`` (section 5, items 2 and 3)."""
    try:
        m = cn.CouncilManifest.from_body(cur.group_id, body)
    except Exception:  # noqa: BLE001 - a body that does not parse does not count
        return False
    return cn.change_ok(cur, m, w.chain.last_admission or w.chain.counted[0].date) is None


def same_change(other: cn.CouncilManifest, body: str, group_id: str) -> str:
    """The body of the same change in a council kept in step with the registrar's (the
    claims group of section 8, the room of section 21): ``other``'s next manifest with
    the members, date and founding of ``body``, a manifest of ``group_id``."""
    m = cn.CouncilManifest.from_body(group_id, body)
    return cn.next_body(other, date=m.date, members=m.members, founding=m.founding)


# --- sponsors (section 11.1) ----------------------------------------------------------------------

def sponsorships(posts: list[nm.Post], members: set[str], full: set[str]) -> dict[str, set[str]]:
    """Shadow key -> the full members whose sponsorship counts: not withdrawn, and the
    only one that member posted in the last 180 days for a shadow not yet a member."""
    last: dict[tuple[str, str], tuple[datetime, bool]] = {}
    for p in sorted(posts, key=lambda p: (p.date, p.message_id)):
        for verb, on in ((SPONSOR, True), (UNSPONSOR, False)):
            if p.subject.startswith(verb + " ") and p.author in full:
                last[(p.author, p.subject[len(verb) + 1:].strip())] = (p.date, on)
    out: dict[str, set[str]] = {}
    newest = max((t for t, _ in last.values()), default=None)
    for (member, shadow), (t, on) in last.items():
        if not on or shadow in members:
            continue
        others = [s for (m, s), (t2, on2) in last.items() if m == member and s != shadow
                  and s not in members and newest and t2 > newest - SPONSOR_WINDOW]
        if not others:
            out.setdefault(shadow, set()).add(member)
    return out


def objections(posts: list[nm.Post]) -> list[tuple[str, str, datetime, str]]:
    """Section 13.1: (who objects, to which key, when, why), oldest first."""
    out = []
    for p in sorted(posts, key=lambda p: (p.date, p.message_id)):
        if p.subject.startswith(OBJECT + " "):
            out.append((p.author, p.subject[len(OBJECT) + 1:].strip(), p.date, p.body.strip()[:2000]))
    return out
