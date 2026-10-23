"""Key-bound groups (UN-RFC 0029, 0040): their lifetime, and keeping them in step.

Belongs here: when a key-bound group's manifest expires and removing it after, and the
running sums by key prefix that reconciliation compares between peers (UN-RFC 0040
section 4: ``kb_items``, ``kb_count_sum``).

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class KeyBound:
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
