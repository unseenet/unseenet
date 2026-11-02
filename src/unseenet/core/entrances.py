"""Web entrances on a list council's entrance list (UN-RFC 0020 sections 5.1 and 6.3,
UN-RFC 0043 sections 4.3, 7.2 and 8.1).

An entrance announces itself in the council's entrance announcement group, signed
with the entrance's key, naming the publisher whose web client it serves (a releases
channel, UN-RFC 0062). Each day a replica fetches the entrance's information over Tor
- which names the same key - and every file of the version it serves, and checks them
against that publisher's signed release post. The report says which signed version
each entrance served unchanged (``served``).

An entrance comes on the list after ``entrance_days`` good days in a row, a good day
being one on which a replica found it serving a signed release no older than the
publisher's newest that has been out for ``release_days``. It leaves as a node does,
after ``grace_days`` with no good day, or by a decision of the council.

Belongs here: the announcement body, reading release posts, the rules. Pure, over
what a caller read. Not here: fetching over Tor and posting (``replica/entrances.py``)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import lists as ls
from .groups import canonical_json, parse_canonical_json, split_group_id

SUBJECT_PREFIX = "entrance "
MAX_ENTRANCES = 200                       # UN-RFC 0043 section 8.1
MAX_NAME = 64
MAX_CONTACT = 120
MAX_DESCRIPTION = 200
MAX_OPERATOR = 100
STALE = timedelta(days=30)                # UN-RFC 0020 section 5.1
URL = re.compile(r"^https://[a-z0-9.-]+(:\d{1,5})?/$")
ONION = re.compile(r"^[a-z2-7]{56}\.onion$")
RELEASE_FIRST = re.compile(r"^Unseenet web client (\S+)\s*$")
RELEASE_LINE = re.compile(r"^([0-9a-f]{64}) [ *]?(\S+)$")
MAX_FILES = 2000


class EntranceProblem(ValueError):
    pass


# --- announcements (section 5.1) -------------------------------------------------------

@dataclass(frozen=True)
class Entrance:
    key: str                              # the entrance's key: the article's Author-Key
    publisher: str                        # the releases channel whose client it serves
    date: datetime
    url: str | None = None
    onion: str | None = None
    name: str | None = None
    operator: str | None = None
    contact: str | None = None
    description: str | None = None
    message_id: str = ""

    def stale(self, now: datetime) -> bool:
        return now - self.date > STALE

    def base(self) -> str:
        """Where a replica reaches it over Tor: its onion if it has one."""
        return f"http://{self.onion}/" if self.onion else str(self.url)

    def entry(self) -> dict:
        """Its entry on the entrance list (UN-RFC 0043 section 8.1), with its key and
        publisher, which clients that do not know them ignore."""
        e: dict = {"key": self.key, "publisher": self.publisher}
        for k in ("url", "onion", "name", "operator", "contact", "description"):
            v = getattr(self, k)
            if v:
                e[k] = v
        return e


def _rfc3339(when: datetime) -> str:
    return when.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(d: dict, k: str, limit: int) -> str | None:
    v = d.get(k)
    if v is None:
        return None
    if not isinstance(v, str) or len(v) > limit or "\n" in v:
        raise EntranceProblem(f"{k}: at most {limit} characters on one line")
    return v or None


def make_body(publisher: str, date: datetime, *, url: str | None = None,
              onion: str | None = None, name: str | None = None, operator: str | None = None,
              contact: str | None = None, description: str | None = None) -> str:
    """The canonical JSON of an entrance's announcement."""
    d: dict = {"v": 1, "publisher": publisher, "date": _rfc3339(date)}
    for k, v in (("url", url), ("onion", onion), ("name", name), ("operator", operator),
                 ("contact", contact), ("description", description)):
        if v:
            d[k] = v
    body = canonical_json(d) + "\n"
    parse(body, key="ed25519:" + "a" * 52, date=date.replace(microsecond=0))
    return body


def subject(name: str) -> str:
    return SUBJECT_PREFIX + name[:MAX_NAME]


def parse(body: str, *, key: str, date: datetime, message_id: str = "") -> Entrance:
    """An entrance's announcement from its article: body, ``Author-Key`` and ``Date``."""
    try:
        d = parse_canonical_json(body if body.endswith("\n") else body + "\n")
    except ValueError as exc:
        raise EntranceProblem("not canonical JSON") from exc
    if not isinstance(d, dict) or d.get("v") != 1:
        raise EntranceProblem("not a version 1 entrance announcement")
    if set(d) - {"v", "publisher", "date", "url", "onion", "name", "operator", "contact",
                 "description"}:
        raise EntranceProblem("unknown fields in an entrance announcement")
    try:
        split_group_id(d.get("publisher") or "")
    except (ValueError, TypeError) as exc:
        raise EntranceProblem("publisher is the releases channel it serves") from exc
    try:
        said = datetime.strptime(str(d.get("date")), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError as exc:
        raise EntranceProblem("no date") from exc
    if abs(said - date) > timedelta(minutes=1):
        raise EntranceProblem("its date is not the article's Date")
    url, onion = d.get("url"), d.get("onion")
    if url is not None and not (isinstance(url, str) and URL.match(url)):
        raise EntranceProblem("url is https://host/")
    if onion is not None and not (isinstance(onion, str) and ONION.match(onion)):
        raise EntranceProblem("onion is <56 base32>.onion")
    if not (url or onion):
        raise EntranceProblem("an entrance has a url, an onion or both")
    return Entrance(key, d["publisher"], date, url, onion, _text(d, "name", MAX_NAME),
                    _text(d, "operator", MAX_OPERATOR), _text(d, "contact", MAX_CONTACT),
                    _text(d, "description", MAX_DESCRIPTION), message_id)


def newest(entrances, now: datetime) -> dict[str, Entrance]:
    """The newest announcement per entrance key that is not stale."""
    out: dict[str, Entrance] = {}
    for e in entrances:
        if e.stale(now):
            continue
        o = out.get(e.key)
        if o is None or (e.date, e.message_id) > (o.date, o.message_id):
            out[e.key] = e
    return out


def info_names(info, key: str) -> bool:
    """Whether an entrance's ``/.well-known/unseenet-entrance`` (UN-RFC 0043 section
    4.3) names the key it announced with."""
    return isinstance(info, dict) and info.get("key") == key


# --- signed releases (UN-RFC 0043 section 7.2) -----------------------------------------

@dataclass(frozen=True)
class Release:
    version: str
    files: dict[str, str]                 # path -> sha256
    date: datetime                        # when it first appeared in the channel


def parse_release(body: str) -> tuple[str, dict[str, str]] | None:
    """(version, {path: sha256}) of a release post, or None. A zip and paths that
    leave the root are not files an entrance serves."""
    lines = body.splitlines()
    m = RELEASE_FIRST.match(lines[0] if lines else "")
    if not m or ls.version_key(m.group(1)) is None:
        return None
    files = {}
    for line in lines[1:]:
        h = RELEASE_LINE.match(line)
        if h and not h.group(2).endswith(".zip") and ".." not in h.group(2) \
                and not h.group(2).startswith("/"):
            files[h.group(2)] = h.group(1)
            if len(files) > MAX_FILES:
                return None
    return (m.group(1), files) if files else None


def releases(posts) -> dict[str, Release]:
    """The releases of one channel from its posts, ``(body, Date)``, which the caller
    has checked are signed by the channel's owner or a poster it lists. A version
    posted twice keeps its first post."""
    out: dict[str, Release] = {}
    for body, when in sorted(posts, key=lambda p: p[1]):
        got = parse_release(body)
        if got is not None and got[0] not in out:
            out[got[0]] = Release(got[0], got[1], when)
    return out


def due_version(rels: dict[str, Release], day: date, release_days: int) -> str | None:
    """The oldest version an entrance may serve on ``day``: the publisher's newest
    that has been out for ``release_days`` by the end of the day."""
    cut = ls._end(day) - timedelta(days=release_days)
    out = [r.version for r in rels.values() if r.date <= cut]
    return max(out, key=ls.version_key) if out else None


def good(measurements: ls.Measurements, d: date, key: str, rels: dict[str, Release],
         release_days: int) -> bool:
    """A good day: a replica found it serving a signed release, unchanged, no older
    than the one due."""
    due = due_version(rels, d, release_days)
    for v in measurements.served(d, key):
        if v in rels and (due is None or ls.version_key(v) >= ls.version_key(due)):
            return True
    return False


# --- the entrance list (section 6.3) ---------------------------------------------------

def _same_place(a: dict, b: dict) -> bool:
    return bool((a.get("url") and a.get("url") == b.get("url"))
                or (a.get("onion") and a.get("onion") == b.get("onion")))


def imported_entrances(body: str) -> list[dict]:
    """The entries of an import's entrance list (UN-RFC 0043 section 8.1)."""
    try:
        d = parse_canonical_json(body)
        items = d["entrances"]["entrances"]
    except Exception:
        return []
    return [e for e in items if isinstance(e, dict) and (
        (isinstance(e.get("url"), str) and URL.match(e["url"]))
        or (isinstance(e.get("onion"), str) and ONION.match(e["onion"])))]


@dataclass
class Inputs:
    """What the rules read besides the reports."""
    announcements: list = field(default_factory=list)          # Entrance
    releases: dict = field(default_factory=dict)               # publisher -> {version: Release}
    previous: set = field(default_factory=set)                 # keys on the list the day before
    imported: list = field(default_factory=list)               # entries of the import
    genesis: date | None = None                                # when the list began


def entrance_list(*, day: date, seq: int, inputs: Inputs, measurements: ls.Measurements,
                  council: ls.ListCouncil, decisions: ls.DecisionState | None = None
                  ) -> tuple[str, dict[str, ls.Verdict]]:
    """The entrance list for the completed UTC day ``day`` and why each entrance is on
    it or not: (body, {key: verdict})."""
    st = decisions or ls.DecisionState()
    p = st.params
    end = ls._end(day)
    current: dict[str, Entrance] = {}
    for e in inputs.announcements:
        if e.date >= end or end - e.date > timedelta(days=p["announce_days"]):
            continue
        o = current.get(e.key)
        if o is None or (e.date, e.message_id) > (o.date, o.message_id):
            current[e.key] = e
    window = ls._days(day, p["entrance_days"])
    grace = ls._days(day, p["grace_days"])
    verdicts: dict[str, ls.Verdict] = {}
    entries: dict[str, dict] = {}

    def no(key, why):
        verdicts[key] = ls.Verdict(key, False, why)

    for key, e in sorted(current.items()):
        if key in st.removed["entrances"]:
            no(key, "removed by a decision of the council")
            continue
        if council.publishers and e.publisher not in council.publishers:
            no(key, "its publisher is not one the council names")
            continue
        rels = inputs.releases.get(e.publisher) or {}
        if not rels:
            no(key, "its publisher has no signed release of the web client")
            continue
        last = next((d for d in window if measurements.reached(d, key)), None)
        soft = measurements.software(last, key) if last else None
        if ls.below_minimum(soft, council.min_software):
            no(key, f"its software ({soft}) is below the council's minimum")
            continue

        def ok(d, key=key, rels=rels):
            return good(measurements, d, key, rels, p["release_days"])

        if key in inputs.previous:
            if all(measurements.reported(d, key) and not ok(d) for d in grace):
                no(key, f"no replica found it serving a current signed release for "
                        f"{p['grace_days']} days")
                continue
            why = "listed, and not down"
        else:
            n = sum(ok(d) for d in window)
            if n < len(window):
                no(key, f"served a current signed release on {n} of the last "
                        f"{len(window)} days; all are needed")
                continue
            why = f"served a current signed release on each of the last {len(window)} days"
        entries[key] = e.entry()
        verdicts[key] = ls.Verdict(key, True, why)

    order = sorted(entries, key=lambda k: (k not in inputs.previous, k))
    kept, per_op = [], {}
    for k in order:
        op = entries[k].get("operator")
        if p["max_per_operator"] and op:
            per_op[op] = per_op.get(op, 0) + 1
            if per_op[op] > p["max_per_operator"]:
                verdicts[k] = ls.Verdict(k, False, "its operator has as many listed entrances "
                                                   "as allowed")
                continue
        if len(kept) >= MAX_ENTRANCES:
            verdicts[k] = ls.Verdict(k, False, f"the list is full ({MAX_ENTRANCES})")
            continue
        kept.append(k)
    items = [entries[k] for k in sorted(kept)]
    # Section 9: imported entries stay for import_days, unless the same entrance is
    # listed by the rules already or a decision removed it (by its url or onion).
    if inputs.genesis is not None and day < inputs.genesis + timedelta(days=p["import_days"]):
        for e in inputs.imported:
            if {e.get("url"), e.get("onion")} & st.removed["entrances"] or any(
                    _same_place(e, x) for x in items):
                continue
            if len(items) < MAX_ENTRANCES:
                items.append(dict(e))
    items.sort(key=lambda e: (e.get("key") or "", e.get("url") or "", e.get("onion") or ""))
    body = canonical_json({"v": 1, "updated": f"council {seq} day {day.isoformat()}",
                           "entrances": items}) + "\n"
    return body, verdicts
