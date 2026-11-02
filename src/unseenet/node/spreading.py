"""Spreading (#230): what this node's own readers post goes out to the announced nodes
it pulls from, so a new node is a node at once.

A node with no configured peer to push to pulls from announced nodes (UN-RFC 0055
section 5.5, ``autopeers.py``) - it gets everything, but nothing would go the other way:
its own announcement, its ripening chain and its readers' posts stay on it, since others
pull only from nodes whose announcement they hold. So such a node streams them (MODE
STREAM, CHECK, TAKETHIS - as a peer pushes, and as any node takes from anyone unless
``require_peer_auth`` is on) to the nodes it pulls from, which pass them on to their
peers. It first checks that each is the node its announcement names (UN-RFC 0016).

``spread`` in node.toml: "auto" (the default: when no configured peer takes pushes from
this node), "on", "off". What is queued is ``Node._spread_local``.

Belongs here: sending the queue. Not here: choosing the nodes (``autopeers.py``),
queueing (``server/forwarding.py``)."""

from __future__ import annotations

import asyncio
import logging

from ..nntp import Client, NNTPError, dot_stuff
from .autopeers import AutoPeers, peer_for
from .peering import PeerAuthError, WrongNodeError, authenticate_with_key
from .server import SPREAD_QUEUE, Node, PeerConfig

log = logging.getLogger("unseenet.spread")

RETRY = 60.0              # seconds before trying the queue again
LATER = 300.0             # an article a node answered "later" (431) is tried again then
TIMEOUT = 300.0           # one node, over Tor


class Spreader:
    def __init__(self, node: Node, autopeers: AutoPeers, socks_port: int | None = None,
                 retry: float = RETRY):
        self.node, self.autopeers, self.socks_port, self.retry = node, autopeers, socks_port, retry
        self.wakeup = node.subscribe()

    async def run_once(self) -> int:
        """Send what is due to every chosen announced node. Returns how many articles at
        least one of them took. An article leaves the queue once a node took it, had it,
        or refused it; it stays when no node could be reached, or one said later."""
        store = self.node.store
        if not self.node.spreads():
            return 0
        due = store.due(SPREAD_QUEUE)
        if not due:
            return 0
        if not self.autopeers.chosen:
            self.autopeers.choose()
        targets = [peer_for(a, address) for a, address in self.autopeers.chosen.values()]
        if not targets:
            return 0
        answered: dict[str, bool] = {}        # message id -> taken somewhere
        later: set[str] = set()
        for peer in targets:
            try:
                got = await asyncio.wait_for(self._push(peer, due), TIMEOUT)
            except WrongNodeError as exc:
                log.warning("announced node %s does not have the key it announced: %s",
                            peer.name, exc)
                continue
            except (OSError, ConnectionError, asyncio.TimeoutError, NNTPError,
                    PeerAuthError, ValueError) as exc:
                log.info("could not spread to %s: %s", peer.name, exc)
                continue
            for msgid, code in got.items():
                if code == 431:
                    later.add(msgid)
                else:
                    answered[msgid] = answered.get(msgid, False) or code in (238, 239, 438)
        for msgid in due:
            if msgid in answered and msgid not in later:
                store.dequeue(SPREAD_QUEUE, msgid)
            elif msgid in later:
                store.postpone(SPREAD_QUEUE, msgid, LATER)
        taken = sum(answered.values())
        if taken:
            log.info("spread %d article(s) to %d announced node(s)", taken, len(targets))
        return taken

    async def _push(self, peer: PeerConfig, due: list[str]) -> dict[str, int]:
        """Stream ``due`` to one node. Returns the answer per message id (239 taken,
        438 had it, 439 refused, 431 later)."""
        store = self.node.store
        client = await Client.connect(peer.address, self.socks_port)
        try:
            await client.fetch_capabilities()
            if client.capability("UNSEENET-PEERKEY") is None:
                raise PeerAuthError("it cannot prove its node key (UN-RFC 0016)")
            try:                     # proves it is the node we meant (WrongNodeError if not)
                await authenticate_with_key(client, self.node.key, peer.public_key())
            except WrongNodeError:
                raise
            except PeerAuthError:    # it does not list us as a peer: anyone may stream
                pass
            await client.command("MODE STREAM", (203,))
            out: dict[str, int] = {}
            for msgid in due:
                raw = store.get(msgid)
                if raw is None or self.node.report_hidden(msgid):
                    out[msgid] = 439                 # gone, or reported: nothing to send
                    continue
                code, _ = await client.command(f"CHECK {msgid}")
                if code == 238:
                    client.writer.write(f"TAKETHIS {msgid}\r\n".encode() + dot_stuff(raw))
                    await client.writer.drain()
                    code, _ = await client._response()
                elif code == 480:                    # it takes pushes from its peers only
                    raise PeerAuthError("it takes articles from its own peers only")
                out[msgid] = code
            return out
        finally:
            try:
                await client.quit()
            except Exception:  # noqa: BLE001 - the connection may be gone already
                pass

    async def run_forever(self) -> None:
        await asyncio.sleep(30)                      # after the node and Tor are up
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - never let this stop the node
                log.exception("spreading to announced nodes failed")
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=self.retry)
                self.wakeup.clear()
                await asyncio.sleep(5)               # a few posts together
            except asyncio.TimeoutError:
                pass
