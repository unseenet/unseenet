"""Origin headers (UN-RFC 0049 section 4, UN-RFC 0023 section 4.3): where an article was
first published, by a gateway or by its own author (a self-import).

``Origin-Network`` names the other network, ``Origin-Date`` when it was first published
there - RFC 3339 UTC for a self-import, the other network's text as a gateway copies it -
and ``Origin-ID`` / ``Origin-From`` what the other network called it and its author.
``Origin-Date`` is the author's (or gateway's) claim: shown as such, never as the time of
posting, and ignored when it cannot be read or is later than ``Date`` (section 4.2).

An article is *old on arrival* when its origin date is more than 24 hours before its
``Date`` (section 5.2): not new, no notification, not in For you.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

OLD_ON_ARRIVAL = timedelta(hours=24)
NETWORK_RE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,31}$")
MAX_VALUE = 256


class OriginError(ValueError):
    pass


@dataclass(frozen=True)
class Origin:
    network: str
    date: datetime | None = None          # None: none given, unreadable or later than Date
    id: str = ""
    from_: str = ""

    def to_dict(self) -> dict:
        return {"network": self.network, "date": self.date.isoformat() if self.date else None,
                "id": self.id or None, "from": self.from_ or None}


def parse_origin_date(text: str) -> datetime | None:
    """RFC 3339 (self-imports), else RFC 5322 or ISO as a gateway copied it; None if
    neither."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def origin_of(get, date: datetime | None) -> Origin | None:
    """The origin of an article from its headers (``get`` is ``Article.get``), or None
    when it has no ``Origin-Network``. ``date`` is its ``Date``: a later origin date is
    ignored (section 4.2)."""
    network = (get("Origin-Network") or "").strip().lower()
    if not network:
        return None
    when = parse_origin_date(get("Origin-Date") or "")
    if when is not None and date is not None and when > date:
        when = None
    return Origin(network[:32], when, (get("Origin-ID") or "").strip()[:MAX_VALUE],
                  (get("Origin-From") or "").strip()[:MAX_VALUE])


def old_on_arrival(origin_date: datetime | None, date: datetime | None) -> bool:
    """Section 5.2: first published more than 24 hours before it entered the network."""
    return origin_date is not None and date is not None and date - origin_date > OLD_ON_ARRIVAL


PROOF_MAX = 8 * 1024                     # the old header block, before encoding (7.3)


def origin_headers(network: str, date: datetime | str | None = None, id: str = "",
                   from_: str = "", now: datetime | None = None,
                   proof: bytes | None = None) -> list[tuple[str, str]]:
    """The headers an author puts on their own import (section 4.1). ``network`` is a
    lowercase name (``facebook``, ``x``, ``mastodon``, ...); ``date`` the time it was
    first published, written as RFC 3339 UTC, never later than now. ``proof``: the old
    article, as signed (section 7.3) - only its header block is carried; it links the two
    keys for good, so it is the author's choice, off by default. Raises OriginError."""
    network = (network or "").strip().lower()
    if not NETWORK_RE.match(network):
        raise OriginError("Origin-Network is a lowercase name such as facebook or mastodon")
    out = [("Origin-Network", network)]
    if date is not None:
        when = date if isinstance(date, datetime) else parse_origin_date(date)
        if when is None:
            raise OriginError("Origin-Date cannot be read: use RFC 3339, e.g. 2026-08-03T14:20:00Z")
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when > (now or datetime.now(timezone.utc)) + timedelta(minutes=5):
            raise OriginError("Origin-Date is in the future")
        out.append(("Origin-Date", when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    for name, value in (("Origin-ID", id), ("Origin-From", from_)):
        value = (value or "").strip()
        if value:
            if len(value) > MAX_VALUE or "\n" in value or "\r" in value:
                raise OriginError(f"{name} is one line of at most {MAX_VALUE} characters")
            out.append((name, value))
    if proof is not None:
        head = bytes(proof).partition(b"\r\n\r\n")[0]
        if not head or len(head) > PROOF_MAX:
            raise OriginError(f"Origin-Proof: the old article's headers, at most {PROOF_MAX} bytes")
        import base64
        out.append(("Origin-Proof", base64.urlsafe_b64encode(head).decode().rstrip("=")))
    return out


def check_proof(art) -> str | None:
    """The old key, as ``ed25519:...``, when an article's ``Origin-Proof`` holds (section
    7.3): the old article - the proof's headers and this body - is signed by that key,
    its Message-ID matches, its ``Date`` is the ``Origin-Date``, and its Message-ID the
    ``Origin-ID`` when given. None otherwise: a proof that does not hold is none."""
    import base64
    from . import crypto
    from .article import Article, ArticleError
    value = (art.get("Origin-Proof") or "").strip()
    if not value:
        return None
    try:
        head = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        if len(head) > PROOF_MAX:
            return None
        body = art.body.replace("\n", "\r\n").encode("utf-8")
        old = Article.from_bytes(head + b"\r\n\r\n" + body)
        old.verify_signature()
    except (ValueError, ArticleError, crypto.CryptoError, KeyError):
        return None
    when, claimed = parse_date_header(old.get("Date")), parse_origin_date(art.get("Origin-Date") or "")
    if when is None or claimed is None or abs((when - claimed).total_seconds()) >= 1:
        return None
    oid = (art.get("Origin-ID") or "").strip()
    if oid and oid != old.message_id:
        return None
    return crypto.key_to_text(old.author_key)


def parse_date_header(text: str | None) -> datetime | None:
    """An article's own ``Date`` header, or None."""
    from .article import parse_date
    try:
        return parse_date(text) if text else None
    except (ValueError, TypeError):
        return None
