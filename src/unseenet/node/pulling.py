"""Catching up from peers by pulling (UN-RFC 0005 section 5.3, UN-RFC 0017).

Pushing (peering.py) delivers new articles as they arrive. Pulling fills the
gaps: a new node gets the history of the groups it carries, and a node that
was down gets what it missed. It uses only reader commands (DATE, NEWNEWS,
ARTICLE), so it works with any node, also one that does not list us as a peer.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import Counter
from datetime import datetime, timedelta, timezone

from ..core.article import ArticleError
from ..nntp import Client, NNTPError, strip_reader_headers
from .peering import PeerAuthError, WrongNodeError, authenticate_with_key
from .server import Node, PeerConfig

log = logging.getLogger("unseenet.pulling")

OVERLAP = timedelta(minutes=15)      # re-ask a little: articles arriving during the last pull
MAX_PER_RUN = 5000                   # the rest comes next run


class Puller:
    """Pulls what a peer has that this node has not seen."""

    def __init__(self, node: Node, peer: PeerConfig, socks_port: int | None = None,
                 interval: float | None = None):
        self.node, self.peer, self.socks_port = node, peer, socks_port
        self.interval = interval if interval is not None else node.config.pull_interval

    async def run_once(self) -> dict:
        """One catch-up. Returns counts: listed, fetched, accepted and rejections by reason."""
        store, peer = self.node.store, self.peer
        result: dict = {"listed": 0, "fetched": 0, "accepted": 0, "rejected": Counter()}
        if not peer.pull:
            return result
        client = await Client.connect(peer.address, self.socks_port)
        try:
            await client.fetch_capabilities()
            if peer.key:
                try:   # proves it is the node we meant; as a peer we also get articles as stored
                    await authenticate_with_key(client, self.node.key, peer.public_key())
                except WrongNodeError:
                    raise
                except PeerAuthError as exc:   # it does not list us: reading is open to anyone
                    log.debug("pulling from %s as a reader: %s", peer.name, exc)
            _, text = await client.command("DATE", (111,))
            their_now = datetime.strptime(text.split()[0], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            last = store.pulled_since(peer.name)
            if last is None:          # first time: everything within our retention
                since = their_now - timedelta(days=self.node.config.retention_days)
            else:
                since = datetime.fromtimestamp(last, timezone.utc) - OVERLAP
            ids = await client.multiline(
                f"NEWNEWS {peer.pull} {since:%Y%m%d %H%M%S} GMT", 230)
            wanted = [i.strip() for i in ids if i.strip() and not store.seen(i.strip())]
            result["listed"] = len(ids)
            for msgid in wanted[:MAX_PER_RUN]:
                raw = await client.article(msgid)
                if raw is None:            # expired or cancelled meanwhile
                    continue
                result["fetched"] += 1
                try:
                    self.node.accept(strip_reader_headers(raw), source=peer.name, from_peer=True,
                                     how="pull")
                    result["accepted"] += 1
                except ArticleError as err:
                    result["rejected"][err.reason] += 1
                    store.remember(msgid)  # do not fetch it again; our policy will not change
                    store.db.commit()
            if len(wanted) <= MAX_PER_RUN:
                store.set_pulled(peer.name, int(their_now.timestamp()))
        finally:
            try:
                await client.quit()
            except (OSError, ConnectionError, NNTPError):
                pass
        if result["fetched"]:
            rejected = ", ".join(f"{n} {r}" for r, n in result["rejected"].items())
            log.info("pulled %d from %s: %d accepted%s", result["fetched"], peer.name,
                     result["accepted"], f", rejected: {rejected}" if rejected else "")
        return result

    async def run_forever(self) -> None:
        await asyncio.sleep(random.uniform(5, 60))     # do not hit every peer at start
        while True:
            stats, name = self.node.stats, self.peer.name
            try:
                r = await self.run_once()
                stats.pulled_from(name, r["accepted"],
                                  f"{r['listed']} listed, {r['fetched']} fetched, {r['accepted']} new")
            except (OSError, ConnectionError, asyncio.TimeoutError,
                    asyncio.IncompleteReadError) as exc:
                log.warning("pull from %s: unreachable: %s", name, exc)
                stats.pulled_from(name, 0, f"unreachable: {exc}")
            except (PeerAuthError, NNTPError, ValueError) as exc:
                log.warning("pull from %s: %s", name, exc)
                stats.pulled_from(name, 0, str(exc))
            except Exception as exc:  # noqa: BLE001
                log.exception("pull from %s failed", name)
                stats.pulled_from(name, 0, f"failed: {exc}")
            await asyncio.sleep(self.interval * random.uniform(0.8, 1.2))
