"""Outgoing streaming feeds to peers (UN-RFC 0005, section 5.2)."""

from __future__ import annotations

import asyncio
import logging

from ..core import crypto
from ..nntp import Client, NNTPError, dot_stuff
from .server import Node, PeerConfig

log = logging.getLogger("unseenet.peering")


class PeerAuthError(Exception):
    pass


class WrongNodeError(PeerAuthError):
    """The node we reached does not have the key we configured for that peer."""

async def authenticate_with_key(client: Client, me: crypto.Identity, expected: bytes) -> None:
    """UN-RFC 0016: prove our node key to a peer, and check that it is the node we meant."""
    if client.capability("UNSEENET-PEERKEY") is None:
        raise PeerAuthError("the peer does not support key authentication (UN-RFC 0016)")
    _, text = await client.command(f"XUN-PEER {me.key_text}", (383,))
    parts = text.split()
    if len(parts) < 2:
        raise PeerAuthError("malformed challenge")
    try:
        theirs = crypto.key_from_text(parts[0])
        nonce = crypto.b64decode(parts[1])
    except Exception as exc:  # noqa: BLE001
        raise PeerAuthError("malformed challenge") from exc
    if theirs != expected:
        raise WrongNodeError(f"the node answered with key {parts[0]}, not the configured "
                            f"{crypto.key_to_text(expected)}")
    if len(nonce) != 32:
        raise PeerAuthError("malformed challenge")
    sig = me.sign_text(crypto.PURPOSE_PEER_AUTH, nonce + theirs + me.public_key)
    code, text = await client.command(f"XUN-PEER-PROOF {sig}")
    if code != 281:
        raise PeerAuthError(f"the peer did not accept our key ({code} {text}); "
                            f"does it list {me.key_text}?")


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
            if self.peer.key:
                await client.fetch_capabilities()
                await authenticate_with_key(client, self.node.key, self.peer.public_key())
            elif self.peer.password:
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
            except (PeerAuthError, NNTPError) as exc:
                log.warning("peer %s: %s", self.peer.name, exc)
            except Exception:  # noqa: BLE001
                log.exception("feed to %s failed", self.peer.name)
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=self.retry)
                self.wakeup.clear()
            except asyncio.TimeoutError:
                pass
