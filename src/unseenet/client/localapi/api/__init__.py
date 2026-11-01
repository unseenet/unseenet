"""What the local client API does (UN-RFC 0046), without the web server.

``LocalAPI`` holds one session - a person's unlocked vault, or a service's key (section
3.2) - with its ``ClientRuntime``, and answers every request of UN-RFC 0046 section 4
as plain JSON-safe data. ``server.py`` puts it behind HTTP and a WebSocket; a test or
another transport can call it directly. Every front end - the GUI, a screen-reader
client, a bot in another language - gets the same behaviour.

The code follows the sections of UN-RFC 0046, one file each:

    base.py       LocalAPI.__init__: the session and its runtime
    state.py      4.1  state, pausing ripening, about, emoji
    setup.py      4.2  unlocking and setting up
    groups.py     4.3  groups you follow, one group's posts, browsing
    writing.py    4.4, 4.5  posting, private posts, edits and withdrawals as jobs
    people.py     4.6  contacts, ignoring, reporting, blocking
    running.py    4.7  groups you run: settings, members, roles, bans, moderation
    identity.py   4.8  profiles, names, the passphrase, settings
    articles.py   4.9  articles and manifests from a program
    files.py      4.10 files on posts: pictures to show, files to save, files to post
    pictures.py   4.11 pictures and identicons of people, and your own picture
    nodes.py      4.17 your nodes: by name, add, remove, the default
    recovery.py   4.18 recovery words: showing, checking, restoring (UN-RFC 0050)
    copying.py    4.19 copying to another device (UN-RFC 0050)
    rules.py      4.20 your own rules (UN-RFC 0051)
    reports.py    spam reports: issuers, hidden posts, issuing (UN-RFC 0045)
    teams.py      team inboxes: reading with others, readers, invitations (UN-RFC 0047)
    events.py     5    events over the WebSocket

A new request goes in the file of its section (and a route in ``server.py``); a new
section of the RFC gets a file of its own, added to ``LocalAPI`` below. This file holds
what all parts share: imports, constants, ``Locked``, ``NotFound`` and helpers.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import timedelta
from pathlib import Path

from .... import __version__
from .... import names as nm
from ....core import about as about_text
from ....core import crypto
from ....core import markup
from ....core import profiles as prof
from ....core import ripening as rp
from ....core.groups import (KIND_CHAT, KIND_POST, group_refs, manifest_article, message_kind,
                            personal_inbox_id)
from ....core.vault import Vault, VaultError
from ... import events as ev
from ... import naming
from ...grouptree import group_tree
from ...runtime import NETWORK_ERRORS, RIPEN_TO, SERVICE_RIPEN_TO, ClientRuntime, service_ripen_to
from ...session import MAX_MENTION_NOTICES, REPORT_REASONS, GroupInfo, Message, Session, SessionError
from ...threads import CONTACT, FOR_YOU, TAGGED, TIMELINE

API_VERSION = 1
MAX_READ = 500                  # ids per read request
MAX_REFERENCES = 50
GROUP_TYPES = ("open", "moderated", "channel", "closed")
KINDS = {"both": None, "post": [KIND_POST], "chat": [KIND_CHAT]}
SETTINGS_FIELDS = ("title", "description", "charter", "charter_type", "view", "kinds",
                   "low_latency", "min_pow", "retention_days", "comments", "comment_days",
                   "files", "reactions", "index",
                   "report_issuers", "team_name",     # UN-RFC 0045 7.5, UN-RFC 0047 3
                   "tags",                            # the group's tags (UN-RFC 0052 section 5)
                   "labellers",                       # labellers named here (UN-RFC 0053, 5)
                   "languages")                       # written here (UN-RFC 0052, 5a)
FIXED_FIELDS = ("type", "owner", "name", "local")      # never change (UN-RFC 0004, 4)
PROGRAM_HEADERS = ("x-", "gateway-")                   # what a program may add (section 4.9)


class Locked(Exception):
    """409: unlock (or set up) first."""


class NotFound(Exception):
    """404: no such group or post."""


class Status(Exception):
    """An answer with its own status and fields: ``Status(text, 503, later=True)``."""

    def __init__(self, text: str, status: int, **fields):
        super().__init__(text)
        self.status, self.fields = status, fields


def _identicon(key: str | None) -> dict | None:
    """A key's identicon for a front end to draw (UN-RFC 0022 section 8.4): ``hue``,
    the 5 x 5 ``cells`` (row by row), and ``colour`` at lightness 50 %."""
    try:
        icon = prof.identicon(crypto.key_from_text(key or ""))
    except (crypto.CryptoError, ValueError):
        return None
    return {"hue": icon.hue, "cells": [list(r) for r in icon.cells], "colour": icon.hex()}


def _perm(p) -> dict:
    """``Session.write_permission`` for a front end: greyed out, with the reason (#181)."""
    return {"allowed": bool(p.allowed), "reason": p.reason, "code": p.code}


def _key(text) -> str:
    text = str(text or "").strip()
    crypto.key_from_text(text)                     # raises ValueError on a bad key
    return text


def _kind(data: dict) -> str:
    kind = str(data.get("kind", KIND_POST))
    if kind not in (KIND_POST, KIND_CHAT):
        raise SessionError("kind is post or chat")
    return kind


# every name above, for the parts (`from . import *`), underscored ones too
__all__ = [n for n in dir() if not n.startswith('__') or n == '__version__']

from .base import ApiBase  # noqa: E402
from .events import Events  # noqa: E402
from .setup import DeviceUnlock, Setup  # noqa: E402
from .state import State  # noqa: E402
from .groups import Groups  # noqa: E402
from .writing import Writing  # noqa: E402
from .people import People  # noqa: E402
from .running import Running  # noqa: E402
from .identity import Identity  # noqa: E402
from .articles import Articles  # noqa: E402
from .files import Files  # noqa: E402
from .pictures import Pictures  # noqa: E402
from .addresses import Addresses  # noqa: E402
from .feeds import Feeds  # noqa: E402
from .pages import Pages  # noqa: E402
from .nodes import AnnouncedNodes, Nodes  # noqa: E402
from .recovery import Recovery  # noqa: E402
from .copying import Copying  # noqa: E402
from .rules import Rules  # noqa: E402
from .reports import Reports  # noqa: E402
from .teams import Teams  # noqa: E402
from .content_labels import ContentLabels  # noqa: E402
from .group_emoji import GroupEmoji  # noqa: E402
from .shares import Shares  # noqa: E402


class LocalAPI(ApiBase, Events, Setup, DeviceUnlock, State, Groups, Writing, People, Running, Identity, Articles,
               Files, Pictures, Addresses, Feeds, Pages, Nodes, AnnouncedNodes, Recovery, Copying, Rules,
               Reports, Teams, ContentLabels, GroupEmoji, Shares):
    """One runtime for UN-RFC 0046. Give it a vault path (a person's client) or
    a session made with ``Session.from_key`` and ``service=True`` (a bot or
    gateway, section 3.2).

    Split by section of UN-RFC 0046 (client/localapi/api/*.py, see above)."""
