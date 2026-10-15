"""SQLite article store, history and group state for a node."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from . import crypto
from .article import Article, parse_date
from .groups import Manifest

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

CREATE TABLE IF NOT EXISTS tombstones (       -- UN-RFC 0013
    group_id   TEXT PRIMARY KEY,
    at         INTEGER NOT NULL,
    reason     TEXT NOT NULL,                   -- "owner" or "operator"
    message_id TEXT,                            -- the rmgroup article, for owner removals
    raw        BLOB
);

CREATE TABLE IF NOT EXISTS peer_queue (
    peer       TEXT NOT NULL,
    message_id TEXT NOT NULL,
    not_before REAL NOT NULL,
    PRIMARY KEY (peer, message_id)
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()

    # --- history ---
    def seen(self, message_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM history WHERE message_id=?",
                               (message_id,)).fetchone() is not None

    def remember(self, message_id: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO history VALUES (?, ?)",
                        (message_id, int(time.time())))

    # --- articles ---
    def add(self, art: Article, raw: bytes) -> int:
        group = art.group
        self.db.execute("INSERT OR IGNORE INTO groups(group_id, manifest, manifest_id, serial)"
                        " VALUES (?, '{}', '', 0)", (group,))
        self.db.execute("UPDATE groups SET high = high + 1 WHERE group_id=?", (group,))
        number = self.db.execute("SELECT high FROM groups WHERE group_id=?", (group,)).fetchone()[0]
        self.db.execute(
            "INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?, ?)",
            (art.message_id, group, number, int(parse_date(art["Date"]).timestamp()),
             int(time.time()), art["Author-Key"], raw))
        self.remember(art.message_id)
        self.db.commit()
        return number

    def get(self, message_id: str) -> bytes | None:
        row = self.db.execute("SELECT raw FROM articles WHERE message_id=?", (message_id,)).fetchone()
        if row:
            return row[0]
        row = self.db.execute("SELECT raw FROM tombstones WHERE message_id=?", (message_id,)).fetchone()
        return row[0] if row else None

    def get_meta(self, message_id: str) -> tuple[str, str] | None:
        row = self.db.execute("SELECT group_id, author_key FROM articles WHERE message_id=?",
                              (message_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def by_number(self, group_id: str, number: int) -> tuple[str, bytes] | None:
        row = self.db.execute("SELECT message_id, raw FROM articles WHERE group_id=? AND number=?",
                              (group_id, number)).fetchone()
        return (row[0], row[1]) if row else None

    def numbers(self, group_id: str) -> list[int]:
        return [r[0] for r in self.db.execute(
            "SELECT number FROM articles WHERE group_id=? ORDER BY number", (group_id,))]

    def delete(self, message_id: str) -> None:
        self.db.execute("DELETE FROM articles WHERE message_id=?", (message_id,))
        self.db.commit()

    def received_since(self, since: int) -> list[tuple[str, str]]:
        return list(self.db.execute(
            "SELECT message_id, group_id FROM articles WHERE received >= ? ORDER BY received", (since,)))

    def expire(self, default_days: int) -> int:
        """Delete articles past their group's retention. Returns count."""
        now = int(time.time())
        deleted = 0
        for group_id, manifest in list(self.db.execute("SELECT group_id, manifest FROM groups")):
            days = min(default_days, json.loads(manifest).get("retention_days", default_days))
            cur = self.db.execute(
                "DELETE FROM articles WHERE group_id=? AND date < ? AND message_id NOT IN "
                "(SELECT manifest_id FROM groups)", (group_id, now - days * 86400))
            deleted += cur.rowcount
        self.db.execute("DELETE FROM history WHERE seen < ?", (now - (default_days + 2) * 86400,))
        self.db.commit()
        return deleted

    # --- groups ---
    def manifest(self, group_id: str) -> Manifest | None:
        row = self.db.execute("SELECT manifest_id FROM groups WHERE group_id=? AND serial > 0",
                              (group_id,)).fetchone()
        if not row:
            return None
        raw = self.get(row[0])
        return Manifest.from_article(Article.from_bytes(raw)) if raw else None

    def set_manifest(self, m: Manifest) -> None:
        self.db.execute("INSERT OR IGNORE INTO groups(group_id, manifest, manifest_id, serial)"
                        " VALUES (?, '{}', '', 0)", (m.group_id,))
        self.db.execute("UPDATE groups SET manifest=?, manifest_id=?, serial=? WHERE group_id=?",
                        (json.dumps(m.raw), m.message_id, m.serial, m.group_id))
        self.db.commit()

    def groups(self) -> list[tuple[str, int, int, str]]:
        """(group_id, high, low, description) for carried groups."""
        out = []
        for gid, high, manifest in self.db.execute(
                "SELECT group_id, high, manifest FROM groups WHERE serial > 0 ORDER BY group_id"):
            nums = self.numbers(gid)
            data = json.loads(manifest)
            out.append((gid, high, nums[0] if nums else high + 1,
                        data.get("title") or data.get("description", "")))
        return out

    def set_epoch(self, group_id: str, epoch: int, member_key: bytes) -> None:
        self.db.execute("INSERT OR REPLACE INTO epochs VALUES (?, ?, ?)",
                        (group_id, epoch, crypto.key_to_text(member_key)))
        self.db.commit()

    def epochs(self, group_id: str) -> dict[int, bytes]:
        return {e: crypto.key_from_text(k) for e, k in self.db.execute(
            "SELECT epoch, member_key FROM epochs WHERE group_id=?", (group_id,))}

    # --- removal (UN-RFC 0013) ---
    def tombstone(self, group_id: str) -> str | None:
        row = self.db.execute("SELECT reason FROM tombstones WHERE group_id=?", (group_id,)).fetchone()
        return row[0] if row else None

    def add_tombstone(self, group_id: str, reason: str, message_id: str | None = None,
                      raw: bytes | None = None) -> None:
        self.db.execute("INSERT OR REPLACE INTO tombstones VALUES (?, ?, ?, ?, ?)",
                        (group_id, int(time.time()), reason, message_id, raw))
        self.db.commit()

    def lift_tombstone(self, group_id: str) -> bool:
        cur = self.db.execute("DELETE FROM tombstones WHERE group_id=? AND reason='operator'", (group_id,))
        self.db.commit()
        return cur.rowcount > 0

    def remove_group(self, group_id: str) -> int:
        """Delete a group's manifest and articles. Returns the number of articles deleted."""
        cur = self.db.execute("DELETE FROM articles WHERE group_id=?", (group_id,))
        self.db.execute("DELETE FROM groups WHERE group_id=?", (group_id,))
        self.db.execute("DELETE FROM epochs WHERE group_id=?", (group_id,))
        self.db.execute("DELETE FROM cancels WHERE group_id=?", (group_id,))
        self.db.commit()
        return cur.rowcount

    # --- cancels ---
    def add_cancel(self, target: str, author_key: str, group_id: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO cancels VALUES (?, ?, ?)", (target, author_key, group_id))
        self.db.commit()

    def cancel_for(self, target: str) -> tuple[str, str] | None:
        row = self.db.execute("SELECT author_key, group_id FROM cancels WHERE target=?",
                              (target,)).fetchone()
        return (row[0], row[1]) if row else None

    # --- peer queues ---
    def enqueue(self, peer: str, message_id: str, not_before: float) -> None:
        self.db.execute("INSERT OR IGNORE INTO peer_queue VALUES (?, ?, ?)",
                        (peer, message_id, not_before))
        self.db.commit()

    def due(self, peer: str, limit: int = 100) -> list[str]:
        return [r[0] for r in self.db.execute(
            "SELECT message_id FROM peer_queue WHERE peer=? AND not_before <= ? "
            "ORDER BY not_before LIMIT ?", (peer, time.time(), limit))]

    def dequeue(self, peer: str, message_id: str) -> None:
        self.db.execute("DELETE FROM peer_queue WHERE peer=? AND message_id=?", (peer, message_id))
        self.db.commit()

    def postpone(self, peer: str, message_id: str, seconds: float) -> None:
        self.db.execute("UPDATE peer_queue SET not_before=? WHERE peer=? AND message_id=?",
                        (time.time() + seconds, peer, message_id))
        self.db.commit()
