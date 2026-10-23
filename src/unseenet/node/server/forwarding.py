"""Forwarding to peers (UN-RFC 0005 section 5): which peers get an article, and when.

Belongs here: queueing an accepted article for each peer that takes its group, with
the random delay (none in low-latency groups), the ripe@ manifest first, and offering
what a reconciliation showed a peer lacks. The sending is ``node/peering.py``.

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Forwarding:
    def _enqueue(self, art: Article, source: str | None, force: bool = False,
                 not_before: float | None = None) -> None:
        manifest = self.store.manifest(art.group)
        if not force and manifest is not None and manifest.local:
            return                       # local groups never leave this node (UN-RFC 0009, 4)
        lo, hi = self.config.forward_delay
        if manifest is not None and manifest.low_latency:
            lo = hi = 0.0                # chat groups: no random delay (UN-RFC 0008, 3.2)
        ripe = None
        if art.get("Key-Ripening") and not self._is_ripe_group(art):
            m = self.store.manifest(make_group_id(rp.GROUP_NAME, art.author_key))
            ripe = m.message_id if m is not None else None
        for peer in self.config.peers:
            if peer.name != source and wildmat(peer.groups, art.group):
                at = not_before or time.time() + random.uniform(lo, hi)
                if ripe:                       # first, so the peer can check the article
                    self.store.enqueue(peer.name, ripe, at - 0.001)
                self.store.enqueue(peer.name, art.message_id, at)
        for event in self._listeners:
            event.set()

    def offer(self, peer_name: str, message_ids: list[str]) -> int:
        """Queue articles a reconciliation showed ``peer_name`` lacks, for its feeder
        (UN-RFC 0040 section 4.3: offered with CHECK/TAKETHIS). Returns how many."""
        peer = self.peer_config(peer_name)
        if peer is None:
            return 0
        n = 0
        for msgid in message_ids:
            meta = self.store.get_meta(msgid)
            if meta and wildmat(peer.groups, meta[0]):
                self.store.enqueue(peer.name, msgid, time.time())
                n += 1
        for event in self._listeners:
            event.set()
        return n
