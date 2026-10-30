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
    reactions.py  reactions under articles: counting, reacting (UN-RFC 0048)
    recovery.py   recovery words: showing, reminding, restoring (UN-RFC 0050 section 4)
    copying.py    copying identities to another device (UN-RFC 0050 section 3)
    queue.py      a posting queue: many posts paced by postage, ripening, quotas
    notify.py     what new has landed in For you, for a client to tell
    exporting.py  your data as a file (UN-RFC 0049 section 7)
    rules.py      your own rules for your feed and groups (#615)
    reports.py    spam reports: issuers you follow, hidden posts, issuing (UN-RFC 0045)
    teams.py      team inboxes: readers, invitations, replying on an inbox's behalf (0047)

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
from ...core.groups import (INBOX_NAME, INBOX_SCHEME, INBOX_SCHEMES, INBOX_SCHEME_TEAM, KIND_CHAT, KIND_POST, MAX_CHARTER, VIEWS, decrypt_article, with_charter,
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
from ..threads import CONTACT, FEED_DEPTH, FOR_YOU, TAGGED, TIMELINE, feed_threaded, threaded
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
        # the current version is one no other valid version names (5.2); of several,
        # the latest Date, on a tie the lower Message-ID - two quick edits in the
        # same second must not bring back the older one (#733)
        named = {v for e in edits for v in e.supersedes}
        current = [e for e in edits if e.message_id not in named] or edits
        winner = max(current, key=lambda e: (e.date or datetime.min.replace(tzinfo=timezone.utc),
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
        days = [m.comment_days for m in present if m.comment_days is not None]
        shown.comment_days = min(days) if days else None   # an edit only shortens (0030 3.1)
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
    reaction: str = ""                    # kind reaction: its emoji (UN-RFC 0048)
    mention_group: str | None = None      # a mention notice: where the post is (UN-RFC 0032)
    mention_of: str | None = None         # ... and its Message-ID
    notices_for: str | None = None        # a bundle of notices for a submission (0032, 4.3)
    # a share (UN-RFC 0060): the article it refers to, by Message-ID and group; a plain
    # share is kind "share". ``sharing_no``: the author asked not to share it (4.4).
    # ``shared_by``: set by the timeline - who shared it, among those you follow (5.4)
    share_of: str | None = None
    share_group: str | None = None
    sharing_no: bool = False
    shared_by: list = field(default_factory=list)
    # a share notice (UN-RFC 0060 section 8): the share that shared your post, and where
    shared_as: str | None = None
    shared_in: str | None = None
    supersedes: list[str] = field(default_factory=list)   # an edit: earlier versions (0042)
    edited: datetime | None = None        # shown version is an edit, made then (0042, 4.2)
    versions: list[str] = field(default_factory=list)     # earlier versions this one replaced
    sender_ripening: str | None = None    # a private post: the sender's Key-Ripening (0025, 3.5)
    page: str | None = None               # a page article of a site: its path (UN-RFC 0035)
    page_removed: bool = False            # ... a removal of that path
    blobs: tuple = ()                     # the blob IDs it carries (UN-RFC 0027, Blobs)
    attachments: tuple = ()               # ... as shown: blob, type, size, name, alt, dim (4.2)
    card: object | None = None            # its link card, checked (UN-RFC 0059): core.cards.Card
    # first published elsewhere (UN-RFC 0049 section 4): the network, its date (the
    # author's or gateway's claim), the other network's ID and author
    origin_network: str = ""
    origin_date: datetime | None = None
    origin_id: str = ""
    origin_from: str = ""
    origin_proven: str = ""               # the old key, when Origin-Proof holds (0049 7.3)
    # encrypted files (closed groups, inboxes): each file's key by blob ID (0027, 3.3);
    # never shown or sent anywhere
    file_keys: dict = field(default_factory=dict, repr=False)
    node: str = ""                        # the node it was read from (a local group: #134)
    comment_days: int | None = None       # a thread root's own time for comments (0030 3.1)
    tags: tuple = ()                      # the author's own tags (UN-RFC 0052)
    languages: tuple = ()                 # Content-Language, the author's (UN-RFC 0052 5a)
    labels: dict | None = None            # warnings and topics, what to do (UN-RFC 0053)
    # written on a team inbox's behalf (UN-RFC 0047 section 8): {"group"}; checked with
    # Session.team_sender. And a team key handed to you: {"group", "seed"} (section 6)
    team: dict | None = None
    team_invite: dict | None = field(default=None, repr=False)
    # hidden by a spam report from an issuer you follow (UN-RFC 0045 section 7.3): who,
    # why and which report - set by ``Session.visible``; clients show it in its place
    reported: dict | None = None

    @property
    def old_on_arrival(self) -> bool:
        """First published more than 24 hours before it came into the network (UN-RFC 0049
        section 5.2): not new, no notification, not in For you."""
        from ...core.origins import old_on_arrival
        return old_on_arrival(self.origin_date, self.date)

    @property
    def sort_date(self) -> datetime | None:
        """What it is ordered by in feeds, the timeline and threads (UN-RFC 0049 5.3)."""
        return self.origin_date or self.date

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
            # UN-RFC 0060: what it shares, whether it may be shared, who shared it
            "share": ({"of": self.share_of, "group": self.share_group,
                       "plain": self.kind == "share"} if self.share_of else None),
            "sharing": "no" if self.sharing_no else None,
            "shared_by": list(self.shared_by),
            "share_notice": ({"of": self.share_of, "group": self.share_group,
                              "as": self.shared_as, "in": self.shared_in}
                             if self.shared_as else None),
            "supersedes": list(self.supersedes), "edited": _iso(self.edited),
            "versions": list(self.versions),
            "attachments": [dict(a) for a in self.attachments],
            # UN-RFC 0059: the link card, its picture being the attachment marked "card"
            "card": self.card.to_dict() if self.card else None,
            # UN-RFC 0049: where it was first published, and whether it is old on arrival
            "origin": ({"network": self.origin_network, "date": _iso(self.origin_date),
                        "id": self.origin_id or None, "from": self.origin_from or None,
                        "proven": self.origin_proven or None}
                       if self.origin_network else None),
            "old_on_arrival": self.old_on_arrival,
            # UN-RFC 0045 section 7.3: hidden by a report - who, why, which report
            "reported": dict(self.reported) if self.reported else None,
            "node": self.node or None,                 # where it was read (#134)
            "tags": list(self.tags),                   # the author's (UN-RFC 0052 section 3)
            "languages": list(self.languages),         # Content-Language (0052 section 5a)
            "labels": self.labels,                     # warnings, topics, action (UN-RFC 0053)
            "team": dict(self.team) if self.team else None,    # on an inbox's behalf (0047)
            "team_invite": ({"group": self.team_invite["group"]} if self.team_invite else None),
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
    tags: tuple[str, ...] = ()            # the group's tags, its owner's (UN-RFC 0052, 5)
    languages: tuple[str, ...] = ()       # the languages written there (UN-RFC 0052, 5a)
    local: bool = False                   # lives on one node only (UN-RFC 0015)
    low_latency: bool = False
    owner: bool = False                   # you own it
    listed: bool | None = None            # carried by your nodes; None while offline
    read_from: list[str] = field(default_factory=list)   # a local group: your nodes read (#134)
    # a team inbox you read with a team key (UN-RFC 0047): its name, and whether you still do
    team: dict | None = None
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
            "tags": list(self.tags),                   # the group's tags (UN-RFC 0052 section 5)
            "languages": list(self.languages),         # its languages (section 5a)
            "local": self.local, "low_latency": self.low_latency,
            "read_from": list(self.read_from),       # a local group: your nodes read (#134)
            "team": dict(self.team) if self.team else None,   # {"name", "reader"} (0047)
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
REPORT_TYPE = "text/x-unseenet-report"    # a report of a post (#74), plain text, as before
# a report written in Markdown, with files: Markdown that says it is a report (gui#70)
REPORT_MD_TYPE = "text/markdown; charset=utf-8; variant=unseenet; report=post"
# why a post is reported, as every client's report action offers it - derived from the one
# list in core (UN-RFC 0045 section 4, #659), never a second list
from ...core.reports import READER_REASONS as _READER_REASONS, REASON_LABELS as _REASON_LABELS  # noqa: E402
REPORT_REASONS = {k: _REASON_LABELS[k] for k in _READER_REASONS}


def is_report_type(content_type: str | None) -> bool:
    """A report of a post: the plain-text type of #74, or Markdown with ``report=post``."""
    ct = (content_type or "").lower()
    if ct.startswith(REPORT_TYPE):
        return True
    base, *params = [p.strip() for p in ct.split(";")]
    return base == "text/markdown" and "report=post" in params
MENTION_TYPE = "text/x-unseenet-mention"  # a mention notice (UN-RFC 0032)
NOTICES_TYPE = "application/x-unseenet-notices"   # notices sent with a submission (0032, 4.3)
MAX_MENTION_NOTICES = 5                   # per post (UN-RFC 0032, section 4.1)
# @name, @domain.tld, local@name, local@domain.tld (UN-RFC 0019, section 4); not part of
# a word, an address or a #group@fp reference
NAME_MENTION_RE = re.compile(
    r"(?<![\w@#.+-])(?:([a-z0-9][a-z0-9-]*))?@([a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)*)"
    r"(?![\w@-]|\.\w)", re.IGNORECASE)


def short_node(address: str) -> str:
    """A node address in a few characters: ``f6vnchi5….onion``, or ``host:port`` as it is."""
    host = address.strip().split(":")[0]
    return host[:8] + "….onion" if host.endswith(".onion") else address.strip()


NODE_NAME_MAX = 64


def clean_node_name(name) -> str | None:
    """A node's own name (UN-RFC 0011) made safe to show: one line, no control or
    format characters, at most ``NODE_NAME_MAX`` characters. None if nothing is left."""
    import unicodedata
    if not isinstance(name, str):
        return None
    text = "".join(ch for ch in name if unicodedata.category(ch)[0] not in "CZ" or ch == " ")
    text = " ".join(text.split())[:NODE_NAME_MAX].strip()
    return text or None


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
from .reactions import ReactionsMixin  # noqa: E402
from .shares import SharesMixin  # noqa: E402
from .recovery import RecoveryMixin  # noqa: E402
from .copying import CopyingMixin, CopyOffer, CopyReceive  # noqa: E402,F401
from .queue import QueueMixin, PostingQueue  # noqa: E402,F401
from .notify import NotifyMixin  # noqa: E402
from .exporting import ExportMixin  # noqa: E402
from .rules import RulesMixin  # noqa: E402
from .reports import ReportsMixin  # noqa: E402
from .content_labels import ContentLabelsMixin  # noqa: E402
from .teams import TeamsMixin  # noqa: E402
from .group_emoji import GroupEmojiMixin  # noqa: E402
from .cards import CardsMixin, CardDraft, fetch_card  # noqa: E402,F401


class Session(BaseMixin, RipeningMixin, NodesMixin, LabelsMixin, GroupsMixin, PrivateMixin, ProfilesMixin, PeopleMixin, ReadingMixin, PostingMixin, AttachmentsMixin, KeptMixin, PersonalMixin, FollowingMixin, StateMixin, ReactionsMixin, SharesMixin, RecoveryMixin, CopyingMixin, QueueMixin, NotifyMixin, ExportMixin, RulesMixin, ReportsMixin, TeamsMixin, ContentLabelsMixin, GroupEmojiMixin, CardsMixin):
    """One person's (or one service's) client: the vault, the network, groups,
    posting. Split into parts by area (client/session/*.py, #390); clients use
    this one class as before."""
