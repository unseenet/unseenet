"""One connection to the node (ONNTP, UN-RFC 0005): the command loop and what all commands share.

Belongs here: ``Session.__init__``, reading command lines and dispatching them to
``cmd_<name>`` (``run``), a full node turning clients away (#296), CAPABILITIES, and
handing an article to ``Node.accept``.

The commands are in the files named ``*_commands.py``: auth, lists, reading, posting,
peering, blobs.

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class ConnectionBase:
    IDLE_SECONDS = 600.0       # a connection silent this long is closed

    def __init__(self, node: Node, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.node, self.reader, self.writer = node, reader, writer
        self.group: str | None = None
        self.current: int | None = None
        self.peer: str | None = None
        self._user: str | None = None
        self._challenge: tuple[bytes, bytes] | None = None   # (claimed key, nonce)
        self._auth_failures = 0
        self._reconcile_rounds = 0
        self._manifest_requests: list[float] = []   # times of recent XUN-MANIFESTS
        self.full = False                            # opened when the node was full (#296)
        self.staged: dict[str, tuple[bytes, float]] = {}   # UN-RFC 0027 6.2: blob ID -> (octets, when)

    def send(self, line: str) -> None:
        """Send one line to the other side (CRLF added). Buffered; ``run`` drains it."""
        self.writer.write(line.encode("utf-8") + b"\r\n")

    async def run(self) -> None:
        """The command loop: greet with ``200``, read a command a line at a time and answer
        it, until QUIT, an idle connection (``IDLE_SECONDS``) or the client goes."""
        self.send(f"200 Unseenet node {__version__} ready (posting ok)")
        while True:
            await self.writer.drain()
            raw = await asyncio.wait_for(self.reader.readline(), timeout=self.IDLE_SECONDS)
            if not raw:
                return
            if len(raw) > MAX_LINE:
                self.send("501 line too long")
                continue
            parts = raw.decode("utf-8", "replace").strip().split()
            if not parts:
                continue
            cmd, args = parts[0].upper(), parts[1:]
            if self.full and not self.peer and cmd not in FULL_ALLOWED and cmd != "QUIT":
                self.node.stats.client_refused()
                self.send("400 too many connections, try another node")
                await self.writer.drain()
                return
            if cmd == "QUIT":
                self.send("205 bye")
                await self.writer.drain()
                return
            if cmd == "MODE" and args and args[0].upper() in ("READER", "STREAM"):
                if args[0].upper() == "STREAM":
                    self.send("203 streaming permitted")
                else:
                    self.send("200 posting allowed")
                continue
            if cmd == "LIST":
                cmd = "LIST_" + (args[0].upper() if args else "ACTIVE")
                args = args[1:]
            handler = getattr(self, "cmd_" + cmd.lower().replace(".", "_").replace("-", "_"), None)
            if handler is None:
                self.send("500 unknown command")
                continue
            await handler(args)

    # --- capabilities & misc ---
    async def cmd_capabilities(self, args):
        """``CAPABILITIES`` (RFC 3977 5.2): what this node speaks, with the Unseenet
        capabilities of UN-RFC 0005 - its size and postage limits, ripening, files and the
        XUN commands."""
        cfg = self.node.config
        self.send("101 capability list follows")
        for cap in ("VERSION 2", "READER", "POST", "IHAVE", "STREAMING", "AUTHINFO USER",
                    "LIST ACTIVE NEWSGROUPS OVERVIEW.FMT HEADERS", "NEWNEWS", "OVER MSGID", "HDR",
                    "UNSEENET 1",
                    f"UNSEENET-MAXSIZE {cfg.max_size}", f"UNSEENET-MINPOW {cfg.min_pow}",
                    "UNSEENET-MINRIPE " + ("-" if cfg.min_ripe is None else str(cfg.min_ripe)),
                    "UNSEENET-NODEINFO", "UNSEENET-WATCH", "UNSEENET-PEERKEY",
                    "UNSEENET-RECONCILE 1", f"UNSEENET-MANIFESTS {MANIFESTS_MAX}"):
            self.send(cap)
        if cfg.blobs is not None:
            self.send(f"UNSEENET-BLOB {cfg.max_blob}")             # UN-RFC 0027 section 6.1
        self.send(".")

    async def cmd_date(self, args):
        """``DATE`` (RFC 3977 7.1): the node's time in UTC - ``111 yyyymmddhhmmss``."""
        self.send("111 " + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))

    async def cmd_help(self, args):
        """``HELP``: points to UN-RFC 0005 for the supported commands - ``100``."""
        self.send("100 help text follows")
        self.send("See UN-RFC 0005 for the supported command profile.")
        self.send(".")

    # --- posting ---
    def _try_accept(self, raw: bytes, from_peer: bool = False) -> ArticleError | None:
        try:
            self.node.accept(raw, source=self.peer, from_peer=from_peer,
                             staged=None if from_peer else self._fresh_staged())
            return None
        except ArticleError as err:
            log.debug("rejected: %s", err)
            return err

    def _peer_allowed(self) -> bool:
        if self.node.config.require_peer_auth and not self.peer:
            self.send("480 peer authentication required")
            return False
        return True
