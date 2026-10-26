"""Peers: what is queued for each, and how far the node has pulled from each.

Belongs here: the peer queues (``enqueue``, ``due``, ``reschedule`` - also when blobs
came, UN-RFC 0027 section 6.3), the pull state (UN-RFC 0017), when to reconcile next
(UN-RFC 0040 section 6), and the policy the node last ran with, so a changed policy
forgets the refusals it made (#543).

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class Peers:
    # --- pull state (UN-RFC 0017) ---
    def pulled_since(self, peer: str) -> int | None:
        """How far the node has pulled from a peer (a Unix time for NEWNEWS), or None."""
        row = self.db.execute("SELECT since FROM pull_state WHERE peer=?", (peer,)).fetchone()
        return row[0] if row else None

    def set_pulled(self, peer: str, since: int) -> None:
        """Record how far the node has pulled from a peer."""
        self.db.execute("INSERT OR REPLACE INTO pull_state VALUES (?, ?)", (peer, since))
        self.db.commit()

    def reconcile_due(self, peer: str, now: float | None = None) -> bool:
        """Never reconciled with ``peer``, or its next time has come (UN-RFC 0040, 6)."""
        row = self.db.execute("SELECT next_at FROM reconcile_state WHERE peer=?",
                              (peer,)).fetchone()
        return row is None or (now or time.time()) >= row[0]

    def set_reconciled(self, peer: str, next_at: float) -> None:
        """When to reconcile key-bound state with a peer next (UN-RFC 0040 section 6)."""
        self.db.execute("INSERT OR REPLACE INTO reconcile_state VALUES (?, ?)",
                        (peer, int(next_at)))
        self.db.commit()

    # --- the node's policy (#543) ---
    def policy_seen(self) -> str | None:
        """The fingerprint of the policy the node last ran with, or None (never, or
        a store from before #543)."""
        row = self.db.execute("SELECT policy FROM node_policy").fetchone()
        return row[0] if row else None

    def set_policy(self, fingerprint: str) -> None:
        """Note the policy the node runs with now (see ``policy_seen``)."""
        self.db.execute("DELETE FROM node_policy")
        self.db.execute("INSERT INTO node_policy VALUES (?)", (fingerprint,))
        self.db.commit()

    def forget_policy_refusals(self) -> int:
        """After a change of policy: forget the articles refused for it (reason
        ``group``: not carried, sites, profiles, pictures, new groups, a peer's accept,
        #132), reconcile with every peer at once (UN-RFC 0040 section 6), and pull from
        each again from the start of retention (UN-RFC 0017) - what the node already
        has is not fetched again, but what it refused is listed once more. Refusals
        for the article itself (postage, signature, permission) stay. Returns how
        many refusals were forgotten."""
        n = self.db.execute("DELETE FROM refused WHERE reason='group'").rowcount
        self.db.execute("DELETE FROM reconcile_state")
        self.db.execute("DELETE FROM pull_state")
        self.db.commit()
        return n

    # --- peer queues ---
    def enqueue(self, peer: str, message_id: str, not_before: float) -> None:
        """Queue an article for a peer, to be sent from ``not_before`` on (the random
        forwarding delay, UN-RFC 0005 section 5)."""
        self.db.execute("INSERT OR IGNORE INTO peer_queue VALUES (?, ?, ?)",
                        (peer, message_id, not_before))
        self.db.commit()

    def due(self, peer: str, limit: int = 100) -> list[str]:
        """The Message-IDs queued for a peer whose time has come, oldest first, at most
        ``limit``."""
        return [r[0] for r in self.db.execute(
            "SELECT message_id FROM peer_queue WHERE peer=? AND not_before <= ? "
            "ORDER BY not_before LIMIT ?", (peer, time.time(), limit))]

    def dequeue(self, peer: str, message_id: str) -> None:
        """Take an article off a peer's queue: sent, or not wanted."""
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
        """Try an article for a peer again in ``seconds`` (e.g. it answered ``431``)."""
        self.db.execute("UPDATE peer_queue SET not_before=? WHERE peer=? AND message_id=?",
                        (time.time() + seconds, peer, message_id))
        self.db.commit()
