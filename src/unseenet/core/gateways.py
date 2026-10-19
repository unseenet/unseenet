"""The gateway directory (UN-RFC 0038 section 6): who runs gateways, and what to invite.

Gateways announce themselves in ``unseenet.gateways``. Each announcement is a
signed JSON article; the newest one per key counts, and announcements older
than 30 days are not shown, so gateways that stop drop out by themselves. A
gatewayed group is active while one of its gateways announces it (section 7).

The directory is a list, not a recommendation: anybody can announce, and an
announcement can claim anything except the key that signed it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import crypto
from .article import Article, ArticleError, parse_date

DIRECTORY_GROUP = "unseenet.gateways@ph5fc5hop5232qsz"
MAX_AGE = timedelta(days=30)


@dataclass(frozen=True)
class GatewayNetwork:
    network: str
    account: str
    imports: bool
    exports: bool
    portals: bool = False
    requests: bool = False


@dataclass
class GatewayAnnouncement:
    key: str                         # the gateway key that signed it
    name: str
    operator: str
    contact: str
    date: datetime
    policy: str = ""
    networks: list[GatewayNetwork] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        return crypto.fingerprint(crypto.key_from_text(self.key))


def _text(d: dict, name: str, limit: int, required: bool = True) -> str:
    v = d.get(name, "")
    if not isinstance(v, str) or (required and not v):
        raise ValueError(name)
    return v[:limit]


def parse_announcement(art: Article) -> GatewayAnnouncement:
    """A verified announcement, or ValueError / ArticleError."""
    art.verify_signature()
    d = json.loads(art.body)
    if not isinstance(d, dict) or d.get("v") != 1:
        raise ValueError("not a version 1 announcement")
    nets = []
    for n in d.get("networks") or []:
        if not isinstance(n, dict):
            continue
        nets.append(GatewayNetwork(
            network=_text(n, "network", 64), account=_text(n, "account", 256),
            imports=bool(n.get("import")), exports=bool(n.get("export")),
            portals=bool(n.get("portals")), requests=bool(n.get("requests"))))
    if not nets:
        raise ValueError("no networks")
    groups = [g for g in d.get("groups") or [] if isinstance(g, str) and "@" in g]
    return GatewayAnnouncement(
        key=crypto.key_to_text(art.author_key), name=_text(d, "name", 64),
        operator=_text(d, "operator", 128), contact=_text(d, "contact", 128),
        date=parse_date(art["Date"]), policy=_text(d, "policy", 1024, required=False),
        networks=nets, groups=groups[:10000])


def current(articles, *, now: datetime | None = None) -> list[GatewayAnnouncement]:
    """The newest valid announcement per gateway key, not older than 30 days, by name."""
    now = now or datetime.now(timezone.utc)
    newest: dict[str, GatewayAnnouncement] = {}
    for art in articles:
        try:
            a = parse_announcement(art)
        except (ArticleError, ValueError, KeyError, TypeError, crypto.CryptoError):
            continue
        if now - a.date > MAX_AGE or a.date - now > timedelta(days=1):
            continue
        if a.key not in newest or a.date > newest[a.key].date:
            newest[a.key] = a
    return sorted(newest.values(), key=lambda a: (a.name.lower(), a.key))


def active_groups(announcements: list[GatewayAnnouncement]) -> dict[str, list[str]]:
    """Group ID -> names of the gateways announcing it (UN-RFC 0038 section 7)."""
    out: dict[str, list[str]] = {}
    for a in announcements:
        for g in a.groups:
            out.setdefault(g, []).append(a.name)
    return out
