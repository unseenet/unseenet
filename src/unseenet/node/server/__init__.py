"""The node: an ONNTP server that stores groups and passes articles on (UN-RFC 0005).

``Node`` takes articles and keeps them; ``Session`` is one connection to it. Both are
joined here from parts, one file per area:

  Node                                    Session (one connection)
    node.py        the node, serving        connection.py        command loop, CAPABILITIES
    accepting.py   the accept pipeline      auth_commands.py     AUTHINFO, XUN-PEER
    postage.py     postage, ripening        lists_commands.py    LIST, XUN-WATCH, node info
    manifests.py   manifests, groups        reading_commands.py  GROUP, ARTICLE, OVER, HDR
    controls.py    key updates, cancels     peering_commands.py  IHAVE, TAKETHIS, NEWNEWS,
    kept.py        pins and pages                                XUN-RECONCILE, XUN-MANIFESTS
    blobs.py       blobs                    posting_commands.py  POST
    blocks.py      maintainers' blocks      blob_commands.py     BLOBPOST, BLOB
                                            meet_commands.py     XUNMEET (UN-RFC 0050)
    edits.py       edits (Supersedes)
    forwarding.py  queueing for peers

The rules for one kind of article go in its file; ``accepting.py`` only decides the
order. A new NNTP command is a ``cmd_<name>`` method in the commands file of its area.
This file holds what all parts share: imports, ``NodeConfig``, ``PeerConfig``,
constants and helpers. Names tests patch on this module are read through it
(``_s.NAME``); ``unseenet.node.server`` is still the module everybody imports.
"""

from __future__ import annotations

import asyncio
from email.utils import format_datetime
import fnmatch
from pathlib import Path
import hashlib
import hmac
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ... import __version__
from ...core.groups import canonical_json, parse_canonical_json
from ...core import crypto, profiles, reconcile
from ...core.groups import split_group_id
from ...core.article import MAX_SIZE, Article, ArticleError, parse_date, validate_structure
from ...core.groups import message_kind, parse_supersedes
from ...core.groups import (INBOX_SCHEME, INBOX_SCHEMES, KEY_BOUND_MANIFEST_MAX, Manifest, check_permitted,
                           is_key_bound, make_group_id, parse_key_update, split_group_id)
from ...core import blobs as bl
from ...core import pages as pg
from ...core import pins as pn
from ...core import reactions as rx
from ...core import ripening as rp
from ...core.store import Store
from ...nntp import (MANIFESTS_ANSWER_BYTES, MANIFESTS_MAX, MAX_LINE, RECONCILE_MAX_BYTES,
                    dot_stuff, read_block)
from ..stats import Stats

log = logging.getLogger("unseenet.node")


@dataclass
class PeerConfig:
    name: str
    address: str                # "xyz.onion" or "host:port" (testing)
    groups: str = "*"           # RFC 3977 wildmat over Group IDs
    key: str | None = None      # the peer's node key, "ed25519:..." (UN-RFC 0016)
    pull: str = "*"             # wildmat of groups to catch up on from this peer (UN-RFC 0017)
    accept: str = "*"           # wildmat of groups to take from this peer, pushed or pulled
    password: str | None = None  # legacy shared secret for AUTHINFO

    def public_key(self) -> bytes | None:
        return crypto.key_from_text(self.key) if self.key else None


BLOB_WAIT_SECONDS = 600.0      # UN-RFC 0027 6.3: forward without the blobs after this
POST_PAST = timedelta(hours=1)  # UN-RFC 0049 3.2: a POST's Date at most this far back
BACKFILL_MAX = 5000            # #543: stored articles whose files are fetched per start


@dataclass
class NodeConfig:
    name: str = "unseenet"              # how this node introduces itself to peers
    max_size: int = MAX_SIZE
    min_pow: int = 18
    # UN-RFC 0025 section 5: the lowest level accepted; None is "-" (no ripening needed)
    min_ripe: int | None = field(default_factory=lambda: rp.DEFAULT_MIN_RIPE)
    retention_days: int = 90
    new_groups: str = "accept"            # "accept" | "trusted" | "manual"
    trusted_owners: list[str] = field(default_factory=list)
    peers: list[PeerConfig] = field(default_factory=list)
    forward_delay: tuple[float, float] = (0.0, 60.0)  # UN-RFC 0005, section 5.5
    require_peer_auth: bool = False
    excludes: str = ""                   # wildmat of groups not carried by choice (UN-RFC 0021)
    pull_interval: float = 3600.0        # seconds between catch-up pulls (UN-RFC 0017)
    honour_blocks: bool = False          # UN-RFC 0018 section 8.2: maintainers' blocks
    profiles: str = "accept"             # UN-RFC 0022 section 10: carry profile@ groups
    avatars: str = "refuse"              # ... and avatar@ groups: images, so off by default
    sites: str = "refuse"                # UN-RFC 0035 6.2: sites stay, so off by default
    # UN-RFC 0011: who runs this node and how to reach them
    operator: dict = field(default_factory=dict)   # key, contact, description, logging
    # open client connections at most (#296): a ceiling, not rationing; peers don't count
    max_clients: int | str = "auto"
    # UN-RFC 0027 section 8: blobs are carried only when the operator turns them on.
    # None: off. Otherwise {"max_size", "retention_days", "encrypted", "groups"}.
    blobs: dict | None = None

    def carries_blobs(self, group_id: str, encrypted: bool = False) -> bool:
        b = self.blobs
        return (b is not None and wildmat(b.get("groups", "*"), group_id)
                and (not encrypted or bool(b.get("encrypted", False))))

    @property
    def max_blob(self) -> int:
        return int((self.blobs or {}).get("max_size", bl.MIN_NODE_BLOB))

    def client_limit(self) -> int:
        """``max_clients`` as a number: ``"auto"`` is what memory and open files allow."""
        return self.max_clients if isinstance(self.max_clients, int) else auto_max_clients()


CLIENT_BYTES = 50 * 1024             # what a client connection costs, generously (#296)
FULL_ALLOWED = {"CAPABILITIES", "AUTHINFO", "XUN-PEER", "XUN-PEER-PROOF"}


def auto_max_clients() -> int:
    """min((available memory - 100 MB) / 50 KB, (open files - 128) / 2): tens of
    thousands on a small VM; where neither can be read, 10 000."""
    limits = []
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                avail = int(line.split()[1]) * 1024
                limits.append(max(0, avail - 100 * 1024 * 1024) // CLIENT_BYTES)
    except (OSError, ValueError, IndexError):
        pass
    try:
        import resource
        soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft != resource.RLIM_INFINITY:
            limits.append(max(0, soft - 128) // 2)
    except (ImportError, OSError, ValueError):
        pass
    return max(16, min(limits)) if limits else 10_000


def wildmat(pattern: str, text: str) -> bool:
    """RFC 3977 wildmat: comma-separated patterns, '!' negates, last match wins."""
    result = False
    for pat in pattern.split(","):
        neg = pat.startswith("!")
        if fnmatch.fnmatchcase(text, pat[1:] if neg else pat):
            result = not neg
    return result


# every name above, for the parts below (`from . import *`), underscored ones too
__all__ = [n for n in dir() if not n.startswith('__') or n == '__version__']

from .node import NodeBase  # noqa: E402
from .accepting import Accepting  # noqa: E402
from .postage import Postage  # noqa: E402
from .manifests import Manifests  # noqa: E402
from .controls import Controls  # noqa: E402
from .kept import Kept  # noqa: E402
from .blobs import Blobs  # noqa: E402
from .blocks import Blocks  # noqa: E402
from .edits import Edits  # noqa: E402
from .forwarding import Forwarding  # noqa: E402
from .connection import ConnectionBase  # noqa: E402
from .auth_commands import AuthCommands  # noqa: E402
from .lists_commands import ListsCommands  # noqa: E402
from .reading_commands import ReadingCommands  # noqa: E402
from .peering_commands import PeeringCommands  # noqa: E402
from .posting_commands import PostingCommands  # noqa: E402
from .blob_commands import BlobCommands  # noqa: E402
from .meet_commands import MeetCommands  # noqa: E402


class Node(NodeBase, Accepting, Postage, Manifests, Controls, Kept, Blobs, Blocks, Edits, Forwarding):
    """A node: takes articles from clients and peers, keeps them, passes them on.
    Split into parts by area (node/server/*.py, see above)."""


class Session(ConnectionBase, AuthCommands, ListsCommands, ReadingCommands, PeeringCommands, PostingCommands, BlobCommands, MeetCommands):
    """One ONNTP connection to a node, from a client or a peer. Split into parts
    by area (node/server/*_commands.py, see above)."""
