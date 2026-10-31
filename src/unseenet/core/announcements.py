"""Node announcements (UN-RFC 0055 section 5): a node says where it is and what it
carries, in a group every node carries, signed with its own node key.

Belongs here: the pure rules - making and reading an announcement, when one is stale,
and when a node announces itself again.

Not here: posting them (``node/announcing.py``), the node's checks when it takes one
(``node/server/accepting.py``), clients choosing nodes (UN-RFC 0055 section 7)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import carrying as ca
from .groups import canonical_json

SUBJECT_PREFIX = "node "
STALE = timedelta(days=45)           # section 5.2: not renewed for 45 days
RENEW = timedelta(days=20)           # a node announces itself again well within 30 days
ONE_PER = timedelta(hours=23)        # section 5.4: at most one per key per day (with slack)
MAX_ADDRESSES = 8
MAX_NAME = 100


class AnnouncementProblem(ValueError):
    pass


@dataclass(frozen=True)
class Announcement:
    key: str
    address: str
    name: str
    carries: dict
    date: datetime
    addresses: tuple[str, ...] = ()
    operator: str | None = None
    contact: str | None = None
    message_id: str = ""
    patterns: list[str] = field(default_factory=list, compare=False)

    def stale(self, now: datetime) -> bool:
        return now - self.date > STALE


def _rfc3339(when: datetime) -> str:
    return when.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _address(a) -> str:
    if not isinstance(a, str) or not a or len(a) > 200 or any(c.isspace() for c in a):
        raise AnnouncementProblem(f"not a transport address: {a!r}")
    return a


def make_body(address: str, name: str, carries: dict, date: datetime, *,
              addresses=(), operator: str | None = None, contact: str | None = None) -> str:
    """The canonical JSON of an announcement (section 5.2)."""
    body: dict = {"v": 1, "address": _address(address), "name": name[:MAX_NAME],
                  "carries": carries, "date": _rfc3339(date)}
    if addresses:
        body["addresses"] = [_address(a) for a in list(addresses)[:MAX_ADDRESSES]]
    if operator:
        body["operator"] = operator
    if contact:
        body["contact"] = contact
    return canonical_json(body)


def subject(name: str) -> str:
    return SUBJECT_PREFIX + name[:MAX_NAME]


def parse(body: str, *, key: str, date: datetime, message_id: str = "") -> Announcement:
    """An announcement from its article: the body, its ``Author-Key`` and ``Date``.
    Raises ``AnnouncementProblem`` when it does not follow section 5.2."""
    try:
        d = json.loads(body)
    except ValueError as exc:
        raise AnnouncementProblem("not JSON") from exc
    if not isinstance(d, dict) or d.get("v") != 1:
        raise AnnouncementProblem("not a version 1 announcement")
    name, carries = d.get("name"), d.get("carries")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
        raise AnnouncementProblem("no name")
    if not isinstance(carries, dict):
        raise AnnouncementProblem("no carries")
    try:
        patterns = ca.check_patterns(carries.get("groups"))
    except ca.CarriesProblem as exc:
        raise AnnouncementProblem(str(exc)) from exc
    try:
        said = datetime.strptime(str(d.get("date")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise AnnouncementProblem("no date") from exc
    if abs(said - date) > timedelta(minutes=1):
        raise AnnouncementProblem("its date is not the article's Date")
    extra = d.get("addresses", [])
    if not isinstance(extra, list) or len(extra) > MAX_ADDRESSES:
        raise AnnouncementProblem(f"addresses: at most {MAX_ADDRESSES}")
    return Announcement(key, _address(d.get("address")), name, carries, date,
                        tuple(_address(a) for a in extra), d.get("operator"), d.get("contact"),
                        message_id, patterns)


def fingerprint(address: str, name: str, carries: dict, addresses=(), operator=None,
                contact=None) -> str:
    """What an announcement says, without its date: when it changes, the node
    announces itself again at once (section 5.2)."""
    text = canonical_json({"address": address, "name": name, "carries": carries,
                           "addresses": list(addresses), "operator": operator,
                           "contact": contact})
    return hashlib.sha256(text.encode()).hexdigest()


def due(last: datetime | None, said: str | None, now_says: str, now: datetime) -> bool:
    """Whether a node announces itself now: never yet, what it says changed, or the
    last one is older than ``RENEW`` - but never twice within ``ONE_PER``."""
    if last is not None and now - last < ONE_PER:
        return False
    return last is None or said != now_says or now - last >= RENEW


def newest(announcements, now: datetime) -> dict[str, Announcement]:
    """The newest announcement per node key that is not stale (section 5.4)."""
    out: dict[str, Announcement] = {}
    for a in announcements:
        if a.stale(now):
            continue
        if a.key not in out or a.date > out[a.key].date:
            out[a.key] = a
    return out
