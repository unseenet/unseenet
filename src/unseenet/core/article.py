"""The Unseenet article (UN-RFC 0002)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime

from .. import PROTOCOL_VERSION
from . import crypto, pow as postage
from .encoding import DS, H, b32

MAX_SIZE = 65536
MIN_ACCEPT_SIZE = 32768

# Headers outside the canonical form (UN-RFC 0002, section 3, step 1)
EXCLUDED = {"message-id", "signature", "proof-of-work", "member-signature",
            "approved-by", "approval"}
REQUIRED = ["unseenet-version", "message-id", "newsgroups", "date",
            "author-key", "signature", "proof-of-work"]
REQUIRED_PLAIN = ["from", "subject"]
FORBIDDEN = {"path", "xref"}

_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")
_MSGID_RE = re.compile(r"^<[a-z2-7]{32}@unseenet>$")


class ArticleError(ValueError):
    """Validation failure. ``reason`` matches the 441 reasons in UN-RFC 0005."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def format_date(dt: datetime, round_minutes: int = 10) -> str:
    dt = dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
    if round_minutes:
        dt = dt.replace(minute=dt.minute - dt.minute % round_minutes)
    return format_datetime(dt)


def parse_date(value: str) -> datetime:
    dt = parsedate_to_datetime(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_body(body: str) -> str:
    """Body with LF line endings, ending in exactly one LF."""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    if not body.endswith("\n"):
        body += "\n"
    return body


class Article:
    """Ordered headers plus a body. Header lookups are case-insensitive."""

    def __init__(self, headers: list[tuple[str, str]] | None = None, body: str = ""):
        self.headers: list[tuple[str, str]] = []
        for name, value in headers or []:
            self.set(name, value)
        self.body = normalize_body(body)

    # --- header access ---
    def get(self, name: str, default: str | None = None) -> str | None:
        lname = name.lower()
        for n, v in self.headers:
            if n.lower() == lname:
                return v
        return default

    def __getitem__(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise KeyError(name)
        return value

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    def set(self, name: str, value: str) -> None:
        if not _NAME_RE.match(name):
            raise ArticleError("syntax", f"bad header name {name!r}")
        if any(c in value for c in "\r\n\x00"):
            raise ArticleError("syntax", f"bad header value in {name}")
        lname = name.lower()
        for i, (n, _) in enumerate(self.headers):
            if n.lower() == lname:
                self.headers[i] = (n, value)
                return
        self.headers.append((name, value))

    def remove(self, name: str) -> None:
        lname = name.lower()
        self.headers = [(n, v) for n, v in self.headers if n.lower() != lname]

    @property
    def message_id(self) -> str:
        return self["Message-ID"]

    @property
    def group(self) -> str:
        return self["Newsgroups"].strip()

    @property
    def author_key(self) -> bytes:
        return crypto.key_from_text(self["Author-Key"])

    @property
    def control(self) -> list[str] | None:
        value = self.get("Control")
        return value.split() if value else None

    # --- wire format ---
    def to_bytes(self) -> bytes:
        lines = [f"{n}: {v}" for n, v in self.headers]
        text = "\r\n".join(lines) + "\r\n\r\n" + self.body.replace("\n", "\r\n")
        return text.encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Article":
        if len(raw) > MAX_SIZE:
            raise ArticleError("size")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArticleError("syntax", "not UTF-8") from exc
        text = text.replace("\r\n", "\n")
        head, sep, body = text.partition("\n\n")
        if not sep:
            raise ArticleError("syntax", "no header/body separator")
        art = cls()
        seen: set[str] = set()
        for line in head.split("\n"):
            if not line or line[0] in " \t":
                raise ArticleError("syntax", "folded or empty header line")
            name, colon, value = line.partition(":")
            if not colon:
                raise ArticleError("syntax", "header without colon")
            if name.lower() in seen:
                raise ArticleError("syntax", f"duplicate header {name}")
            seen.add(name.lower())
            art.headers.append((name, value.strip()))
            if not _NAME_RE.match(name):
                raise ArticleError("syntax", f"bad header name {name!r}")
        art.body = normalize_body(body)
        return art

    # --- canonical form, signing (UN-RFC 0002, sections 3-4) ---
    def canonical(self) -> bytes:
        items = sorted(
            (n.lower().encode("ascii"), v.strip(" \t").encode("utf-8"))
            for n, v in self.headers
            if n.lower() not in EXCLUDED
        )
        out = b"".join(n + b": " + v + b"\r\n" for n, v in items)
        return out + b"\r\n" + self.body.replace("\n", "\r\n").encode("utf-8")

    def compute_message_id(self) -> str:
        sig = crypto.sig_from_text(self["Signature"])
        digest = H(DS("UNSEENET-MSGID-1") + self.canonical() + sig)
        return f"<{b32(digest)[:32]}@unseenet>"

    def finalize(self, author: crypto.Identity, pow_bits: int,
                 member: crypto.Identity | None = None) -> "Article":
        """Sign, attach postage and compute the Message-ID."""
        self.set("Author-Key", author.key_text)
        for name in ("Message-ID", "Signature", "Proof-Of-Work", "Member-Signature"):
            self.remove(name)
        canonical = self.canonical()
        self.set("Signature", author.sign_text(crypto.PURPOSE_ARTICLE, canonical))
        if member is not None:
            self.set("Member-Signature", member.sign_text(crypto.PURPOSE_MEMBER, canonical))
        self.set("Proof-Of-Work", postage.solve(canonical, pow_bits))
        self.set("Message-ID", self.compute_message_id())
        return self

    def verify_signature(self) -> None:
        try:
            pk = self.author_key
            sig = crypto.sig_from_text(self["Signature"])
        except (crypto.CryptoError, KeyError) as exc:
            raise ArticleError("signature", str(exc)) from exc
        if not crypto.verify(pk, crypto.PURPOSE_ARTICLE, self.canonical(), sig):
            raise ArticleError("signature", "bad signature")
        if self.message_id != self.compute_message_id():
            raise ArticleError("signature", "Message-ID does not match content")

    def proven_pow(self) -> int:
        return postage.verify(self.get("Proof-Of-Work", ""), self.canonical())


def new_article(group: str, subject: str | None, body: str, *,
                from_name: str | None = None, references: list[str] | None = None,
                extra: list[tuple[str, str]] | None = None,
                now: datetime | None = None) -> Article:
    """Build an unsigned article with the standard header order."""
    headers = [("Unseenet-Version", PROTOCOL_VERSION),
               ("Newsgroups", group),
               ("Date", format_date(now or datetime.now(timezone.utc)))]
    if from_name is not None:
        headers.append(("From", from_name))
    if subject is not None:
        headers.append(("Subject", subject))
    if references:
        headers.append(("References", " ".join(references)))
    headers.extend(extra or [])
    return Article(headers, body)


def validate_structure(art: Article, *, raw_size: int, max_size: int = MAX_SIZE,
                       now: datetime | None = None) -> None:
    """UN-RFC 0002 section 5, steps 1-6 and 8 (no group or history knowledge)."""
    if raw_size > max_size:
        raise ArticleError("size")
    if art.get("Unseenet-Version") != PROTOCOL_VERSION:
        raise ArticleError("syntax", "unsupported Unseenet-Version")
    for name in REQUIRED:
        if name not in art:
            raise ArticleError("syntax", f"missing {name}")
    names = {n.lower() for n, _ in art.headers}
    if names & FORBIDDEN:
        raise ArticleError("syntax", "forbidden header (Path/Xref)")
    encrypted = "encrypted" in names
    for name in REQUIRED_PLAIN:
        if encrypted and name in names:
            raise ArticleError("syntax", f"{name} must be inside the ciphertext")
        if not encrypted and name not in names and art.control is None:
            raise ArticleError("syntax", f"missing {name}")
    if " " in art.group or "," in art.group:
        raise ArticleError("syntax", "exactly one group required")
    if not _MSGID_RE.match(art.message_id):
        raise ArticleError("signature", "malformed Message-ID")
    art.verify_signature()
    try:
        date = parse_date(art["Date"])
    except (TypeError, ValueError) as exc:
        raise ArticleError("date", "unparseable Date") from exc
    now = now or datetime.now(timezone.utc)
    if date > now + timedelta(hours=1):
        raise ArticleError("date", "Date in the future")
