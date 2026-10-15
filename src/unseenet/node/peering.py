"""Outgoing streaming feeds to peers (UN-RFC 0005, section 5.2)."""

from __future__ import annotations

import asyncio
import logging

from ..nntp import Client, dot_stuff
from .server import Node, PeerConfig

log = logging.getLogger("unseenet.peering")


class Feeder:
    """Pushes queued articles to one peer with MODE STREAM / CHECK / TAKETHIS."""

    def __init__(self, node: Node, peer: PeerConfig, socks_port: int | None = None,
                 retry: float = 30.0):
        self.node, self.peer, self.socks_port, self.retry = node, peer, socks_port, retry
        self.wakeup = node.subscribe()

    async def run_once(self) -> int:
        """Deliver everything that is due. Returns number of articles handled."""
        store = self.node.store
        due = store.due(self.peer.name)
        if not due:
            return 0
        client = await Client.connect(self.peer.address, self.socks_port)
        try:
            if self.peer.password:
                await client.command(f"AUTHINFO USER {self.node_name}", (381,))
                await client.command(f"AUTHINFO PASS {self.peer.password}", (281,))
            await client.command("MODE STREAM", (203,))
            for msgid in due:
                raw = store.get(msgid)
                if raw is None:          # expired or cancelled meanwhile
                    store.dequeue(self.peer.name, msgid)
                    continue
                code, _ = await client.command(f"CHECK {msgid}")
                if code == 238:
                    client.writer.write(f"TAKETHIS {msgid}\r\n".encode() + dot_stuff(raw))
                    await client.writer.drain()
                    code, _ = await client._response()
                if code == 431:
                    store.postpone(self.peer.name, msgid, self.retry)
                else:                    # 438 not wanted, 239 taken, 439 rejected
                    store.dequeue(self.peer.name, msgid)
            return len(due)
        finally:
            await client.quit()

    @property
    def node_name(self) -> str:
        return self.node.config.name

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except (OSError, ConnectionError, asyncio.TimeoutError) as exc:
                log.warning("peer %s unreachable: %s", self.peer.name, exc)
            except Exception:  # noqa: BLE001
                log.exception("feed to %s failed", self.peer.name)
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=self.retry)
                self.wakeup.clear()
            except asyncio.TimeoutError:
                pass
