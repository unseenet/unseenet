"""The node itself: what it is made of and how it is reached.

Belongs here: ``Node.__init__`` (the store, the blob store, the config, the node key,
the stats), the watchers of new articles (push, UN-RFC 0008), the peers it is
configured with, what it says about itself (``node_info``, UN-RFC 0011), and serving
connections (``serve``: each connection is a ``Session``, see connection.py).

Not here: the rules for taking an article (accepting.py and the files it points to).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class NodeBase:
    blobs: bl.BlobStore          # UN-RFC 0027: the octets, next to the database

    def __init__(self, store: Store, config: NodeConfig | None = None,
                 key: crypto.Identity | None = None, blobs: bl.BlobStore | None = None):
        self.store = store
        # blobs as files next to the database; in memory for a store in memory (tests)
        self.blobs = blobs or bl.BlobStore(store.path.parent / "blobs" if store.path else None)
        self.config = config or NodeConfig()
        self.client_limit = self.config.client_limit()      # worked out once (#296)
        # The node key identifies this node to its peers (UN-RFC 0016). A real node
        # keeps it sealed in its data directory; without one (tests) it is temporary.
        self.key = key or crypto.Identity.generate()
        self._listeners: list[asyncio.Event] = []
        self._watchers: list[tuple[str, asyncio.Queue]] = []   # UN-RFC 0008 section 2
        self.stats = Stats()                  # for the operator's monitor (node/stats.py)
        self._blocks: dict[str, tuple[float, dict]] = {}   # group name -> (time, blocks)
        # comments that came before their thread (UN-RFC 0030, 4.1):
        # thread root Message-ID -> [(time held, raw, source, from_peer)]
        self._held: dict[str, list[tuple[float, bytes, str | None, bool]]] = {}
        # UN-RFC 0040 section 6: key-bound groups whose manifest a peer's article
        # showed we lack, since when; and the peers to reconcile with soon.
        self._kb_waiting: dict[str, float] = {}
        self.reconcile_wanted: set[str] = set()
        # UN-RFC 0025 section 3.4: each key's chain and how many segments are verified
        self._ripe_cache: dict[bytes, tuple[rp.Chain, int]] = {}
        # UN-RFC 0027 section 6.3: articles from peers whose blobs we are fetching,
        # Message-ID -> {"group", "source", "missing": {blob ID: octets}, "until"}
        self.blob_wait: dict[str, dict] = {}

    def watch(self, pattern: str) -> asyncio.Queue:
        """A queue that receives the Message-ID and group of every new article whose group
        matches ``pattern`` (a wildmat): push for XUN-WATCH (UN-RFC 0008)."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._watchers.append((pattern, queue))
        return queue

    def unwatch(self, queue: asyncio.Queue) -> None:
        """Stop sending new articles to a watcher's queue (see ``watch``)."""
        self._watchers = [(p, q) for p, q in self._watchers if q is not queue]

    def _notify_watchers(self, art: Article) -> None:
        number = self.store.number_of(art.message_id)
        if number is None:
            return
        for pattern, queue in self._watchers:
            if wildmat(pattern, art.group):
                try:
                    queue.put_nowait((art.group, number, art.message_id))
                except asyncio.QueueFull:
                    pass                      # a slow watcher catches up by polling

    def peer_config(self, name: str) -> PeerConfig | None:
        """The configured peer of that name (``[[peer]]`` in ``node.toml``), or None."""
        for peer in self.config.peers:
            if peer.name == name:
                return peer
        return None

    def subscribe(self) -> asyncio.Event:
        """An event that is set whenever a new article is queued for peers."""
        event = asyncio.Event()
        self._listeners.append(event)
        return event

    def node_info(self) -> dict:
        """The node's information (UN-RFC 0011 section 4): name, software, node key, its
        policy (new groups, postage, ripening, retention, size, blocks, profiles, pictures,
        sites, files) and the operator's contact, as ``LIST UNSEENET-NODEINFO`` sends it."""
        cfg = self.config
        op = cfg.operator or {}
        info = {"v": 1, "name": cfg.name, "software": f"unseenet {__version__}",
                "node_key": self.key.key_text,
                "policy": {"new_groups": cfg.new_groups, "min_pow": cfg.min_pow,
                           "min_ripe": "-" if cfg.min_ripe is None else cfg.min_ripe,
                           "retention_days": cfg.retention_days, "max_size": cfg.max_size,
                           "archive": False, "honours_blocks": cfg.honour_blocks,
                           "profiles": cfg.profiles, "avatars": cfg.avatars,
                           "sites": cfg.sites,
                           "logging": op.get("logging", "accepted articles only, no reading activity")}}
        excludes = self.excludes()
        if excludes:
            info["policy"]["excludes"] = excludes
        if cfg.blobs is not None:                   # UN-RFC 0027 section 8: carried, and how
            b = cfg.blobs
            info["policy"]["blobs"] = {
                "max_size": cfg.max_blob, "retention_days": b.get("retention_days", 30),
                "encrypted": bool(b.get("encrypted", False)),
                "refusal_lists": bool(b.get("refusal_keys")),
                "daily_per_key": b.get("daily_per_key", bl.DAILY_PER_KEY),
                "daily_per_group": b.get("daily_per_group", bl.DAILY_PER_GROUP)}
        for key in ("operator", "contact", "description"):
            value = op.get("key" if key == "operator" else key)
            if value:
                info[key] = value
        return info

    # ------------------------------------------------------------------
    # ONNTP server
    # ------------------------------------------------------------------
    async def serve(self, host: str = "127.0.0.1", port: int = 1119) -> asyncio.base_events.Server:
        """Listen for ONNTP connections on ``host:port``; each one is a ``Session``. Tor
        publishes the onion service in front of it."""
        return await asyncio.start_server(self._session, host, port, limit=MAX_LINE * 200)

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        session = _s.Session(self, reader, writer)
        # full (#296): only peers may go on - they authenticate first; everyone else
        # gets 400 at their first other command and goes to another node
        session.full = self.stats.open - self.stats.peers_open >= self.client_limit
        self.stats.session_opened()
        try:
            await session.run()
        except (ConnectionError, asyncio.IncompleteReadError, TimeoutError):
            pass        # gone, cut off, or idle for longer than the session allows
        finally:
            self.stats.session_closed(was_peer=session.peer is not None)
            writer.close()
