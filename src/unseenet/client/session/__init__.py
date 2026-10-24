"""Client session: one person's (or one service's) client of the Unseenet network.

``Session`` is the client core that every client is built on - the command line, the
TUI, unseenet-gui, the local client API (UN-RFC 0046), bots and gateways - so they all
behave alike. It holds the encrypted vault (UN-RFC 0007), talks to nodes over Tor, and
reads and posts. Clients use the one class; its code is split by area:

    base.py       the vault, identities, settings, events
    ripening.py   key ripening (UN-RFC 0025)
    nodes.py      nodes, the connection, push, Tor
    labels.py     how people and groups are shown: names and labels (UN-RFC 0019)
    groups.py     manifests, creating and changing groups, moderation, roles, portals
    private.py    the inbox, private posts and chats, key-bound groups and renewal
    profiles.py   profiles and pictures (UN-RFC 0022)
    people.py     contacts, ignoring, for you and mentions, notices, bots, reporting
    reading.py    following, fetching, threads and views, the offline cache, read marks
    posting.py    posting, postage, editing and withdrawing
    attachments.py  files on posts: preparing and checking them (UN-RFC 0027)
    kept.py       pinned posts and the pages of sites (UN-RFC 0033, 0035)
    personal.py   an identity's personal feed and site (UN-RFC 0029 section 2.1)
    following.py  following feeds and people, the timeline (UN-RFC 0034 sections 6, 7)
    state.py      your state in the network, encrypted, merged and written (UN-RFC 0044)

New code goes in the file whose docstring says it belongs there; a new area gets a file
of its own, added to ``Session`` below. This file holds what all parts share: imports,
constants, ``Message``, ``GroupInfo``, ``Permission``, ``SessionError`` and helpers.
Names that tests patch on this module (``DEFAULT_POW``, ``TorProcess``) are read
through it (``_s.NAME``) in the parts.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
import re
import base64
import json
import textwrap
from dataclasses import dataclass, field, replace
from typing import NamedTuple
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ...core import crypto
from ...core.backoff import Backoff
from ...core.article import Article, ArticleError, new_article, parse_date, validate_structure
from ...core.groups import GroupRef, group_refs  # noqa: F401  (#172, for clients)
from ...core.groups import MAX_SUPERSEDES, parse_supersedes
from ...core.groups import (INBOX_NAME, INBOX_SCHEME, INBOX_SCHEMES, KIND_CHAT, KIND_POST, MAX_RULES, VIEWS, decrypt_article,
                           encrypted_article, encryption_epoch, inbox_article, make_key_update,
                           make_group_id, make_manifest, manifest_article, message_kind, open_envelope,
                           open_inbox_article, personal_inbox_id, short_group_id, split_group_id,
                           EXTRA_FIELDS, check_extra_fields)
from ...core.groups import _comments  # UN-RFC 0030 field check
from ...core.groups import (FIRST_LIFETIME, FIRST_RENEW_WHEN_LEFT, MAX_LIFETIME, RENEW_WHEN_LEFT,
                           RENEW_WINDOW, is_key_bound, stored_expires)
from ...core import profiles as prof
from ...core.tor import (BRIDGE_MODES, Socks, TorError, TorProcess, bridges_for, check_socks,
                        existing_tor, parse_socks)
from ...core.vault import Vault
from ...nntp import Client, NNTPError
from ... import names
from .. import naming
from ..threads import CONTACT, FEED_DEPTH, FOR_YOU, TIMELINE, feed_threaded, threaded
from .. import events as ev
from ...core import pow as postage
from ...core import ripening as rp

DEFAULT_POW = 20
MAX_READ_MARKS = 5000
MAX_SENT_COPIES = 100             # sent posts findable from other devices, in the state (0044, 6.2)
MAX_CACHED_PER_GROUP = 2000
SIG_SEPARATOR = "-- \n"         # the Usenet signature delimiter (RFC 3676, 4.3): dash dash space
MAX_SIG_LINES = 4               # the old netiquette limit
DEFAULT_SIGNATURE = "{name}  ·  {key}"   # until you set your own; empty means none
CACHE_SIDECAR = "cache"
DICT_VERSION = 1                # the shape of Message.to_dict() and GroupInfo.to_dict()
SENT_SIDECAR = "sent"           # where older vaults kept copies of private posts you sent

log = logging.getLogger(__name__)


class ForYouCount(NamedTuple):
    """Unread posts for you: replies to your posts and posts naming you (#109, #170)."""
    replies: int = 0
    mentions: int = 0

    @property
    def total(self) -> int:
        return self.replies + self.mentions



def resolve_edits(msgs: list[Message]) -> list[Message]:
    """Show only the newest version of each edited post, in the first version's place,
    marked edited, with replies to any version under it (UN-RFC 0042 sections 4-5).

    An edit counts only if every earlier version present is by the same author, in
    the same group and of the same kind (section 4.1); otherwise it is shown as an
    ordinary post and replaces nothing - a node is not trusted for this. Two edits of
    the same post: the later Date wins, on a tie the lower Message-ID (5.2). The
    messages given are not changed; shown ones are copies."""
    by_id = {m.message_id: m for m in msgs}
    posts: dict[str, list[Message]] = {}           # first version -> its valid edits
    for e in msgs:
        if not e.supersedes or e.private:
            continue
        ok = True
        for v in e.supersedes:
            old = by_id.get(v)
            if old is not None and (old.author_key != e.author_key or old.group != e.group
                                    or old.private or (old.readable and e.readable
                                                       and old.kind != e.kind)):
                ok = False
                break
        if ok:
            posts.setdefault(e.supersedes[-1], []).append(e)
    if not posts:
        return list(msgs)
    canonical: dict[str, Message] = {}             # any replaced Message-ID -> shown edit
    for first, edits in posts.items():
        winner = max(edits, key=lambda e: (e.date or datetime.min.replace(tzinfo=timezone.utc),
                                           [-ord(c) for c in e.message_id]))
        ids = {first} | {v for e in edits for v in e.supersedes} | {e.message_id for e in edits}
        ids.discard(winner.message_id)
        present = [by_id[i] for i in ids if i in by_id] + [winner]
        # newest first and the first version last, as an edit of it must list them
        others = sorted(ids - set(winner.supersedes))
        shown = replace(winner, edited=winner.date, versions=others + list(winner.supersedes),
                        number=min(m.number for m in present))
        original = by_id.get(first)
        if original is not None and original.date is not None:
            shown.date = original.date              # where and when it was first posted
        for i in ids | {winner.message_id}:
            canonical[i] = shown
    out: list[Message] = []
    done: set[str] = set()
    for m in msgs:
        shown = canonical.get(m.message_id)
        if shown is not None:
            if shown.message_id not in done:
                done.add(shown.message_id)
                out.append(shown)
            continue
        out.append(m)
    for i, m in enumerate(out):                      # replies to any version: under the shown one
        refs = [canonical[r].message_id if r in canonical else r for r in m.references]
        if refs != m.references:
            out[i] = replace(m, references=refs)
    return out

def _needed_bits(text: str) -> int:
    """N from a node's "postage: need N bits", 0 if it says something else."""
    m = re.search(r"need (\d+) bits", text)
    return int(m.group(1)) if m else 0


class SessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Permission:
    """Whether you may write somewhere, and if not, the reason to show (#181)."""
    allowed: bool
    reason: str = ""
    code: str = "ok"     # own_inbox, kind, banned, blocked, not_member, channel,
                         # channel_thread, comments_closed

    def __bool__(self) -> bool:
        return self.allowed


@dataclass
class Message:
    number: int
    message_id: str
    group: str
    subject: str = ""
    from_name: str = ""
    author_key: str = ""
    date: datetime | None = None
    body: str = ""
    references: list[str] = field(default_factory=list)
    encrypted: bool = False
    readable: bool = True
    error: str | None = None
    raw: bytes = field(default=b"", repr=False)
    private: bool = False                 # an inbox message (UN-RFC 0009)
    private_profile: bool = False         # a profile shared with you or the group (0022, 6)
    sender_key: str | None = None         # verified sender of a private message
    reply_inbox: str | None = None
    to_key: str | None = None             # a private message you sent: its recipient
    content_type: str = ""                # private messages: the inner Content-Type
    kind: str = KIND_POST               # private messages: a chat or a post (UN-RFC 0028)
    mention_group: str | None = None      # a mention notice: where the post is (UN-RFC 0032)
    mention_of: str | None = None         # ... and its Message-ID
    notices_for: str | None = None        # a bundle of notices for a submission (0032, 4.3)
    supersedes: list[str] = field(default_factory=list)   # an edit: earlier versions (0042)
    edited: datetime | None = None        # shown version is an edit, made then (0042, 4.2)
    versions: list[str] = field(default_factory=list)     # earlier versions this one replaced
    sender_ripening: str | None = None    # a private post: the sender's Key-Ripening (0025, 3.5)
    page: str | None = None               # a page article of a site: its path (UN-RFC 0035)
    page_removed: bool = False            # ... a removal of that path
    blobs: tuple = ()                     # the blob IDs it carries (UN-RFC 0027, Blobs)
    attachments: tuple = ()               # ... as shown: blob, type, size, name, alt, dim (4.2)
    # encrypted files (closed groups, inboxes): each file's key by blob ID (0027, 3.3);
    # never shown or sent anywhere
    file_keys: dict = field(default_factory=dict, repr=False)

    @property
    def author_fp(self) -> str:
        try:
            return crypto.fingerprint(crypto.key_from_text(self.author_key))[:4]
        except crypto.CryptoError:
            return "????"

    @property
    def thread_root(self) -> str:
        return self.references[0] if self.references else self.message_id

    def to_dict(self) -> dict:
        """The message as plain JSON-safe data, shape ``DICT_VERSION`` (#139).

        Dates are ISO 8601 strings, the raw article is left out, and the body
        is also given split into ``text`` and ``signature``. How a name or a
        key is shown is the client's: this holds only what the message says.
        """
        text, sig = split_signature(self.body) if self.readable else ("", None)
        return {
            "v": DICT_VERSION, "id": self.message_id, "number": self.number,
            "group": self.group, "subject": self.subject, "from_name": self.from_name,
            "author_key": self.author_key, "date": _iso(self.date), "body": self.body,
            "text": text.rstrip("\n"), "signature": (sig or "").rstrip("\n") or None,
            "references": list(self.references), "thread_root": self.thread_root,
            "kind": self.kind, "content_type": self.content_type,
            "encrypted": self.encrypted, "readable": self.readable, "error": self.error,
            "private": self.private, "sender_key": self.sender_key,
            "reply_inbox": self.reply_inbox, "to_key": self.to_key,
            "mention_group": self.mention_group, "mention_of": self.mention_of,
            "supersedes": list(self.supersedes), "edited": _iso(self.edited),
            "versions": list(self.versions),
            "attachments": [dict(a) for a in self.attachments],
        }


@dataclass
class GroupInfo:
    group_id: str
    description: str = ""
    type: str | None = None
    owner_key: str | None = None
    subscribed: bool = False
    nodes: list[str] = field(default_factory=list)   # the nodes that carry it, yours first
    # filled in by Session.subscribed_groups() (#139); None where not known
    title: str = ""
    view: str = "threads"                 # what you see: threads, chat or data
    owner_view: str = "threads"           # what the owner chose (UN-RFC 0008, 3.1)
    kinds: tuple[str, ...] = ()           # what it takes: chat lines, posts (UN-RFC 0028)
    local: bool = False                   # lives on one node only (UN-RFC 0015)
    low_latency: bool = False
    owner: bool = False                   # you own it
    listed: bool | None = None            # carried by your nodes; None while offline
    unread: int | None = None
    replies: int | None = None            # unread replies to you
    mentions: int | None = None           # unread posts naming you

    @property
    def short(self) -> str:
        """The ID with a shortened fingerprint; a pseudo group (``for-you:``,
        ``contact:<key>``, threads.py) has no fingerprint and keeps its ID."""
        try:
            return short_group_id(self.group_id)
        except ValueError:
            return self.group_id

    @property
    def label(self) -> str:
        """The name without the owner fingerprint, e.g. ``dk.snak``."""
        return self.group_id.rpartition("@")[0] or self.group_id

    @property
    def hierarchy(self) -> str:
        """The first part of the name, as on Usenet: ``dk`` for ``dk.snak``."""
        return self.label.split(".", 1)[0]

    def to_dict(self) -> dict:
        """The group as plain JSON-safe data, shape ``DICT_VERSION`` (#139)."""
        return {
            "v": DICT_VERSION, "id": self.group_id, "short": self.short, "label": self.label,
            "hierarchy": self.hierarchy, "title": self.title, "description": self.description,
            "type": self.type, "owner_key": self.owner_key, "owner": self.owner,
            "subscribed": self.subscribed, "nodes": list(self.nodes), "listed": self.listed,
            "view": self.view, "owner_view": self.owner_view, "kinds": list(self.kinds),
            "local": self.local, "low_latency": self.low_latency,
            "unread": self.unread, "replies": self.replies, "mentions": self.mentions,
        }


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


def art_body_text(body: str) -> str:
    """A body as it will appear in an article (LF endings, one final newline)."""
    body = body.replace("\r\n", "\n")
    return body if body.endswith("\n") else body + "\n"


def split_signature(body: str) -> tuple[str, str | None]:
    """Split a body into (text, signature). The signature follows the last '-- ' line."""
    if body.startswith(SIG_SEPARATOR):
        return "", body[len(SIG_SEPARATOR):]
    idx = body.rfind("\n" + SIG_SEPARATOR)
    if idx < 0:
        return body, None
    return body[:idx + 1], body[idx + 1 + len(SIG_SEPARATOR):]


def strip_reader_headers(raw: bytes) -> bytes:
    """Remove Path/Xref synthesized by the node for newsreaders (UN-RFC 0005, 3)."""
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = [ln for ln in head.split(b"\r\n") if not ln.lower().startswith((b"path:", b"xref:"))]
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


SUBMISSION_TYPE = "message/unseenet"      # UN-RFC 0009 section 3
REPORT_TYPE = "text/x-unseenet-report"    # a report of a post (#74)
MENTION_TYPE = "text/x-unseenet-mention"  # a mention notice (UN-RFC 0032)
NOTICES_TYPE = "application/x-unseenet-notices"   # notices sent with a submission (0032, 4.3)
MAX_MENTION_NOTICES = 5                   # per post (UN-RFC 0032, section 4.1)
# @name, @domain.tld, local@name, local@domain.tld (UN-RFC 0019, section 4); not part of
# a word, an address or a #group@fp reference
NAME_MENTION_RE = re.compile(
    r"(?<![\w@#.+-])(?:([a-z0-9][a-z0-9-]*))?@([a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)*)"
    r"(?![\w@-]|\.\w)", re.IGNORECASE)


def default_vault_path() -> Path:
    """``unseenet.vault`` in the current directory, or in ``data/`` of a portable build."""
    from ...portable import default_vault_path as portable_default
    return portable_default()


# every name above, for the parts below (`from . import *`), underscored ones too
__all__ = [n for n in dir() if not n.startswith('__')]

from .base import BaseMixin  # noqa: E402
from .ripening import RipeningMixin  # noqa: E402
from .nodes import NodesMixin  # noqa: E402
from .labels import LabelsMixin  # noqa: E402
from .groups import GroupsMixin  # noqa: E402
from .private import PrivateMixin  # noqa: E402
from .profiles import ProfilesMixin  # noqa: E402
from .people import PeopleMixin  # noqa: E402
from .reading import ReadingMixin  # noqa: E402
from .posting import PostingMixin  # noqa: E402
from .attachments import AttachmentsMixin, FileUnavailable  # noqa: E402,F401
from .kept import KeptMixin  # noqa: E402
from .personal import PersonalMixin  # noqa: E402
from .following import FollowingMixin  # noqa: E402
from .state import StateMixin  # noqa: E402


class Session(BaseMixin, RipeningMixin, NodesMixin, LabelsMixin, GroupsMixin, PrivateMixin, ProfilesMixin, PeopleMixin, ReadingMixin, PostingMixin, AttachmentsMixin, KeptMixin, PersonalMixin, FollowingMixin, StateMixin):
    """One person's (or one service's) client: the vault, the network, groups,
    posting. Split into parts by area (client/session/*.py, #390); clients use
    this one class as before."""
