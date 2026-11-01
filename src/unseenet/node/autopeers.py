"""Pulling from announced nodes (UN-RFC 0055 section 5.5): a node finds peers by itself.

A node with no configured peer gets only what is posted to it. Pulling uses reader
commands only, which every node answers (``pulling.py``), so a node can catch up from
any node without an agreement. Here a node picks a few nodes from the announcements it
holds, checks that each answers with the key it announced (section 5.3: the onion
service proves the address, the node key the node), and pulls from them as from a
configured peer. They see its announcement and pull from it the same way, so articles
flow both ways and the network grows by itself. Everything pulled is checked as
always - signature, postage, ripening, this node's own rules - so a bad node can offer
articles but not make this one take them.

Belongs here: choosing announced nodes, swapping them once a day or when one fails, and
pulling from them. Not here: the pull itself (``pulling.py``), announcements (``core/
announcements.py``, ``announcing.py``).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import Callable

from ..core import announcements as an
from ..core import transport
from ..core.article import Article, ArticleError, parse_date
from ..known_nodes import NODES_ANNOUNCE_GROUP
from ..nntp import NNTPError
from .peering import PeerAuthError, WrongNodeError
from .pulling import Puller
from .server import Node, PeerConfig

log = logging.getLogger("unseenet.autopeers")

AUTO_PEERS = 3            # announced nodes pulled from at once, by default
SWAP_EVERY = 86400.0      # choose again once a day
FAILS = 3                 # failed pulls in a row before a node is swapped out
SHUN = 86400.0            # a node that answered with the wrong key is left out this long


def held_announcements(node: Node) -> list[an.Announcement]:
    """The announcements this node holds, checked again (section 5.2)."""
    out = []
    store = node.store
    for n in store.numbers(NODES_ANNOUNCE_GROUP):
        found = store.by_number(NODES_ANNOUNCE_GROUP, n)
        if not found:
            continue
        try:
            art = Article.from_bytes(found[1])
            out.append(an.parse(art.body, key=art["Author-Key"], date=parse_date(art["Date"]),
                                message_id=found[0]))
        except (ArticleError, an.AnnouncementProblem, KeyError, ValueError):
            continue
    return out


def candidates(node: Node, now: datetime, shunned=frozenset()) -> list[tuple[an.Announcement, str]]:
    """(announcement, address to reach it at) of every announced node this node may pull
    from: not stale, not itself, not a configured peer (by key or address), not shunned,
    and reachable here (an onion address; a test one only on a test network)."""
    mine = node.key.key_text if node.key is not None else None
    peer_keys = {p.key for p in node.config.peers if p.key}
    peer_addresses = set()
    for p in node.config.peers:
        try:
            peer_addresses.add(transport.connect_target(p.address))
        except transport.AddressProblem:
            pass
    out = []
    for key, a in sorted(an.newest(held_announcements(node), now).items()):
        if key == mine or key in peer_keys or key in shunned:
            continue
        usable = transport.usable([a.address, *a.addresses])
        if not usable:
            continue
        address = usable[0].plain()
        if address in peer_addresses:
            continue
        out.append((a, address))
    return out


def peer_for(a: an.Announcement, address: str) -> PeerConfig:
    """A pull-only peer for an announced node; its name is stable per key, so the pull
    remembers where it was (``Store.pulled_since``)."""
    tag = a.key.split(":", 1)[-1][:16]
    return PeerConfig(name=f"announced-{tag}", address=address, groups="", key=a.key, pull="*")


class AutoPeers:
    """Pulls from ``count`` announced nodes, chosen at random, swapped daily."""

    def __init__(self, node: Node, socks_port: int | None, count: int = AUTO_PEERS,
                 now: Callable[[], datetime] | None = None, interval: float | None = None):
        self.node, self.socks_port, self.count = node, socks_port, count
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.interval = interval if interval is not None else node.config.pull_interval
        self.chosen: dict[str, tuple[an.Announcement, str]] = {}
        self.fails: dict[str, int] = {}
        self.shunned: dict[str, float] = {}
        self.chosen_at = 0.0

    def _shunned(self) -> set[str]:
        t = time.time()
        self.shunned = {k: until for k, until in self.shunned.items() if until > t}
        return set(self.shunned)

    def choose(self) -> list[str]:
        """Keep the chosen nodes that are still announced and working; fill up with
        others at random, and start over once a day. Returns the chosen keys."""
        now = self.now()
        pool = {a.key: (a, addr) for a, addr in candidates(self.node, now, self._shunned())}
        if time.time() - self.chosen_at >= SWAP_EVERY:
            self.chosen, self.chosen_at = {}, time.time()
        self.chosen = {k: pool[k] for k in self.chosen
                       if k in pool and self.fails.get(k, 0) < FAILS}
        rest = [k for k in pool if k not in self.chosen]
        random.shuffle(rest)
        for k in rest[:max(0, self.count - len(self.chosen))]:
            self.chosen[k] = pool[k]
            self.fails.pop(k, None)
            log.info("pulling from announced node %s (%s) too", pool[k][0].name, k)
        return list(self.chosen)

    async def run_once(self) -> dict[str, dict]:
        """One pull from each chosen node. Returns the results by key."""
        results = {}
        for key in self.choose():
            a, address = self.chosen[key]
            try:
                results[key] = await Puller(self.node, peer_for(a, address), self.socks_port,
                                            must_prove=True).run_once()
                self.fails[key] = 0
            except WrongNodeError as exc:
                log.warning("announced node %s does not have the key it announced: %s; "
                            "left out for a day", a.name, exc)
                self.shunned[key] = time.time() + SHUN
                self.chosen.pop(key, None)
            except (OSError, ConnectionError, asyncio.TimeoutError, NNTPError,
                    PeerAuthError, ValueError) as exc:
                self.fails[key] = self.fails.get(key, 0) + 1
                log.info("could not pull from announced node %s: %s", a.name, exc)
        return results

    async def run_forever(self) -> None:
        await asyncio.sleep(random.uniform(60, 300))      # after the node and Tor are up
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - never let this stop the node
                log.exception("pulling from announced nodes failed")
            await asyncio.sleep(self.interval * random.uniform(0.8, 1.2))
