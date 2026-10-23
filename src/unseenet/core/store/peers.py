"""Peers: what is queued for each, and how far the node has pulled from each.

Belongs here: the peer queues (``enqueue``, ``due``, ``reschedule`` - also when blobs
came, UN-RFC 0027 section 6.3), the pull state (UN-RFC 0017) and when to reconcile next
(UN-RFC 0040 section 6).

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class Peers:
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

    def reschedule(self, message_id: str, when) -> None:
        """Move an article queued for peers to ``when(peer)`` (unix seconds), for
        example when the blobs it waited for have come (UN-RFC 0027 section 6.3)."""
        for (peer,) in list(self.db.execute("SELECT peer FROM peer_queue WHERE message_id=?",
                                            (message_id,))):
            self.db.execute("UPDATE peer_queue SET not_before=? WHERE peer=? AND message_id=?",
                            (when(peer), peer, message_id))
        self.db.commit()

    def postpone(self, peer: str, message_id: str, seconds: float) -> None:
        self.db.execute("UPDATE peer_queue SET not_before=? WHERE peer=? AND message_id=?",
                        (time.time() + seconds, peer, message_id))
        self.db.commit()
