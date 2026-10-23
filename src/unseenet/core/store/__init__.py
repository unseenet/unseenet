"""The node's store: articles, groups and their state in SQLite (and blobs on disk).

``Store`` is used by the node (``node.server``) and by tools that open a node's data
(``unseenet-node --drop-group``, ``--refuse-blob``). The schema is below; the code is
split by area:

    base.py         opening the store, the history of Message-IDs seen
    articles.py     storing, finding, deleting and expiring articles
    groups.py       manifests, carried groups, state, epochs, removal
    keybound.py     key-bound groups: lifetime and reconciliation sums
    kept.py         kept articles: pins and pages
    blobs.py        blob references, deletion, refusal, quotas
    withdrawals.py  cancels and edits
    peers.py        peer queues, pull and reconcile state
    stats.py        numbers for the operator's monitor

A new table goes in ``SCHEMA`` here, and its code in the file of its area (or a new
one, added to ``Store`` below). ``unseenet.core.store`` is still the module to import.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ..reconcile import FULL, MOD, item_hash, item_key, item_value
from .. import crypto
from ..article import Article, parse_date
from .. import blobs as bl
from .. import pages as pg
from .. import pins as pn
from ..groups import (KEY_BOUND_NAMES, MAX_LIFETIME, REMOVE_AFTER, Manifest, is_key_bound,
                     stored_expires)

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    message_id TEXT PRIMARY KEY,
    group_id   TEXT NOT NULL,
    number     INTEGER NOT NULL,
    date       INTEGER NOT NULL,   -- article Date, unix seconds
    received   INTEGER NOT NULL,   -- when this node got it, unix seconds
    author_key TEXT NOT NULL,
    raw        BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS articles_group ON articles(group_id, number);
CREATE INDEX IF NOT EXISTS articles_received ON articles(received);

CREATE TABLE IF NOT EXISTS history (
    message_id TEXT PRIMARY KEY,
    seen       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    group_id   TEXT PRIMARY KEY,
    manifest   TEXT NOT NULL,      -- JSON body of the current manifest
    manifest_id TEXT NOT NULL,
    serial     INTEGER NOT NULL,
    high       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS closed_epochs (     -- key updates with closes_previous (UN-RFC 0004, 6.2)
    group_id   TEXT NOT NULL,
    epoch      INTEGER NOT NULL,
    PRIMARY KEY (group_id, epoch)
);

CREATE TABLE IF NOT EXISTS epochs (
    group_id   TEXT NOT NULL,
    epoch      INTEGER NOT NULL,
    member_key TEXT NOT NULL,
    PRIMARY KEY (group_id, epoch)
);

CREATE TABLE IF NOT EXISTS cancels (
    target     TEXT PRIMARY KEY,
    author_key TEXT NOT NULL,
    group_id   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS supersedes (       -- UN-RFC 0042: an earlier version -> its edit
    old        TEXT PRIMARY KEY,
    new        TEXT NOT NULL,
    author_key TEXT NOT NULL,
    group_id   TEXT NOT NULL,
    kind       TEXT NOT NULL,
    first_date INTEGER                -- Date of the earliest version known, unix seconds
);
CREATE INDEX IF NOT EXISTS supersedes_new ON supersedes(new);

CREATE TABLE IF NOT EXISTS tombstones (       -- UN-RFC 0013
    group_id   TEXT PRIMARY KEY,
    at         INTEGER NOT NULL,
    reason     TEXT NOT NULL,                   -- "owner" or "operator"
    message_id TEXT,                            -- the rmgroup article, for owner removals
    raw        BLOB
);

CREATE TABLE IF NOT EXISTS epoch_articles (   -- key updates that define an epoch (UN-RFC 0017)
    group_id   TEXT NOT NULL,
    epoch      INTEGER NOT NULL,
    message_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS markers (          -- pins and unpins (UN-RFC 0033), kept-article markers
    message_id TEXT PRIMARY KEY,
    group_id   TEXT NOT NULL,
    target     TEXT NOT NULL,
    action     TEXT NOT NULL,                   -- "pin" or "unpin"
    author_key TEXT NOT NULL,
    date       INTEGER NOT NULL,                -- the marker's Date, unix seconds
    supersedes TEXT NOT NULL DEFAULT ''         -- the markers it replaces (UN-RFC 0033, 3.1)
);
CREATE INDEX IF NOT EXISTS markers_group ON markers(group_id);
CREATE INDEX IF NOT EXISTS markers_target ON markers(target);

CREATE TABLE IF NOT EXISTS blob_refs (        -- UN-RFC 0027 7.1: which articles reference a blob
    message_id TEXT NOT NULL,
    blob_id    TEXT NOT NULL,
    group_id   TEXT NOT NULL,
    size       INTEGER NOT NULL,
    PRIMARY KEY (message_id, blob_id)
);
CREATE INDEX IF NOT EXISTS blob_refs_blob ON blob_refs(blob_id);
CREATE TABLE IF NOT EXISTS blob_meta (         -- blobs this node stores, and since when
    blob_id    TEXT PRIMARY KEY,
    stored_at  INTEGER NOT NULL,
    size       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS refused_blobs (     -- UN-RFC 0027 7.3: by the operator or a list
    blob_id    TEXT PRIMARY KEY,
    at         INTEGER NOT NULL,
    reason     TEXT NOT NULL,
    source     TEXT NOT NULL                    -- "operator" or the list's author key
);
CREATE TABLE IF NOT EXISTS blob_usage (        -- UN-RFC 0027 8.1: octets accepted per day
    day        TEXT NOT NULL,
    kind       TEXT NOT NULL,                   -- "key" or "group"
    who        TEXT NOT NULL,
    octets     INTEGER NOT NULL,
    PRIMARY KEY (day, kind, who)
);

CREATE TABLE IF NOT EXISTS pages (            -- page articles of sites (UN-RFC 0035)
    message_id TEXT PRIMARY KEY,
    group_id   TEXT NOT NULL,
    path       TEXT NOT NULL,
    author_key TEXT NOT NULL,
    date       INTEGER NOT NULL,
    removed    INTEGER NOT NULL,
    supersedes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS pages_group ON pages(group_id);

CREATE TABLE IF NOT EXISTS pull_state (       -- UN-RFC 0017: how far we have pulled from a peer
    peer       TEXT PRIMARY KEY,
    since      INTEGER NOT NULL                 -- the peer's clock, unix seconds
);

CREATE TABLE IF NOT EXISTS refused (           -- pulled from a peer and refused (#132)
    message_id TEXT NOT NULL,
    peer       TEXT NOT NULL,
    reason     TEXT NOT NULL,
    at         INTEGER NOT NULL,
    PRIMARY KEY (message_id, peer)
);

CREATE TABLE IF NOT EXISTS peer_queue (
    peer       TEXT NOT NULL,
    message_id TEXT NOT NULL,
    not_before REAL NOT NULL,
    PRIMARY KEY (peer, message_id)
);

-- UN-RFC 0040 section 4: the key-bound state as items, ordered by key, with
-- running sums per key prefix so a range's fingerprint is a few lookups.
CREATE TABLE IF NOT EXISTS kb_items (
    key        BLOB PRIMARY KEY,                -- SHA-256(Group ID)
    group_id   TEXT NOT NULL UNIQUE,
    message_id TEXT NOT NULL,                   -- the current manifest
    h          BLOB NOT NULL,                   -- SHA-256(key || SHA-256(Message-ID))
    expires_at INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS kb_items_expires ON kb_items(expires_at);
CREATE TABLE IF NOT EXISTS kb_sums (            -- per level-nibble prefix of key, levels 0-4
    level      INTEGER NOT NULL,
    prefix     INTEGER NOT NULL,
    count      INTEGER NOT NULL,
    total      BLOB NOT NULL,                   -- sum of h mod 2^256, 32 octets big-endian
    PRIMARY KEY (level, prefix)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS kb_meta (built INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reconcile_state (    -- UN-RFC 0040 section 6: when to reconcile next
    peer       TEXT PRIMARY KEY,
    next_at    INTEGER NOT NULL
);
"""

KB_LEVELS = 4          # running sums down to the first 4 nibbles (65 536 prefixes) of key


# every name above, for the parts (`from . import *`), underscored ones too
__all__ = [n for n in dir() if not n.startswith('__') or n == '__version__']

from .base import StoreBase  # noqa: E402
from .articles import Articles  # noqa: E402
from .groups import Groups  # noqa: E402
from .keybound import KeyBound  # noqa: E402
from .kept import Kept  # noqa: E402
from .blobs import Blobs  # noqa: E402
from .withdrawals import Withdrawals  # noqa: E402
from .peers import Peers  # noqa: E402
from .stats import Stats  # noqa: E402


class Store(StoreBase, Articles, Groups, KeyBound, Kept, Blobs, Withdrawals, Peers, Stats):
    """The node's store.

    Split into parts by area (core/store/*.py, see above)."""
