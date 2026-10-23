"""SQLite article store, history and group state for a node."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .reconcile import FULL, MOD, item_hash, item_key, item_value
from . import crypto
from .article import Article, parse_date
from . import pins as pn
from .groups import (KEY_BOUND_NAMES, MAX_LIFETIME, REMOVE_AFTER, Manifest, is_key_bound,
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


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = None if str(path) == ":memory:" else Path(path)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()
        self._backfill_epoch_articles()
        if not self.db.execute("SELECT 1 FROM kb_meta").fetchone():
            self.kb_rebuild()                 # stores from before UN-RFC 0040

    def _backfill_epoch_articles(self) -> None:
        """Stores from before UN-RFC 0017 did not record which articles define epochs."""
        if self.db.execute("SELECT 1 FROM epoch_articles LIMIT 1").fetchone():
            return
        if not self.db.execute("SELECT 1 FROM epochs LIMIT 1").fetchone():
            return
        from .groups import parse_key_update
        for msgid, gid, raw in list(self.db.execute(
                "SELECT message_id, group_id, raw FROM articles WHERE instr(raw, ?) > 0",
                (b"Control: key-update",))):
            try:
                epoch, member_key, _ = parse_key_update(Article.from_bytes(raw))
            except Exception:  # noqa: BLE001
                continue
            if member_key is not None:
                self.db.execute("INSERT OR IGNORE INTO epoch_articles VALUES (?, ?, ?)",
                                (gid, epoch, msgid))
        self.db.commit()

    # --- history ---
    def seen(self, message_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM history WHERE message_id=?",
                               (message_id,)).fetchone() is not None

    def refuse(self, message_id: str, peer: str, reason: str) -> None:
        """Note that an article pulled from ``peer`` was refused, so it is not fetched
        from that peer again. Unlike history, this never refuses the article itself:
        it may still be posted by a client, or arrive once our policy allows it."""
        self.db.execute("INSERT OR REPLACE INTO refused VALUES (?, ?, ?, ?)",
                        (message_id, peer, reason, int(time.time())))

    def refused_from(self, message_id: str, peer: str) -> bool:
        return self.db.execute("SELECT 1 FROM refused WHERE message_id=? AND peer=?",
                               (message_id, peer)).fetchone() is not None

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

    def number_of(self, message_id: str) -> int | None:
        row = self.db.execute("SELECT number FROM articles WHERE message_id=?", (message_id,)).fetchone()
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
            # the group's state - current manifest, live key updates, kept articles
            # (UN-RFC 0017 section 2) - never expires
            kept = self.kept_ids(group_id, window_days=days, now=now)
            self.db.execute("CREATE TEMP TABLE IF NOT EXISTS keep_now (message_id TEXT PRIMARY KEY)")
            self.db.execute("DELETE FROM keep_now")
            self.db.executemany("INSERT OR IGNORE INTO keep_now VALUES (?)", [(k,) for k in kept])
            cur = self.db.execute(
                "DELETE FROM articles WHERE group_id=? AND date < ? AND message_id NOT IN "
                "(SELECT manifest_id FROM groups) AND message_id NOT IN "
                "(SELECT message_id FROM epoch_articles WHERE group_id=? AND epoch >= "
                " (SELECT MAX(epoch) - 1 FROM epoch_articles WHERE group_id=?)) "
                "AND message_id NOT IN (SELECT message_id FROM keep_now)",
                (group_id, now - days * 86400, group_id, group_id))
            deleted += cur.rowcount
            # markers of no use any more: their article is gone, or a pending one
            # waited longer than the window for its target
            self.db.execute(
                "DELETE FROM markers WHERE group_id=? AND (message_id NOT IN "
                "(SELECT message_id FROM articles) OR date < ?) AND message_id NOT IN "
                "(SELECT message_id FROM keep_now)", (group_id, now - days * 86400))
        self.kb_sweep(now)
        self.remove_expired_key_bound(now)
        self.db.execute("DELETE FROM history WHERE seen < ?", (now - (default_days + 2) * 86400,))
        self.db.execute("DELETE FROM refused WHERE at < ?", (now - (default_days + 2) * 86400,))
        self.db.commit()
        return deleted

    # --- key-bound groups (UN-RFC 0029) ---
    def _expires_at(self, group_id: str, manifest_json: str, manifest_id: str) -> int | None:
        """When a key-bound group's state ends, as unix seconds; None for other groups.
        A manifest stored before UN-RFC 0029 has no ``expires``: it lasts the longest
        lifetime from its own Date, so nothing is lost while owners' clients renew it."""
        if not is_key_bound(group_id):
            return None
        exp = stored_expires(json.loads(manifest_json or "{}"))
        if exp is not None:
            return int(exp.timestamp())
        row = self.db.execute("SELECT date FROM articles WHERE message_id=?",
                              (manifest_id,)).fetchone()
        return int(row[0] + MAX_LIFETIME.total_seconds()) if row else 0

    def expired(self, group_id: str, now: float | None = None) -> bool:
        """A key-bound group whose manifest has run out: not carried any more (section 5)."""
        row = self.db.execute("SELECT manifest, manifest_id FROM groups WHERE group_id=? "
                              "AND serial > 0", (group_id,)).fetchone()
        if not row:
            return False
        at = self._expires_at(group_id, row[0], row[1])
        return at is not None and (now or time.time()) >= at

    def known_group(self, group_id: str) -> bool:
        """The node has a manifest for the group, current or expired."""
        return self.db.execute("SELECT 1 FROM groups WHERE group_id=? AND serial > 0",
                               (group_id,)).fetchone() is not None

    def remove_expired_key_bound(self, now: float | None = None) -> list[str]:
        """Remove key-bound groups expired more than REMOVE_AFTER ago (section 5)."""
        now = now or time.time()
        gone = []
        for gid, manifest, mid in list(self.db.execute(
                "SELECT group_id, manifest, manifest_id FROM groups WHERE serial > 0")):
            at = self._expires_at(gid, manifest, mid)
            if at is not None and now >= at + REMOVE_AFTER.total_seconds():
                self.remove_group(gid)
                gone.append(gid)
        return gone

    # --- groups ---
    def manifest(self, group_id: str) -> Manifest | None:
        """The current manifest; None if the group is not carried or has expired."""
        row = self.db.execute("SELECT manifest_id FROM groups WHERE group_id=? AND serial > 0",
                              (group_id,)).fetchone()
        if not row or self.expired(group_id):
            return None
        raw = self.get(row[0])
        return Manifest.from_article(Article.from_bytes(raw), stored=True) if raw else None

    def set_manifest(self, m: Manifest) -> None:
        self.db.execute("INSERT OR IGNORE INTO groups(group_id, manifest, manifest_id, serial)"
                        " VALUES (?, '{}', '', 0)", (m.group_id,))
        self.db.execute("UPDATE groups SET manifest=?, manifest_id=?, serial=? WHERE group_id=?",
                        (json.dumps(m.raw), m.message_id, m.serial, m.group_id))
        if is_key_bound(m.group_id) and not m.local:
            self._kb_put(m.group_id, m.message_id,
                         self._expires_at(m.group_id, json.dumps(m.raw), m.message_id))
        self.db.commit()

    def groups(self, ordinary: bool = False) -> list[tuple[str, int, int, str]]:
        """(group_id, high, low, description) for carried groups; with ``ordinary``,
        without key-bound groups (UN-RFC 0040 section 3: not listed)."""
        sql = "SELECT group_id, high, manifest FROM groups WHERE serial > 0"
        if ordinary:
            sql += "".join(f" AND group_id NOT GLOB '{n}@*'" for n in KEY_BOUND_NAMES)
        out = []
        for gid, high, manifest in list(self.db.execute(sql + " ORDER BY group_id")):
            if self.expired(gid):             # UN-RFC 0029 section 5: not offered
                continue
            if ordinary and is_key_bound(gid):
                continue
            nums = self.numbers(gid)
            data = json.loads(manifest)
            out.append((gid, high, nums[0] if nums else high + 1,
                        data.get("title") or data.get("description", "")))
        return out

    def set_epoch(self, group_id: str, epoch: int, member_key: bytes,
                  message_id: str | None = None) -> None:
        self.db.execute("INSERT OR REPLACE INTO epochs VALUES (?, ?, ?)",
                        (group_id, epoch, crypto.key_to_text(member_key)))
        if message_id:
            self.db.execute("INSERT OR IGNORE INTO epoch_articles VALUES (?, ?, ?)",
                            (group_id, epoch, message_id))
        self.db.commit()

    def state_ids(self, group_id: str) -> list[str]:
        """UN-RFC 0017: the articles a node needs before it can accept posts in a
        group - its current manifest and the key updates of the live epochs."""
        out = []
        if self.expired(group_id):
            return out
        row = self.db.execute("SELECT manifest_id FROM groups WHERE group_id=? AND serial > 0",
                              (group_id,)).fetchone()
        if row and row[0]:
            out.append(row[0])
        out += [r[0] for r in self.db.execute(
            "SELECT e.message_id FROM epoch_articles e JOIN articles a USING (message_id) "
            "WHERE e.group_id=? AND e.epoch >= (SELECT MAX(epoch) - 1 FROM epoch_articles "
            "WHERE group_id=?) ORDER BY e.epoch", (group_id, group_id))]
        out += [k for k in self.kept_ids(group_id) if self.has(k) and k not in out]
        return out

    # --- kept articles (UN-RFC 0017 section 2.1): pins (UN-RFC 0033) ---
    def has(self, message_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM articles WHERE message_id=?",
                               (message_id,)).fetchone() is not None

    def add_marker(self, art: Article, action: str, target: str, replaces=()) -> None:
        self.db.execute("INSERT OR IGNORE INTO markers VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (art.message_id, art.group, target, action, art["Author-Key"],
                         int(parse_date(art["Date"]).timestamp()), " ".join(replaces)))
        self.db.commit()

    def markers(self, group_id: str) -> list[pn.Marker]:
        return [pn.Marker(mid, target, action, author, date, tuple(sup.split()))
                for mid, target, action, author, date, sup in self.db.execute(
                    "SELECT message_id, target, action, author_key, date, supersedes "
                    "FROM markers WHERE group_id=?", (group_id,))]

    def marker(self, message_id: str) -> tuple[str, str] | None:
        """(group, target) of a pin or unpin we hold."""
        row = self.db.execute("SELECT group_id, target FROM markers WHERE message_id=?",
                              (message_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def current_version(self, message_id: str) -> str:
        """An edited post's current version (UN-RFC 0042); the post itself otherwise."""
        row = self.db.execute("SELECT new FROM supersedes WHERE old=?", (message_id,)).fetchone()
        return row[0] if row else message_id

    def withdrawn(self, group_id: str) -> set[str]:
        """Targets withdrawn by a valid cancel (UN-RFC 0033 section 4.2, step 2)."""
        return {r[0] for r in self.db.execute("SELECT target FROM cancels WHERE group_id=?",
                                              (group_id,))}

    def pins_in_force(self, group_id: str, manifest: Manifest | None = None,
                      extra: list[pn.Marker] = ()) -> list[pn.Marker]:
        """The pins in force (UN-RFC 0033 section 4.2), newest first, also those whose
        target has not arrived yet (pending). ``extra``: markers not stored yet."""
        m = manifest or self.manifest(group_id)
        if m is None or m.type in ("inbox",) or m.local:
            return []
        try:
            limit = pn.max_pins(m.raw)
        except ValueError:
            return []
        return pn.in_force([*self.markers(group_id), *extra], owner=crypto.key_to_text(m.owner),
                           moderators=[crypto.key_to_text(k) for k in m.moderators],
                           limit=limit, withdrawn=self.withdrawn(group_id))

    def kept_ids(self, group_id: str, *, window_days: int | None = None,
                 now: float | None = None) -> list[str]:
        """The group's kept articles in listing order (UN-RFC 0017 sections 2.1, 3):
        pins in force, the latest unpin of a target while inside the window, then
        the pinned targets. At most 256 targets (section 2.2)."""
        if not self.db.execute("SELECT 1 FROM markers WHERE group_id=? LIMIT 1",
                               (group_id,)).fetchone():
            return []                    # most groups: nothing kept, nothing to work out
        m = self.manifest(group_id)
        if m is None:
            return []
        pins = self.pins_in_force(group_id, m)
        days = m.retention_days if window_days is None else window_days
        since = (now or time.time()) - days * 86400
        allowed = {crypto.key_to_text(m.owner), *(crypto.key_to_text(k) for k in m.moderators)}
        unpins = sorted((u for u in pn.current(self.markers(group_id), allowed).values()
                         if u.action == pn.UNPIN and u.date >= since),
                        key=lambda u: u.newest_first)
        # an edited post is kept as its current version (UN-RFC 0033 section 5.1)
        targets = [self.current_version(p.target) for p in pins][:pn.KEPT_PER_GROUP]
        return [p.message_id for p in pins] + [u.message_id for u in unpins] + targets

    def removals_since(self, since: int) -> list[tuple[str, str]]:
        """(rmgroup Message-ID, group) for groups their owner removed since ``since``."""
        return list(self.db.execute(
            "SELECT message_id, group_id FROM tombstones WHERE reason='owner' AND at >= ? "
            "AND message_id IS NOT NULL ORDER BY at", (since,)))

    # --- pull state (UN-RFC 0017) ---
    def pulled_since(self, peer: str) -> int | None:
        row = self.db.execute("SELECT since FROM pull_state WHERE peer=?", (peer,)).fetchone()
        return row[0] if row else None

    def set_pulled(self, peer: str, since: int) -> None:
        self.db.execute("INSERT OR REPLACE INTO pull_state VALUES (?, ?)", (peer, since))
        self.db.commit()

    def reconcile_due(self, peer: str, now: float | None = None) -> bool:
        """Never reconciled with ``peer``, or its next time has come (UN-RFC 0040, 6)."""
        row = self.db.execute("SELECT next_at FROM reconcile_state WHERE peer=?",
                              (peer,)).fetchone()
        return row is None or (now or time.time()) >= row[0]

    def set_reconciled(self, peer: str, next_at: float) -> None:
        self.db.execute("INSERT OR REPLACE INTO reconcile_state VALUES (?, ?)",
                        (peer, int(next_at)))
        self.db.commit()

    def close_previous(self, group_id: str, epoch: int) -> None:
        self.db.execute("INSERT OR IGNORE INTO closed_epochs VALUES (?, ?)", (group_id, epoch))
        self.db.commit()

    def closed_before(self, group_id: str) -> int:
        """Articles of epochs below this are refused (0: none closed)."""
        row = self.db.execute("SELECT MAX(epoch) FROM closed_epochs WHERE group_id=?",
                              (group_id,)).fetchone()
        return int(row[0] or 0)

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

    def dropped_groups(self) -> list[str]:
        """Groups the operator has dropped (UN-RFC 0013 section 3), sorted."""
        rows = self.db.execute("SELECT group_id FROM tombstones WHERE reason='operator' "
                               "ORDER BY group_id").fetchall()
        return [r[0] for r in rows]

    def lift_tombstone(self, group_id: str) -> bool:
        cur = self.db.execute("DELETE FROM tombstones WHERE group_id=? AND reason='operator'", (group_id,))
        self.db.commit()
        return cur.rowcount > 0

    def remove_group(self, group_id: str) -> int:
        """Delete a group's manifest and articles. Returns the number of articles deleted."""
        cur = self.db.execute("DELETE FROM articles WHERE group_id=?", (group_id,))
        self.db.execute("DELETE FROM groups WHERE group_id=?", (group_id,))
        self.db.execute("DELETE FROM epochs WHERE group_id=?", (group_id,))
        self.db.execute("DELETE FROM closed_epochs WHERE group_id=?", (group_id,))
        self.db.execute("DELETE FROM epoch_articles WHERE group_id=?", (group_id,))
        self.db.execute("DELETE FROM cancels WHERE group_id=?", (group_id,))
        self.db.execute("DELETE FROM supersedes WHERE group_id=?", (group_id,))
        self._kb_drop(group_id)
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

    # --- edits (UN-RFC 0042) ---
    def add_supersede(self, old: str, new: str, author_key: str, group_id: str, kind: str,
                      first_date: int | None) -> None:
        """Record that ``new`` replaces ``old`` - held and withdrawn, or not seen yet
        (a pending supersede, section 3.1). The newest edit wins."""
        self.db.execute("INSERT OR REPLACE INTO supersedes VALUES (?, ?, ?, ?, ?, ?)",
                        (old, new, author_key, group_id, kind, first_date))

    def supersede_for(self, old: str) -> tuple[str, str, str, str] | None:
        """(edit, author_key, group_id, kind) for a replaced version, or None."""
        row = self.db.execute("SELECT new, author_key, group_id, kind FROM supersedes WHERE old=?",
                              (old,)).fetchone()
        return tuple(row) if row else None

    def first_date(self, message_id: str) -> int | None:
        """The Date of the earliest version known of a post, given any version of it
        (section 3.2); None if it was never edited or no date is known."""
        row = self.db.execute(
            "SELECT MIN(first_date) FROM supersedes WHERE new=? OR old=? OR new IN "
            "(SELECT new FROM supersedes WHERE old=?)", (message_id, message_id, message_id)
        ).fetchone()
        return row[0] if row else None

    def date_of(self, message_id: str) -> int | None:
        row = self.db.execute("SELECT date FROM articles WHERE message_id=?",
                              (message_id,)).fetchone()
        return row[0] if row else None

    # --- key-bound state for reconciliation (UN-RFC 0040 section 4) ---
    def _kb_adjust(self, key: bytes, h: int, delta: int) -> None:
        """Add (delta 1) or take out (-1) one item's hash in the running sums."""
        k = int.from_bytes(key, "big")
        for level in range(KB_LEVELS + 1):
            prefix = k >> (256 - 4 * level)
            row = self.db.execute("SELECT count, total FROM kb_sums WHERE level=? AND prefix=?",
                                  (level, prefix)).fetchone()
            count = (row[0] if row else 0) + delta
            total = ((int.from_bytes(row[1], "big") if row else 0) + delta * h) % MOD
            if count:
                self.db.execute("INSERT OR REPLACE INTO kb_sums VALUES (?, ?, ?, ?)",
                                (level, prefix, count, total.to_bytes(32, "big")))
            else:
                self.db.execute("DELETE FROM kb_sums WHERE level=? AND prefix=?", (level, prefix))

    def _kb_put(self, group_id: str, message_id: str, expires_at: int | None) -> None:
        """The current manifest of a key-bound group (no commit)."""
        key = item_key(group_id)
        h = item_hash(key, item_value(message_id))
        row = self.db.execute("SELECT h, message_id FROM kb_items WHERE key=?", (key,)).fetchone()
        if row and row[1] == message_id:
            self.db.execute("UPDATE kb_items SET expires_at=? WHERE key=?", (expires_at or 0, key))
            return
        if row:
            self._kb_adjust(key, int.from_bytes(row[0], "big"), -1)
        self.db.execute("INSERT OR REPLACE INTO kb_items VALUES (?, ?, ?, ?, ?)",
                        (key, group_id, message_id, h.to_bytes(32, "big"), expires_at or 0))
        self._kb_adjust(key, h, 1)

    def _kb_drop(self, group_id: str) -> None:
        key = item_key(group_id)
        row = self.db.execute("SELECT h FROM kb_items WHERE key=?", (key,)).fetchone()
        if row:
            self.db.execute("DELETE FROM kb_items WHERE key=?", (key,))
            self._kb_adjust(key, int.from_bytes(row[0], "big"), -1)

    def kb_sweep(self, now: float | None = None) -> int:
        """Take groups whose manifest has expired out of the state (UN-RFC 0029 section 5:
        an expired group is absent). A renewal puts them back."""
        gone = [r[0] for r in self.db.execute(
            "SELECT group_id FROM kb_items WHERE expires_at <= ?", (int(now or time.time()),))]
        for gid in gone:
            self._kb_drop(gid)
        if gone:
            self.db.commit()
        return len(gone)

    def kb_rebuild(self) -> None:
        """Build the index from the groups table: for stores from before it existed."""
        self.db.execute("DELETE FROM kb_items")
        self.db.execute("DELETE FROM kb_sums")
        now = time.time()
        for gid, manifest, mid in list(self.db.execute(
                "SELECT group_id, manifest, manifest_id FROM groups WHERE serial > 0")):
            if not is_key_bound(gid) or json.loads(manifest or "{}").get("local"):
                continue
            at = self._expires_at(gid, manifest, mid)
            if at is not None and at > now:
                self._kb_put(gid, mid, at)
        self.db.execute("DELETE FROM kb_meta")
        self.db.execute("INSERT INTO kb_meta VALUES (?)", (int(now),))
        self.db.commit()

    @staticmethod
    def _kb_bound(n: int) -> bytes:
        return n.to_bytes(32, "big")

    def _kb_scan(self, lo: int, hi: int, what: str):
        sql = f"SELECT {what} FROM kb_items WHERE key >= ?"
        args: list = [self._kb_bound(lo)]
        if hi < FULL:
            sql += " AND key < ?"
            args.append(self._kb_bound(hi))
        return self.db.execute(sql + " ORDER BY key", args)

    def kb_items(self, lo: int = 0, hi: int = FULL) -> list[tuple[bytes, str]]:
        """(key, Message-ID) of the items with lo <= key < hi, by key."""
        return [(bytes(k), m) for k, m in self._kb_scan(lo, hi, "key, message_id")]

    def kb_count_sum(self, lo: int = 0, hi: int = FULL) -> tuple[int, int]:
        """Count and sum of the items with lo <= key < hi.

        Whole prefixes come from the running sums; only the parts of the range
        finer than KB_LEVELS nibbles at its two edges are read item by item."""
        count = total = 0
        stack = [(0, 0)]
        while stack:
            level, prefix = stack.pop()
            shift = 256 - 4 * level
            a, b = prefix << shift, (prefix + 1) << shift
            if b <= lo or a >= hi:
                continue
            row = self.db.execute("SELECT count, total FROM kb_sums WHERE level=? AND prefix=?",
                                  (level, prefix)).fetchone()
            if not row:
                continue                               # nothing under this prefix
            if lo <= a and b <= hi:
                count += row[0]
                total += int.from_bytes(row[1], "big")
            elif level == KB_LEVELS:
                for (h,) in self._kb_scan(max(a, lo), min(b, hi), "h"):
                    count += 1
                    total += int.from_bytes(h, "big")
            else:
                stack += [(level + 1, prefix * 16 + i) for i in range(16)]
        return count, total % MOD

    # --- numbers for the operator (node/stats.py) ---
    def group_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM groups WHERE serial > 0").fetchone()[0]

    def group_sizes(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT group_id, COUNT(*) FROM articles GROUP BY group_id"))

    def total_bytes(self) -> int:
        return self.db.execute("SELECT COALESCE(SUM(LENGTH(raw)), 0) FROM articles").fetchone()[0]

    def queue_length(self, peer: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM peer_queue WHERE peer=?", (peer,)).fetchone()[0]

    def tombstone_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0]

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
