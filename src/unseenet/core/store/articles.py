"""Articles: storing, finding, deleting and expiring them (UN-RFC 0012).

Belongs here: ``add`` (an article, its number in its group, and the blobs it references),
looking articles up by Message-ID or number, deleting one, what arrived since a time,
and ``expire``, which leaves the state of every group (its manifest, live key updates
and kept articles, UN-RFC 0017 section 2) and deletes what is past the window.

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class Articles:
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
        try:
            refs = bl.parse_blobs(art)
        except Exception:  # noqa: BLE001  checked before; nothing to remember then
            refs = []
        self.db.executemany("INSERT OR IGNORE INTO blob_refs VALUES (?, ?, ?, ?)",
                            [(art.message_id, b, group, n) for b, n in refs])
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

    # --- kept articles (UN-RFC 0017 section 2.1): pins (UN-RFC 0033) ---
    def has(self, message_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM articles WHERE message_id=?",
                               (message_id,)).fetchone() is not None
