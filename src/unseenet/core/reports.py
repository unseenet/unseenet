"""Spam reports (UN-RFC 0045): signed reports that nodes and readers choose to follow.

Any key can be an **issuer**. It publishes reports in its own key-bound channel
``reports@<fingerprint>`` (section 3); each report names posts and keys and why
(section 4). A report does nothing by itself (section 5): a node acts on the reports
of the issuers its operator names (section 6), a reader on those its hierarchy names
and those it chooses (section 7). Nobody has to follow anybody.

Belongs here: the reports group and its manifest fields, building and reading report
articles, and the ``Book`` - what the reports of the issuers one follows say about a
post or a key, shared by nodes (``node/server/reports.py``) and clients
(``client/session/reports.py``).

Not here: which issuers a hierarchy names (``hierarchies.py``, ``report_issuers``),
what a node does (``node/server/reports.py``), what a client shows (``client/session``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import crypto
from .article import Article, parse_date

GROUP_NAME = "reports"                 # reports@<fp>, a key-bound group (UN-RFC 0029)
MANIFEST_MAX = 4 * 1024                # its manifest article (UN-RFC 0040 section 9)
REASONS = ("spam", "flood", "phishing", "malware", "illegal", "other")    # section 4
MAX_ENTRIES = 1000                     # posts and keys together, in one article
KEY_MAX = timedelta(days=365)          # a key report's ``until``, at most after Date
NOTE_MAX = 200                         # characters of ``note``
POLICY_MAX = 2000                      # characters of the manifest's ``policy`` (section 3)
CONTACT_MAX = 512                      # characters of the manifest's ``contact``
MANIFEST_FIELDS = ("policy", "contact", "automatic")
MAX_HIERARCHY_ISSUERS = 16             # ``report_issuers`` of one hierarchy (section 7.1)

# what a node does with what an issuer it follows reports (section 6)
NODE_POSTS = ("hide", "delete")
NODE_KEYS = ("refuse", "surcharge", "ignore")
SURCHARGE_BITS = 6                     # "surcharge": this much more postage


class ReportError(ValueError):
    """A report article that is not one (wrong group, author, form or size)."""


def reports_group(public_key: bytes) -> str:
    """``reports@<fingerprint>``: the Group ID of a key's reports (section 3)."""
    from .groups import make_group_id
    return make_group_id(GROUP_NAME, public_key)


def is_reports_group(group_id: str) -> bool:
    return group_id.startswith(GROUP_NAME + "@")


def issuer_of(group_id: str) -> str:
    """The fingerprint a ``reports@`` Group ID names."""
    return group_id.partition("@")[2]


def check_manifest_fields(data: dict) -> None:
    """ValueError if ``policy``, ``contact`` or ``automatic`` are not as section 3
    says, or are set on a group that is not ``reports@``."""
    present = [k for k in MANIFEST_FIELDS if k in data]
    if not present:
        return
    if data.get("name") != GROUP_NAME:
        raise ValueError("policy, contact and automatic are for reports@ groups (UN-RFC 0045)")
    policy, contact = data.get("policy", ""), data.get("contact", "")
    if not isinstance(policy, str) or len(policy) > POLICY_MAX:
        raise ValueError(f"policy is text of at most {POLICY_MAX} characters")
    if not isinstance(contact, str) or len(contact) > CONTACT_MAX:
        raise ValueError(f"contact is text of at most {CONTACT_MAX} characters")
    if "automatic" in data and not isinstance(data["automatic"], bool):
        raise ValueError("automatic is true or false")


# --- reports (section 4) ------------------------------------------------------

@dataclass(frozen=True)
class PostEntry:
    id: str                            # the post's Message-ID
    group: str                         # where the issuer saw it
    reason: str


@dataclass(frozen=True)
class KeyEntry:
    key: str                           # ``ed25519:...``
    reason: str
    until: datetime


@dataclass(frozen=True)
class Report:
    message_id: str                    # the report article's
    issuer: str                        # the issuer's key, as text
    date: datetime
    posts: tuple[PostEntry, ...] = ()
    keys: tuple[KeyEntry, ...] = ()
    note: str = ""


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_until(value) -> datetime | None:
    """An RFC 3339 UTC time ending in Z, or None."""
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None


def _reason(value) -> bool:
    return isinstance(value, str) and value in REASONS


def report_body(posts=(), keys=(), note: str = "", now: datetime | None = None) -> str:
    """The canonical JSON of a report (section 4). ``posts``: (Message-ID, Group ID,
    reason); ``keys``: (key, reason, until or None). ``until`` defaults to 365 days
    from now and may not be later. ValueError if an entry is not one, if a post is in
    an inbox, or if there are none or more than 1000."""
    from .groups import canonical_json
    from .article import format_date
    # rounded as the article's Date is: a default until is then never past Date + 365 days
    now = parse_date(format_date(now or datetime.now(timezone.utc)))
    out_posts, out_keys = [], []
    for mid, group, reason in posts:
        if not (isinstance(mid, str) and mid.startswith("<") and mid.endswith(">")):
            raise ValueError(f"not a Message-ID: {mid!r}")
        if not isinstance(group, str) or "@" not in group:
            raise ValueError(f"not a Group ID: {group!r}")
        if group.startswith("inbox@"):
            raise ValueError("a sealed private post is never reported (UN-RFC 0045 section 4)")
        if not _reason(reason):
            raise ValueError(f"reason must be one of {', '.join(REASONS)}")
        out_posts.append({"id": mid, "group": group, "reason": reason})
    for key, reason, until in keys:
        crypto.key_from_text(key)
        if not _reason(reason):
            raise ValueError(f"reason must be one of {', '.join(REASONS)}")
        until = until or now + KEY_MAX
        if until > now + KEY_MAX:
            raise ValueError("a key is reported for at most 365 days")
        if until <= now:
            raise ValueError("until is in the past")
        out_keys.append({"key": key, "reason": reason, "until": iso(until)})
    if not out_posts and not out_keys:
        raise ValueError("a report names at least one post or key")
    if len(out_posts) + len(out_keys) > MAX_ENTRIES:
        raise ValueError(f"a report holds at most {MAX_ENTRIES} entries")
    note = note.strip()
    if len(note) > NOTE_MAX:
        raise ValueError(f"the note is at most {NOTE_MAX} characters")
    data: dict = {"v": 1}
    if out_posts:
        data["posts"] = out_posts
    if out_keys:
        data["keys"] = out_keys
    if note:
        data["note"] = note
    return canonical_json(data)


def report_article(issuer: crypto.Identity, body: str, *, from_name: str = "Report issuer",
                   pow_bits: int = 18, now: datetime | None = None) -> Article:
    """A signed report article in the issuer's ``reports@`` group, ``body`` from
    ``report_body``. Its subject says how many posts and keys it names."""
    from .article import new_article
    data = json.loads(body)
    n_posts, n_keys = len(data.get("posts", [])), len(data.get("keys", []))
    parts = [f"{n} {w}{'s' if n != 1 else ''}" for n, w in ((n_posts, "post"), (n_keys, "key")) if n]
    art = new_article(reports_group(issuer.public_key), "Report: " + " and ".join(parts), body,
                      from_name=from_name, extra=[("Content-Type", "application/json")], now=now)
    return art.finalize(issuer, pow_bits)


def parse_report(art: Article) -> Report:
    """A report article in a ``reports@`` group, posted by the group's own key.

    Entries that are not as section 4 says are left out - an unknown reason, a post
    in an inbox, a key without ``until`` or with one more than 365 days after Date -
    and the rest still count. ReportError if the article as a whole is not a report."""
    if art.control:
        raise ReportError("a control article")
    if not (art.get("Content-Type") or "").startswith("application/json"):
        raise ReportError("a report is application/json")
    try:
        author = crypto.key_to_text(art.author_key)
        date = parse_date(art["Date"])
    except (KeyError, ValueError, crypto.CryptoError) as exc:
        raise ReportError(f"not a report: {exc}") from exc
    return read_report(art.message_id, (art.get("Newsgroups") or "").strip(), author, date, art.body)


def read_report(message_id: str, group: str, author: str, date: datetime, body: str) -> Report:
    """A report from its parts, as a client holds a post (``parse_report`` for the
    checks on the article itself)."""
    if not is_reports_group(group):
        raise ReportError("not in a reports@ group")
    try:
        if crypto.fingerprint(crypto.key_from_text(author)) != issuer_of(group):
            raise ReportError("not posted by the group's own key")
    except (crypto.CryptoError, TypeError, ValueError) as exc:
        raise ReportError("not posted by the group's own key") from exc
    if date is None:
        raise ReportError("no Date")
    try:
        data = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise ReportError(f"not a report: {exc}") from exc
    if not isinstance(data, dict) or data.get("v") != 1:
        raise ReportError("not a version 1 report")
    raw_posts, raw_keys = data.get("posts") or [], data.get("keys") or []
    if not isinstance(raw_posts, list) or not isinstance(raw_keys, list):
        raise ReportError("posts and keys are lists")
    if len(raw_posts) + len(raw_keys) > MAX_ENTRIES:
        raise ReportError(f"more than {MAX_ENTRIES} entries")
    posts, keys = [], []
    for e in raw_posts:
        if not isinstance(e, dict) or not _reason(e.get("reason")):
            continue
        mid, g = e.get("id"), e.get("group")
        if (not isinstance(mid, str) or not mid.startswith("<") or not isinstance(g, str)
                or g.startswith("inbox@")):
            continue
        posts.append(PostEntry(mid, g, e["reason"]))
    for e in raw_keys:
        if not isinstance(e, dict) or not _reason(e.get("reason")):
            continue
        until = parse_until(e.get("until"))
        if until is None or until > date + KEY_MAX:
            continue
        try:
            crypto.key_from_text(e.get("key"))
        except (crypto.CryptoError, TypeError, ValueError):
            continue
        keys.append(KeyEntry(e["key"], e["reason"], until))
    note = data.get("note", "")
    return Report(message_id, author, date, tuple(posts), tuple(keys),
                  note[:NOTE_MAX] if isinstance(note, str) else "")


# --- what the reports one follows say (sections 5-7) ----------------------------

@dataclass(frozen=True)
class Hit:
    """Why a post or a key is reported: by whom, for what, and in which report."""
    issuer: str
    reason: str
    report: str                        # the report article's Message-ID
    automatic: bool = False            # the issuer's manifest says automatic (section 8)
    kind: str = "post"                 # "post" or "key"
    until: datetime | None = None      # a key: until when


@dataclass
class Book:
    """The reports of the issuers one follows, by post and by key. Reports are added
    as they are read and removed when their article is withdrawn. Of several issuers
    reporting the same thing, the earliest report is the one shown."""
    reports: dict[str, Report] = field(default_factory=dict)
    automatic: set[str] = field(default_factory=set)       # issuers' keys
    _posts: dict[str, list[Hit]] = field(default_factory=dict)
    _keys: dict[str, list[Hit]] = field(default_factory=dict)

    def add(self, report: Report, automatic: bool = False) -> bool:
        """Take a report in; False if it was known already."""
        if report.message_id in self.reports:
            return False
        self.reports[report.message_id] = report
        if automatic:
            self.automatic.add(report.issuer)
        for p in report.posts:
            self._posts.setdefault(p.id, []).append(
                Hit(report.issuer, p.reason, report.message_id, automatic, "post"))
        for k in report.keys:
            self._keys.setdefault(k.key, []).append(
                Hit(report.issuer, k.reason, report.message_id, automatic, "key", k.until))
        return True

    def remove(self, report_id: str) -> bool:
        """A withdrawn report article: what it said no longer counts."""
        report = self.reports.pop(report_id, None)
        if report is None:
            return False
        for table in (self._posts, self._keys):
            for k in [k for k, hits in table.items() if any(h.report == report_id for h in hits)]:
                table[k] = [h for h in table[k] if h.report != report_id]
                if not table[k]:
                    del table[k]
        return True

    def _first(self, hits, issuers) -> Hit | None:
        hits = [h for h in hits if issuers is None or h.issuer in issuers]
        if not hits:
            return None
        return min(hits, key=lambda h: (self.reports[h.report].date, h.report))

    def post(self, message_id: str, issuers=None) -> Hit | None:
        """The report of a post by one of ``issuers`` (all, if None)."""
        return self._first(self._posts.get(message_id, []), issuers)

    def key(self, key: str, issuers=None, now: datetime | None = None) -> Hit | None:
        """A report of a key still in force, by one of ``issuers`` (all, if None)."""
        now = now or datetime.now(timezone.utc)
        return self._first([h for h in self._keys.get(key, []) if h.until and h.until > now],
                           issuers)

    def reported_posts(self, issuers=None) -> dict[str, Hit]:
        """Every reported post, by Message-ID."""
        out = {}
        for mid, hits in self._posts.items():
            hit = self._first(hits, issuers)
            if hit:
                out[mid] = hit
        return out

    def issuers(self) -> set[str]:
        return {r.issuer for r in self.reports.values()}
