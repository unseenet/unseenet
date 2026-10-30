"""Fetching a shared article from peers (UN-RFC 0060 section 6.2).

Belongs here: ``fetch_target`` - what a node answers when a client asks for an article
a share refers to: the article or its newest version if held, gone if a cancel was
seen, otherwise fetched from the peers whose groups cover it, at most three at a time,
checked, and kept in a cache of its own for at most a day; misses are remembered for
a while so that random Message-IDs cannot make the node flood its peers.

The cache is never part of a group: it is not stored, listed, forwarded or counted.

Not here: the command (``XUN-FETCH``, fetch_commands.py).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time

FETCH_CACHE_SECONDS = 24 * 3600.0     # section 6.2 step 5
FETCH_MISS_SECONDS = 600.0            # step 6: "for some minutes"
FETCH_PEERS_AT_ONCE = 3               # step 3
FETCH_HOLD_SECONDS = 10.0             # step 3: hold the question, then 436
FETCH_TIMEOUT = 60.0                  # one peer, over Tor
FETCH_CACHE_MAX = 5000


class Fetching:
    """``fetch_target`` and its cache. Answers are ``(code, raw)`` with code 220 (raw
    is the article), 430 (gone or not found), 436 (still fetching) or 503 (not here)."""

    def _fetch_state(self) -> tuple[dict, dict, dict]:
        if not hasattr(self, "_fetch_cache"):
            self._fetch_cache: dict[str, tuple[float, bytes]] = {}      # mid -> (until, raw)
            self._fetch_misses: dict[str, float] = {}                   # mid -> until
            self._fetch_tasks: dict[str, asyncio.Task] = {}
        return self._fetch_cache, self._fetch_misses, self._fetch_tasks

    def fetches(self, group_id: str) -> bool:
        """Whether the node fetches articles of ``group_id`` for its users (section
        6.4): groups it carries need none; the operator may turn fetching off for the
        others, and it is off for groups the node excludes on purpose."""
        if not self.config.fetch:
            return False
        return not (self.config.excludes and wildmat(self.config.excludes, group_id))

    def held_target(self, message_id: str, group_id: str) -> tuple[int, bytes | None] | None:
        """Step 1-2: the target or its newest version if held (220), 430 if a cancel
        of it was seen or it was here and is gone; None when not known here."""
        raw = self.store.get(message_id)
        if raw is None:
            edit = self.store.supersede_for(message_id)
            if edit is not None and edit[2] == group_id:
                raw = self.store.get(edit[0])
                if raw is None and self.store.seen(edit[0]):
                    return 430, None
        if raw is not None:
            meta = self.store.get_meta(message_id) or self.store.get_meta(
                Article.from_bytes(raw).message_id)
            if meta is None or meta[0] != group_id:
                return 430, None          # not in the group the share names
            return 220, raw
        if self.store.cancel_for(message_id) is not None:
            return 430, None
        if self.store.seen(message_id) and self.store.manifest(group_id) is not None:
            return 430, None              # carried here, and gone: expired or withdrawn
        return None

    def check_fetched(self, raw: bytes, message_id: str, group_id: str) -> bool:
        """Step 4: signature, postage and group, and the article asked for or a newer
        version that names it in Supersedes."""
        try:
            art = Article.from_bytes(raw)
            validate_structure(art, raw_size=len(raw), max_size=self.config.max_size)
        except (ArticleError, ValueError):
            return False
        if art.group != group_id or art.control is not None or "Encrypted" in art:
            return False
        if art.proven_pow() < self.config.min_pow:
            return False
        if art.message_id == message_id:
            return True
        try:
            return message_id in parse_supersedes(art)
        except ArticleError:
            return False

    async def _fetch_from_peers(self, message_id: str, group_id: str) -> bytes | None:
        from ...nntp import Client, strip_reader_headers
        peers = [p for p in self.config.peers if wildmat(p.groups, group_id)]
        socks = getattr(self, "socks_port", None)

        async def one(peer) -> bytes | None:
            client = await asyncio.wait_for(Client.connect(peer.address, socks), FETCH_TIMEOUT)
            try:
                raw = await asyncio.wait_for(client.article(message_id), FETCH_TIMEOUT)
            finally:
                await client.quit()
            if raw is None:
                return None
            raw = strip_reader_headers(raw)          # Path/Xref a node adds for readers
            return raw if self.check_fetched(raw, message_id, group_id) else None

        for i in range(0, len(peers), FETCH_PEERS_AT_ONCE):
            batch = peers[i:i + FETCH_PEERS_AT_ONCE]
            for got in await asyncio.gather(*(one(p) for p in batch), return_exceptions=True):
                if isinstance(got, bytes):
                    return got
        return None

    async def _fetch_and_keep(self, message_id: str, group_id: str) -> None:
        cache, misses, tasks = self._fetch_state()
        try:
            raw = await self._fetch_from_peers(message_id, group_id)
        except Exception as exc:  # noqa: BLE001  a failed fetch is a miss
            log.debug("fetching %s failed: %s", message_id, exc)
            raw = None
        now = time.monotonic()
        if raw is None:
            misses[message_id] = now + _s.FETCH_MISS_SECONDS
        else:
            if len(cache) >= FETCH_CACHE_MAX:
                for k in [k for k, (u, _) in cache.items() if u < now] or list(cache)[:100]:
                    cache.pop(k, None)
            cache[message_id] = (now + _s.FETCH_CACHE_SECONDS, raw)
        tasks.pop(message_id, None)

    async def fetch_target(self, message_id: str, group_id: str,
                           hold: float | None = None) -> tuple[int, bytes | None]:
        """Section 6.2: answer a request for a shared article (see the class)."""
        held = self.held_target(message_id, group_id)
        if held is not None:
            return held
        cache, misses, tasks = self._fetch_state()
        now = time.monotonic()
        hit = cache.get(message_id)
        if hit is not None:
            if hit[0] > now:
                return 220, hit[1]
            cache.pop(message_id, None)
        if self.store.manifest(group_id) is None and not self.fetches(group_id):
            return 503, None
        if misses.get(message_id, 0) > now:
            return 430, None
        misses.pop(message_id, None)
        task = tasks.get(message_id)
        if task is None:
            task = tasks[message_id] = asyncio.ensure_future(
                self._fetch_and_keep(message_id, group_id))
        try:
            await asyncio.wait_for(asyncio.shield(task),
                                   _s.FETCH_HOLD_SECONDS if hold is None else hold)
        except asyncio.TimeoutError:
            return 436, None
        hit = cache.get(message_id)
        return (220, hit[1]) if hit is not None else (430, None)
