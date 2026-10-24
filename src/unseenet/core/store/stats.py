"""Numbers for the operator's monitor (``node/stats.py``): groups, articles, bytes, queues.

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class Stats:
    # --- numbers for the operator (node/stats.py) ---
    def group_count(self) -> int:
        """How many groups the node carries (with a manifest)."""
        return self.db.execute("SELECT COUNT(*) FROM groups WHERE serial > 0").fetchone()[0]

    def group_sizes(self) -> dict[str, int]:
        """How many articles each group has."""
        return dict(self.db.execute("SELECT group_id, COUNT(*) FROM articles GROUP BY group_id"))

    def group_activity(self, group_id: str, not_by: str = "") -> tuple[int, int | None]:
        """How many articles a group has, and when the newest arrived (Unix time) -
        leaving out those by the key ``not_by`` (e.g. the owner's manifests)."""
        n, newest = self.db.execute(
            "SELECT COUNT(*), MAX(received) FROM articles WHERE group_id = ? AND author_key != ?",
            (group_id, not_by)).fetchone()
        return n, newest

    def total_bytes(self) -> int:
        """The octets of all articles held."""
        return self.db.execute("SELECT COALESCE(SUM(LENGTH(raw)), 0) FROM articles").fetchone()[0]

    def queue_length(self, peer: str) -> int:
        """How many articles wait for a peer."""
        return self.db.execute("SELECT COUNT(*) FROM peer_queue WHERE peer=?", (peer,)).fetchone()[0]

    def tombstone_count(self) -> int:
        """How many groups are removed or dropped."""
        return self.db.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0]
