"""Lists kept by councils (UN-RFC 0020): the rules every replica computes alike.

A list council's replicas measure the announced nodes each day, post what they found
(``report <date>``), and compute the node list from public data alone: the nodes'
announcements, the reports of the council's members, the passed ``list`` decisions
(UN-RFC 0061) and the council's own list of the day before. Replicas that have read the
same articles post identical lists, so it does not matter whose post is newest.

Belongs here: the list council's manifest fields (section 4), measurement reports
(section 7), ``list`` decisions (section 6.7), minimum versions (section 6.5) and the
rules for the node list (section 6.1). Pure functions over what a caller read, so that a
client can check a list the same way a replica made it.

Not here: reaching nodes and posting canaries (the replica), hierarchy claims
(section 6.2), entrances and scribes (sections 6.3 and 6.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from . import carrying as ca
from . import transport
from .announcements import Announcement
from .groups import canonical_json, parse_canonical_json, split_group_id

LIST_KINDS = ("nodes", "root", "entrances", "scribes")
REPORT_PREFIX = "report "
MAX_NODES = 200                              # UN-RFC 0010 section 2
MAX_REPORT_KEYS = 1000
MAX_SOFTWARE = 100

# Section 6: the parameters a ``set`` decision may change, and their values until then.
PARAMS = {
    "announce_days": 30,        # 5.1: how long an announcement is current
    "window_days": 7,           # 6.1 item 3: the days looked at ...
    "need_days": 5,             # ... and on how many of them a replica must have reached it
    "grace_days": 10,           # 6.1: a listed entry leaves after this many days down
    "import_days": 180,         # 9: an imported entry stays this long without the rules
    "max_per_operator": 0,      # 12: entries per operator key; 0 is no limit
}
PARAM_LIMITS = {"announce_days": (7, 90), "window_days": (3, 30), "need_days": (1, 30),
                "grace_days": (3, 60), "import_days": (0, 730), "max_per_operator": (0, 200)}


class ListProblem(ValueError):
    pass


# --- the list council (section 4) ---------------------------------------------

@dataclass(frozen=True)
class ListCouncil:
    """What a council manifest says about the lists it keeps."""
    lists: dict[str, str]                  # kind -> list group
    claims: str
    reports: str
    min_software: dict[str, str] = field(default_factory=dict)
    publishers: tuple[str, ...] = ()
    import_id: str | None = None


def _group(g, what: str) -> str:
    if not isinstance(g, str):
        raise ListProblem(f"{what} is a Group ID")
    try:
        split_group_id(g)
    except Exception as exc:
        raise ListProblem(f"{what}: {exc}") from exc
    return g


def list_council(data: dict) -> ListCouncil | None:
    """The list council fields of a council manifest's ``data``, or None when the
    council keeps no lists. Raises ``ListProblem`` when they are malformed."""
    if "lists" not in data:
        return None
    lists = data["lists"]
    if not isinstance(lists, dict) or not lists or not set(lists) <= set(LIST_KINDS):
        raise ListProblem(f"lists maps some of {', '.join(LIST_KINDS)} to Group IDs")
    lists = {k: _group(v, f"lists.{k}") for k, v in lists.items()}
    soft = data.get("min_software", {})
    if not isinstance(soft, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and version_key(v) for k, v in soft.items()):
        raise ListProblem("min_software maps implementations to versions")
    pubs = data.get("publishers", [])
    if not isinstance(pubs, list):
        raise ListProblem("publishers is a list of Group IDs")
    if "scribes" in lists and not pubs:
        raise ListProblem("a council with a scribe list names its publishers")
    imp = data.get("import")
    if imp is not None and not (isinstance(imp, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", imp)):
        raise ListProblem("import is sha256:<hex> of the import's body")
    return ListCouncil(lists, _group(data.get("claims"), "claims"),
                       _group(data.get("reports"), "reports"), dict(soft),
                       tuple(_group(p, "publishers") for p in pubs), imp)


# --- the genesis import (section 9) --------------------------------------------

IMPORT_SUBJECT = "import"
LIST_LABELS = {"nodes": "nodes", "root": "hierarchies", "entrances": "entrances",
               "scribes": "scribes"}


def import_body(lists: dict) -> str:
    """The import article's body: the lists as they are, by kind (``{"nodes": <a node
    list of UN-RFC 0010>, ...}``)."""
    if not isinstance(lists, dict) or not set(lists) <= set(LIST_KINDS):
        raise ListProblem(f"an import holds some of {', '.join(LIST_KINDS)}")
    return canonical_json({"v": 1, **lists}) + "\n"


def import_hash(body: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(body.rstrip("\n").encode("utf-8")).hexdigest()


def imported_nodes(body: str) -> dict[str, dict]:
    """The node entries of an import, by node key."""
    try:
        d = parse_canonical_json(body)
        nodes = d["nodes"]["nodes"]
    except Exception:
        return {}
    return {n["node_key"]: n for n in nodes if isinstance(n, dict) and isinstance(n.get("node_key"), str)}


# --- versions (section 6.5) ----------------------------------------------------

_VERSION = re.compile(r"^(\d+(?:\.\d+)*)(.*)$")


def version_key(version: str) -> tuple | None:
    """A sortable form of a version: its numbers, and a release after its pre-releases
    (``0.7.2.dev3`` < ``0.7.2rc1`` < ``0.7.2``). None when it does not start with a
    number."""
    m = _VERSION.match(version.strip())
    if not m:
        return None
    nums = tuple(int(n) for n in m.group(1).split("."))
    nums = nums + (0,) * (4 - len(nums)) if len(nums) < 4 else nums
    rest = m.group(2).lstrip(".-")
    return nums, (0 if rest else 1), rest


def below_minimum(software: str | None, min_software: dict[str, str]) -> bool:
    """Whether ``"<implementation> <version>"`` is below the council's minimum for that
    implementation. An implementation the minimum does not name, or software not
    stated, is not below it."""
    if not software or not min_software:
        return False
    impl, _, version = software.strip().partition(" ")
    floor = min_software.get(impl)
    if floor is None:
        return False
    have, need = version_key(version), version_key(floor)
    return have is None or have < need


# --- measurements (section 7) --------------------------------------------------

@dataclass(frozen=True)
class Report:
    key: str                               # the replica that measured
    day: date
    reached: frozenset[str]
    missed: frozenset[str]
    disconnected: frozenset[str] = frozenset()   # UN-RFC 0021 section 7
    incomplete: frozenset[str] = frozenset()
    software: dict = field(default_factory=dict, compare=False)
    files: tuple = ()
    date: datetime | None = None           # the article's Date
    message_id: str = ""


def report_subject(day: date) -> str:
    return REPORT_PREFIX + day.isoformat()


def _keys(v, what: str) -> list[str]:
    if not isinstance(v, list) or len(v) > MAX_REPORT_KEYS or not all(
            isinstance(k, str) and k.startswith("ed25519:") and len(k) < 80 for k in v):
        raise ListProblem(f"{what} is a list of keys")
    return sorted(set(v))


def report_body(day: date, reached, missed, *, disconnected=(), incomplete=(),
                software: dict | None = None, files=()) -> str:
    body: dict = {"v": 1, "date": day.isoformat(), "reached": _keys(list(reached), "reached"),
                  "missed": _keys(list(missed), "missed")}
    if disconnected:
        body["disconnected"] = _keys(list(disconnected), "disconnected")
    if incomplete:
        body["incomplete"] = _keys(list(incomplete), "incomplete")
    if software:
        body["software"] = {k: str(v)[:MAX_SOFTWARE] for k, v in sorted(software.items())}
    if files:
        body["files"] = list(files)
    return canonical_json(body) + "\n"


def parse_report(body: str, *, key: str, date: datetime, message_id: str = "") -> Report:
    """A report from its article: the body, its ``Author-Key`` and ``Date``. A report
    is about a completed UTC day and is posted on that day or the next."""
    try:
        d = parse_canonical_json(body)
    except Exception as exc:
        raise ListProblem("not canonical JSON") from exc
    if not isinstance(d, dict) or d.get("v") != 1:
        raise ListProblem("not a version 1 report")
    try:
        day = datetime.strptime(str(d.get("date")), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ListProblem("no date") from exc
    start = datetime.combine(day, time(), timezone.utc)
    if not start <= date < start + timedelta(days=2):
        raise ListProblem("posted on another day than the one it reports")
    reached, missed = set(_keys(d.get("reached"), "reached")), set(_keys(d.get("missed"), "missed"))
    if reached & missed:
        raise ListProblem("a key both reached and missed")
    disc = set(_keys(d.get("disconnected", []), "disconnected"))
    inc = set(_keys(d.get("incomplete", []), "incomplete"))
    if not (disc | inc) <= reached:
        raise ListProblem("disconnected and incomplete are keys it reached")
    soft = d.get("software", {})
    if not isinstance(soft, dict) or not set(soft) <= reached or not all(
            isinstance(v, str) and len(v) <= MAX_SOFTWARE for v in soft.values()):
        raise ListProblem("software maps keys it reached to what they said")
    files = d.get("files", [])
    if not isinstance(files, list):
        raise ListProblem("files is a list")
    return Report(key, day, frozenset(reached), frozenset(missed), frozenset(disc),
                  frozenset(inc), dict(soft), tuple(files), date, message_id)


class Measurements:
    """The reports of a council's members, one per member and day (the newest counts,
    and of two with one Date the larger Message-ID)."""

    def __init__(self, reports, members: set[str]):
        best: dict[tuple[str, date], Report] = {}
        for r in reports:
            if r.key not in members:
                continue
            k = (r.key, r.day)
            o = best.get(k)
            if o is None or (r.date, r.message_id) > (o.date, o.message_id):
                best[k] = r
        self.by_day: dict[date, list[Report]] = {}
        for (_, d), r in sorted(best.items()):
            self.by_day.setdefault(d, []).append(r)

    def reached(self, d: date, key: str) -> bool:
        return any(key in r.reached for r in self.by_day.get(d, ()))

    def good(self, d: date, key: str) -> bool:
        """Reached, connected and complete by at least one replica (UN-RFC 0021 7)."""
        return any(key in r.reached and key not in r.disconnected and key not in r.incomplete
                   for r in self.by_day.get(d, ()))

    def reported(self, d: date, key: str) -> bool:
        return any(key in r.reached or key in r.missed for r in self.by_day.get(d, ()))

    def software(self, d: date, key: str) -> str | None:
        """What the entry said it runs on day ``d``: the highest version any replica
        heard, so that one replica cannot take an entry off by misreporting it."""
        said = [r.software[key] for r in self.by_day.get(d, ()) if key in r.software]
        if not said:
            return None
        return max(said, key=lambda s: (version_key(s.partition(" ")[2]) or ((),), s))


# --- decisions (section 6.7) ---------------------------------------------------

def check_list_change(c) -> None:
    """A ``list`` change of a proposal (UN-RFC 0061 section 4): exactly one of
    ``remove``/``restore`` ``{"list": kind, "entry": key or name}``, ``reserve``/
    ``unreserve`` a top-level name, or ``set`` parameters of section 6."""
    if not isinstance(c, dict) or len(c) != 1:
        raise ListProblem("a list change is one of remove, restore, reserve, unreserve, set")
    (op, arg), = c.items()
    if op in ("remove", "restore"):
        if (not isinstance(arg, dict) or set(arg) != {"list", "entry"}
                or arg["list"] not in LIST_KINDS or not isinstance(arg["entry"], str)
                or not 0 < len(arg["entry"]) <= 100):
            raise ListProblem(f"{op} is {{\"list\": kind, \"entry\": key or name}}")
    elif op in ("reserve", "unreserve"):
        if not isinstance(arg, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", arg):
            raise ListProblem(f"{op} is a top-level name")
    elif op == "set":
        if not isinstance(arg, dict) or not arg or not set(arg) <= set(PARAMS):
            raise ListProblem(f"set changes some of {', '.join(PARAMS)}")
        for k, v in arg.items():
            lo, hi = PARAM_LIMITS[k]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise ListProblem(f"{k} is a number from {lo} to {hi}")
    else:
        raise ListProblem("a list change is one of remove, restore, reserve, unreserve, set")


@dataclass(frozen=True)
class Decision:
    """A passed ``list`` proposal and the day it applies (UN-RFC 0061 section 7)."""
    applies: date
    id: str
    change: dict


@dataclass
class DecisionState:
    removed: dict[str, set[str]] = field(default_factory=lambda: {k: set() for k in LIST_KINDS})
    reserved: set[str] = field(default_factory=set)
    params: dict[str, int] = field(default_factory=lambda: dict(PARAMS))


def decisions_until(decisions, day: date) -> DecisionState:
    """What the passed decisions that apply on or before ``day`` add up to, applied in
    order of the day they apply and then of their id."""
    st = DecisionState()
    for d in sorted(decisions, key=lambda d: (d.applies, d.id)):
        if d.applies > day:
            break
        (op, arg), = d.change.items()
        if op == "remove":
            st.removed[arg["list"]].add(arg["entry"])
        elif op == "restore":
            st.removed[arg["list"]].discard(arg["entry"])
        elif op == "reserve":
            st.reserved.add(arg)
        elif op == "unreserve":
            st.reserved.discard(arg)
        elif op == "set":
            st.params.update(arg)
    return st


# --- the node list (section 6.1) -------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    key: str
    listed: bool
    why: str                 # in plain words, for the log and ``status``


def _end(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time(), timezone.utc)


def _days(day: date, n: int) -> list[date]:
    return [day - timedelta(days=i) for i in range(n)]


def _onion(a: Announcement) -> bool:
    try:
        parsed = transport.parse(a.address)
    except transport.AddressProblem:
        return False
    return parsed is not None and parsed.scheme == "onion"


def _extra_addresses(a: Announcement) -> list[str]:
    """Further addresses as the node gives them, but never a ``test:`` one."""
    out = []
    for text in a.addresses:
        try:
            p = transport.parse(text)
        except transport.AddressProblem:
            continue
        if p is None or p.scheme != "test":
            out.append(text)
    return out


def carries_network(a: Announcement, network) -> bool:
    """Item 2: its ``carries`` names every one of the network's own groups."""
    return all(ca.matches(a.patterns, ca.group_name(g)) for g in network)


def node_entry(a: Announcement) -> dict:
    e: dict = {"name": a.name, "address": a.address, "node_key": a.key}
    extra = _extra_addresses(a)
    if extra:
        e["addresses"] = extra
    if a.operator:
        e["operator"] = a.operator
    return e


def node_list(*, day: date, seq: int, announcements, measurements: Measurements,
              network, previous: set[str], council: ListCouncil,
              decisions: DecisionState | None = None, imported: dict[str, dict] | None = None,
              genesis: date | None = None) -> tuple[str, dict[str, Verdict]]:
    """The node list for the completed UTC day ``day`` and why each node is on it or
    not: (body, {node key: verdict}).

    ``announcements``: the node announcements read (UN-RFC 0055 section 5);
    ``network``: the network's own groups (``carrying.network_groups``);
    ``previous``: the node keys on this council's list of the day before - a listed
    node keeps its place until it has been down for ``grace_days``;
    ``imported``: entries of the genesis import (section 9), by node key, which stay
    for ``import_days`` after ``genesis`` whatever the rules say."""
    st = decisions or DecisionState()
    p = st.params
    end = _end(day)
    current: dict[str, Announcement] = {}
    for a in announcements:
        if a.date >= end or end - a.date > timedelta(days=p["announce_days"]):
            continue
        if a.key not in current or (a.date, a.message_id) > (current[a.key].date,
                                                              current[a.key].message_id):
            current[a.key] = a
    imported = imported or {}
    import_lasts = genesis is not None and day < genesis + timedelta(days=p["import_days"])
    window = _days(day, p["window_days"])
    grace = _days(day, p["grace_days"])

    verdicts: dict[str, Verdict] = {}
    entries: dict[str, dict] = {}

    def no(key, why):
        verdicts[key] = Verdict(key, False, why)

    for key in sorted(set(current) | (set(imported) if import_lasts else set())):
        a = current.get(key)
        if key in st.removed["nodes"]:
            no(key, "removed by a decision of the council")
            continue
        if a is None:
            entries[key] = dict(imported[key])
            verdicts[key] = Verdict(key, True, "imported at the genesis; not announced yet")
            continue
        if not _onion(a):
            no(key, "its address is not an onion: address")
            continue
        last_reached = next((d for d in window if measurements.reached(d, key)), None)
        soft = measurements.software(last_reached, key) if last_reached else None
        if below_minimum(soft, council.min_software):
            no(key, f"its software ({soft}) is below the council's minimum")
            continue
        if not carries_network(a, network):
            no(key, "it does not carry all of the network's own groups")
            continue
        if key in previous:
            down = all(measurements.reported(d, key) and not measurements.good(d, key)
                       for d in grace)
            if down:
                no(key, f"no replica reached it connected and complete for {p['grace_days']} days")
                continue
            why = "listed, and not down"
        else:
            n = sum(measurements.reached(d, key) for d in window)
            if n < p["need_days"]:
                if import_lasts and key in imported:
                    entries[key] = node_entry(a)
                    verdicts[key] = Verdict(key, True, "imported at the genesis")
                    continue
                no(key, f"reached on {n} of the last {p['window_days']} days; "
                        f"{p['need_days']} are needed")
                continue
            if not measurements.good(last_reached, key):
                if import_lasts and key in imported:
                    entries[key] = node_entry(a)
                    verdicts[key] = Verdict(key, True, "imported at the genesis")
                    continue
                no(key, "not connected and complete the last day it was reached (UN-RFC 0021)")
                continue
            why = f"reached on {n} of the last {p['window_days']} days, connected and complete"
        entries[key] = node_entry(a)
        verdicts[key] = Verdict(key, True, why)

    # Section 12 and UN-RFC 0010: at most max_per_operator per operator, at most 200 -
    # those already listed first, then by node key.
    order = sorted(entries, key=lambda k: (k not in previous, k))
    kept, per_op = [], {}
    for k in order:
        op = entries[k].get("operator")
        if p["max_per_operator"] and op:
            per_op[op] = per_op.get(op, 0) + 1
            if per_op[op] > p["max_per_operator"]:
                verdicts[k] = Verdict(k, False, "its operator has as many listed nodes as allowed")
                continue
        if len(kept) >= MAX_NODES:
            verdicts[k] = Verdict(k, False, f"the list is full ({MAX_NODES})")
            continue
        kept.append(k)
    body = canonical_json({"v": 1, "updated": f"council {seq} day {day.isoformat()}",
                           "nodes": [entries[k] for k in sorted(kept)]})
    return body + "\n", verdicts


def updated_day(updated: str) -> tuple[int, date] | None:
    """(council seq, day) from a list's ``updated`` field of section 8, or None."""
    m = re.fullmatch(r"council (\d+) day (\d{4}-\d{2}-\d{2})", updated or "")
    if not m:
        return None
    try:
        return int(m.group(1)), date.fromisoformat(m.group(2))
    except ValueError:
        return None


# --- canaries: connected and complete (UN-RFC 0021, section 7) --------------------

CANARY_PREFIX = "canary "


def canary_subject(node_key: str, day: date) -> str:
    return f"{CANARY_PREFIX}{node_key[8:24]} {day.isoformat()}"


def canary_body(node_key: str, day: date, nonce: str) -> str:
    """A canary for the node ``node_key``, posted to that node alone on ``day``. The
    nonce makes every canary a new article (UN-RFC 0021 section 4)."""
    return canonical_json({"v": 1, "node": node_key, "date": day.isoformat(),
                           "nonce": nonce}) + "\n"


def read_canary(body: str, day: date) -> str | None:
    """The node key a canary of ``day`` was posted to, or None. The caller checks that
    a member of the council signed it, in the council's reports group."""
    try:
        d = parse_canonical_json(body)
    except Exception:
        return None
    if not isinstance(d, dict) or d.get("v") != 1 or d.get("date") != day.isoformat():
        return None
    node = d.get("node")
    return node if isinstance(node, str) and node.startswith("ed25519:") else None


@dataclass
class Reading:
    """What one replica read from one node today."""
    seen: set[str] = field(default_factory=set)       # node keys whose canary of yesterday it has
    groups: set[str] = field(default_factory=set)     # its ordinary groups (LIST ACTIVE)
    patterns: list[str] = field(default_factory=list)  # what its announcement says it carries


def connection_verdicts(readings: dict[str, Reading], posted: set[str],
                        network=()) -> tuple[set[str], set[str]]:
    """(disconnected, incomplete) among the nodes that answered today (UN-RFC 0021
    sections 5 and 6). ``posted``: the node keys this replica posted a canary to
    yesterday - only those can be judged on whether their canary got out.

    A node is **connected** when its canary of yesterday reached more than half of
    the nodes that answered, and it has every canary that did. A group is carried by
    the network when more than half of the connected nodes list it; a connected node
    is **complete** when it lists every such group its own ``carries`` names, and every
    one of the network's own groups (UN-RFC 0055 section 4)."""
    answered = len(readings)
    if not answered or not posted:
        return set(), set()
    reach = {k: sum(k in r.seen for r in readings.values()) for k in posted}
    in_network = {k for k, n in reach.items() if 2 * n > answered}
    disconnected = {k for k, r in readings.items()
                    if (k in posted and k not in in_network) or (in_network - r.seen)}
    connected = [k for k in readings if k not in disconnected]
    incomplete: set[str] = set()
    if connected:
        count: dict[str, int] = {}
        for k in connected:
            for g in readings[k].groups:
                count[g] = count.get(g, 0) + 1
        carried = {g for g, n in count.items() if 2 * n > len(connected)}
        own = set(network)
        for k in connected:
            r = readings[k]
            wanted = {g for g in carried if ca.matches(r.patterns, ca.group_name(g))}
            if (wanted | (own & carried)) - r.groups:
                incomplete.add(k)
    return disconnected, incomplete
