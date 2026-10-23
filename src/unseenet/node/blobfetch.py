"""Blobs follow their article (UN-RFC 0027 section 6.3).

A blob node that accepts an article with blobs from a peer fetches them from that
peer first, then from the other peers that carry the group, before it passes the
article on; after BLOB_WAIT_SECONDS it passes the article on without them. The
article waits in the persistent peer queue meanwhile (Node._wait_for_blobs), so a
restart loses at most the fetching, never the forwarding.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..core import blobs as bl
from ..nntp import Client
from .server import Node, PeerConfig, wildmat

log = logging.getLogger("unseenet.blobs")


class BlobFollower:
    def __init__(self, node: Node, socks_port: int | None = None, tick: float = 5.0,
                 timeout: float = 120.0):
        self.node, self.socks_port, self.tick, self.timeout = node, socks_port, tick, timeout

    def _peers_for(self, group: str, source: str | None) -> list[PeerConfig]:
        """The peer the article came from first, then the others carrying the group."""
        peers = [p for p in self.node.config.peers if wildmat(p.groups, group)]
        peers.sort(key=lambda p: p.name != source)
        return peers

    async def fetch(self, peer: PeerConfig, bid: str, size: int) -> bytes | None:
        """BLOB from one peer (section 6.4); None when it has not got it (now)."""
        client = await asyncio.wait_for(Client.connect(peer.address, self.socks_port), self.timeout)
        try:
            code, text = await asyncio.wait_for(client.command(f"BLOB {bid}"), self.timeout)
            if code != 226:
                return None
            n = int(text.split()[0])
            if n != size or n > self.node.config.max_blob:
                return None
            octets = await asyncio.wait_for(client.reader.readexactly(n), self.timeout)
            return octets if bl.blob_id(octets) == bid else None      # section 3.1
        finally:
            await client.quit()

    async def run_once(self) -> int:
        """One round over the waiting articles. Returns the blobs fetched."""
        got = 0
        for msgid, w in list(self.node.blob_wait.items()):
            for bid, size in list(w["missing"].items()):
                if self.node.blobs.has(bid):
                    w["missing"].pop(bid, None)
                    continue
                for peer in self._peers_for(w["group"], w["source"]):
                    try:
                        octets = await self.fetch(peer, bid, size)
                    except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
                        log.debug("blob %s from %s: %s", bid, peer.name, exc)
                        continue
                    if octets is not None:
                        self.node.blobs.put(bid, octets)
                        w["missing"].pop(bid, None)
                        got += 1
                        break
            if not w["missing"]:
                self.node.blobs_done(msgid)
            elif time.time() >= w["until"]:
                log.info("passing %s on without %d blob(s)", msgid, len(w["missing"]))
                self.node.blobs_done(msgid)
        return got

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("fetching blobs failed")
            await asyncio.sleep(self.tick)
