"""Catching up from peers by pulling (UN-RFC 0005 section 5.3, UN-RFC 0017, 0040).

Pushing (peering.py) delivers new articles as they arrive. Pulling fills the
gaps: a new node gets the history of the groups it carries, and a node that
was down gets what it missed. It uses only reader commands (DATE, NEWNEWS,
ARTICLE, XUN-RECONCILE), so it works with any node, also one that does not
list us as a peer.

Key-bound state (inboxes, profiles, ...) is not listed by NEWNEWS part 1 on
nodes that follow UN-RFC 0040, so before NEWNEWS a pull reconciles it with
XUN-RECONCILE when that is due (section 6): on the first pull from a peer,
after a pause longer than the peer keeps its record, once a day, and soon after
the peer offered an article whose key-bound group we hold no manifest for.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import Counter
from datetime import datetime, timedelta, timezone

import time

from ..core.article import Article, ArticleError
from ..core.groups import is_key_bound
from ..core.reconcile import MAX_ROUNDS, ReconcileError, reconcile
from ..nntp import Client, NNTPError, strip_reader_headers
from .peering import PeerAuthError, WrongNodeError, authenticate_with_key
from .server import Node, PeerConfig

log = logging.getLogger("unseenet.pulling")

OVERLAP = timedelta(minutes=15)      # re-ask a little: articles arriving during the last pull
MAX_PER_RUN = 5000                   # the rest comes next run
KEEP = timedelta(days=7)             # how long a peer keeps its record, in doubt (UN-RFC 0040, 6)
RECONCILE_EVERY = 86400.0            # once a day, at a random time
PEER_ROUNDS = 4096                   # rounds per exchange when the peer knows us


class Puller:
    """Pulls what a peer has that this node has not seen."""

    def __init__(self, node: Node, peer: PeerConfig, socks_port: int | None = None,
                 interval: float | None = None):
        self.node, self.peer, self.socks_port = node, peer, socks_port
        self.interval = interval if interval is not None else node.config.pull_interval

    async def run_once(self) -> dict:
        """One catch-up. Returns counts: listed, fetched, accepted and rejections by
        reason, and what a reconciliation found if there was one."""
        store, peer = self.node.store, self.peer
        result: dict = {"listed": 0, "fetched": 0, "accepted": 0, "rejected": Counter(),
                        "reconciled": None}
        if not peer.pull:
            return result
        client = await Client.connect(peer.address, self.socks_port)
        try:
            await client.fetch_capabilities()
            known = False
            if peer.key:
                try:   # proves it is the node we meant; as a peer we also get articles as stored
                    await authenticate_with_key(client, self.node.key, peer.public_key())
                    known = True
                except WrongNodeError:
                    raise
                except PeerAuthError as exc:   # it does not list us: reading is open to anyone
                    log.debug("pulling from %s as a reader: %s", peer.name, exc)
            _, text = await client.command("DATE", (111,))
            their_now = datetime.strptime(text.split()[0], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            last = store.pulled_since(peer.name)
            budget = [MAX_PER_RUN]
            if client.capability("UNSEENET-RECONCILE") is not None \
                    and self._reconcile_due(last, their_now):
                await self._reconcile(client, known, result, budget)
            if last is None:          # first time: everything within our retention
                since = their_now - timedelta(days=self.node.config.retention_days)
            else:
                since = datetime.fromtimestamp(last, timezone.utc) - OVERLAP
            ids = await client.multiline(
                f"NEWNEWS {peer.pull} {since:%Y%m%d %H%M%S} GMT", 230)
            wanted = [i.strip() for i in ids if i.strip() and not store.seen(i.strip())
                      and not store.refused_from(i.strip(), peer.name)]
            result["listed"] = len(ids)
            for msgid in wanted[:budget[0]]:
                await self._fetch(client, msgid, result)
            if len(wanted) <= budget[0]:
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

    # --- one article ---
    async def _fetch(self, client: Client, msgid: str, result: dict) -> None:
        store, peer = self.node.store, self.peer
        raw = await client.article(msgid)
        if raw is None:            # expired or cancelled meanwhile
            return
        result["fetched"] += 1
        raw = strip_reader_headers(raw)
        for attempt in range(2):
            try:
                self.node.accept(raw, source=peer.name, from_peer=True, how="pull")
                result["accepted"] += 1
                return
            except ArticleError as err:
                # a key-bound group whose manifest we lack: get it from this peer, once
                if err.reason == "later" and attempt == 0 \
                        and await self._fetch_manifest(client, raw, result):
                    continue
                result["rejected"][err.reason] += 1
                # "later": a comment before its thread (UN-RFC 0030, 4.1); fetch again
                if err.reason not in ("duplicate", "later"):
                    # Do not fetch it from this peer again, but do not refuse the
                    # article itself: a client may post it here, our policy may
                    # change, or its group's manifest may still be on its way (#132).
                    store.refuse(msgid, peer.name, err.reason)
                    store.db.commit()
                return

    async def _fetch_manifest(self, client: Client, raw: bytes, result: dict) -> bool:
        """The manifests of the key-bound group ``raw`` is in, from this peer (UN-RFC 0040
        section 6). True if we now hold the group's manifest."""
        try:
            group = Article.from_bytes(raw).group
        except ArticleError:
            return False
        store = self.node.store
        if not is_key_bound(group) or store.known_group(group):
            return store.known_group(group)
        if client.capability("UNSEENET-MANIFESTS") is not None:    # UN-RFC 0041 4.3
            try:
                [answer] = await client.manifests([(group, None)])
            except NNTPError:
                return False
            if answer.code == 220 and answer.raw:
                result["fetched"] += 1
                try:
                    self.node.accept(answer.raw, source=self.peer.name, from_peer=True,
                                     how="pull")
                    result["accepted"] += 1
                except ArticleError:
                    pass
            return store.known_group(group)
        try:
            _, low, high = await client.group(group)
            if high < low:
                return False
            lines = await client.multiline(f"HDR Control {low}-{high}", 225)
        except NNTPError:
            return False
        for line in lines:
            number, _, control = line.partition(" ")
            if control.split()[:1] != ["manifest"] or not number.isdigit():
                continue
            art = await client.article(number)
            if art is None:
                continue
            result["fetched"] += 1
            try:
                self.node.accept(strip_reader_headers(art), source=self.peer.name,
                                 from_peer=True, how="pull")
                result["accepted"] += 1
            except ArticleError:
                pass
        return store.known_group(group)

    # --- key-bound state (UN-RFC 0040 section 6) ---
    def _reconcile_due(self, last: int | None, their_now: datetime) -> bool:
        name = self.peer.name
        return (last is None
                or their_now - datetime.fromtimestamp(last, timezone.utc) > KEEP
                or name in self.node.reconcile_wanted
                or self.node.store.reconcile_due(name))

    async def _reconcile(self, client: Client, known: bool, result: dict,
                         budget: list[int]) -> None:
        """Reconcile, fetch what we lack (from ``budget``), offer what the peer lacks."""
        store, peer = self.node.store, self.peer
        store.kb_sweep()
        try:
            r = await reconcile(client.reconcile, store,
                                max_rounds=PEER_ROUNDS if known else MAX_ROUNDS)
        except (ReconcileError, NNTPError) as exc:
            log.warning("reconcile with %s: %s", peer.name, exc)
            return
        need = [m for m in r.need if not store.seen(m) and not store.refused_from(m, peer.name)]
        all_fetched = len(need) <= budget[0]
        for msgid in need[:budget[0]]:
            await self._fetch(client, msgid, result)
        budget[0] = max(0, budget[0] - len(need))
        offered = self.node.offer(peer.name, r.offer)
        result["reconciled"] = {"rounds": r.rounds, "need": len(need), "offered": offered,
                                "complete": r.complete}
        log.info("reconciled with %s in %d rounds: %d to fetch, %d offered%s", peer.name,
                 r.rounds, len(need), offered, "" if r.complete else " (not finished)")
        if r.complete and all_fetched:     # else again next run, from where we are
            store.set_reconciled(peer.name, time.time() + RECONCILE_EVERY * random.uniform(0.75, 1.25))
            self.node.reconcile_wanted.discard(peer.name)

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
