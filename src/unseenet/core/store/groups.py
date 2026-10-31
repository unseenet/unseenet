"""Groups: manifests, the groups a node carries, their state, epochs and removal.

Belongs here: the current manifest of a group (``manifest``, ``set_manifest``), the
groups for LIST, a group's state for NEWNEWS (``state_ids``, UN-RFC 0017: manifest,
key updates, then kept articles), the epochs of closed groups (UN-RFC 0004 section 6),
and groups removed by their owner or dropped by the operator (tombstones, UN-RFC 0013).

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class Groups:
    # --- groups ---
    def manifest(self, group_id: str) -> Manifest | None:
        """The current manifest; None if the group is not carried or has expired."""
        row = self.db.execute("SELECT manifest_id FROM groups WHERE group_id=? AND serial > 0",
                              (group_id,)).fetchone()
        if not row or self.expired(group_id):
            return None
        raw = self.get(row[0])
        # a council manifest is set here only once its chain counted (UN-RFC 0054)
        return (Manifest.from_article(Article.from_bytes(raw), stored=True, council_ok=True)
                if raw else None)

    def set_manifest(self, m: Manifest) -> None:
        """Make a manifest the group's current one; a key-bound group's is also put in
        the sums that reconciliation compares (UN-RFC 0040 section 4)."""
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
        """Record a closed group's key epoch and its member key, with the key update
        that made it (UN-RFC 0004 section 6)."""
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
        # a council group's chain, oldest first, so it can be counted as it comes (0054, 6)
        out += self.council_kept(group_id)
        row = self.db.execute("SELECT manifest_id FROM groups WHERE group_id=? AND serial > 0",
                              (group_id,)).fetchone()
        if row and row[0] and row[0] not in out:
            out.append(row[0])
        out += [r[0] for r in self.db.execute(
            "SELECT e.message_id FROM epoch_articles e JOIN articles a USING (message_id) "
            "WHERE e.group_id=? AND e.epoch >= (SELECT MAX(epoch) - 1 FROM epoch_articles "
            "WHERE group_id=?) ORDER BY e.epoch", (group_id, group_id))]
        out += [k for k in self.kept_ids(group_id) if self.has(k) and k not in out]
        return out

    def removals_since(self, since: int) -> list[tuple[str, str]]:
        """(rmgroup Message-ID, group) for groups their owner removed since ``since``."""
        return list(self.db.execute(
            "SELECT message_id, group_id FROM tombstones WHERE reason='owner' AND at >= ? "
            "AND message_id IS NOT NULL ORDER BY at", (since,)))

    def close_previous(self, group_id: str, epoch: int) -> None:
        """Note that a closed group's ``epoch`` has been replaced: posts encrypted to it
        are no longer taken (UN-RFC 0004 section 6)."""
        self.db.execute("INSERT OR IGNORE INTO closed_epochs VALUES (?, ?)", (group_id, epoch))
        self.db.commit()

    def closed_before(self, group_id: str) -> int:
        """Articles of epochs below this are refused (0: none closed)."""
        row = self.db.execute("SELECT MAX(epoch) FROM closed_epochs WHERE group_id=?",
                              (group_id,)).fetchone()
        return int(row[0] or 0)

    def epochs(self, group_id: str) -> dict[int, bytes]:
        """A closed group's epochs and the member key of each (UN-RFC 0004 section 6)."""
        return {e: crypto.key_from_text(k) for e, k in self.db.execute(
            "SELECT epoch, member_key FROM epochs WHERE group_id=?", (group_id,))}

    # --- removal (UN-RFC 0013) ---
    def tombstone(self, group_id: str) -> str | None:
        """Why a group is gone - ``owner`` (removed, UN-RFC 0013) or ``operator``
        (dropped) - or None."""
        row = self.db.execute("SELECT reason FROM tombstones WHERE group_id=?", (group_id,)).fetchone()
        return row[0] if row else None

    def add_tombstone(self, group_id: str, reason: str, message_id: str | None = None,
                      raw: bytes | None = None) -> None:
        """Mark a group removed - by its owner (``owner``, with the rmgroup article,
        UN-RFC 0013) or dropped by the operator (``operator``) - so it is not taken again."""
        self.db.execute("INSERT OR REPLACE INTO tombstones VALUES (?, ?, ?, ?, ?)",
                        (group_id, int(time.time()), reason, message_id, raw))
        self.db.commit()

    def dropped_groups(self) -> list[str]:
        """Groups the operator has dropped (UN-RFC 0013 section 3), sorted."""
        rows = self.db.execute("SELECT group_id FROM tombstones WHERE reason='operator' "
                               "ORDER BY group_id").fetchall()
        return [r[0] for r in rows]

    def lift_tombstone(self, group_id: str) -> bool:
        """Take back an operator's drop of a group, so it can be carried again; an
        owner's removal stays. True if there was one."""
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
