"""Numbers for the operator's monitor (``node/stats.py``): groups, articles, bytes, queues.

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class Stats:
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
