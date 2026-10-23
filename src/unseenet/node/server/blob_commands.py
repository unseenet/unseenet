"""Blobs on a connection (UN-RFC 0027 section 6): BLOBPOST stages a blob for this
connection, BLOB sends one, ``436`` while it is being fetched.

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class BlobCommands:
    # --- blobs (UN-RFC 0027 section 6) ---
    def _fresh_staged(self) -> dict:
        """Staged blobs older than an hour are gone (section 6.2)."""
        cutoff = time.monotonic() - bl.STAGE_SECONDS
        for bid in [b for b, (_, at) in self.staged.items() if at < cutoff]:
            del self.staged[bid]
        return self.staged

    async def cmd_blobpost(self, args):
        """BLOBPOST <blob-id> <octets>: stage a blob for this connection (6.2)."""
        cfg = self.node.config
        if len(args) != 2 or not bl.valid_id(args[0]) or not args[1].isdigit():
            self.send("501 syntax: BLOBPOST <blob-id> <octets>")
            return
        bid, size = args[0], int(args[1])
        if cfg.blobs is None:
            self.send("445 unsupported")
            return
        if self.node.store.blob_refused(bid):
            self.send("445 refused")
            return
        if self.node.blobs.has(bid) or bid in self._fresh_staged():
            self.send("245 blob staged")
            return
        if not 0 < size <= cfg.max_blob:
            self.send("445 size")
            return
        held = sum(len(o) for o, _ in self.staged.values())
        if (len(self.staged) >= max(bl.STAGE_MIN_COUNT, cfg.blobs.get("stage_count", 0))
                or held + size > max(bl.STAGE_MIN_BYTES, cfg.blobs.get("stage_bytes", 0))):
            self.send("445 limit")
            return
        self.send("345 send blob")
        await self.writer.drain()
        octets = await asyncio.wait_for(self.reader.readexactly(size), timeout=self.IDLE_SECONDS)
        if bl.blob_id(octets) != bid:
            self.send("445 hash")
            return
        self.staged[bid] = (octets, time.monotonic())
        self.send("245 blob staged")

    async def cmd_blob(self, args):
        """BLOB <blob-id>: the blob as raw octets (6.4). Never had and deleted are alike."""
        if len(args) != 1 or not bl.valid_id(args[0]):
            self.send("501 syntax: BLOB <blob-id>")
            return
        octets = (self.node.blobs.get(args[0]) if self.node.config.blobs is not None
                  and not self.node.store.blob_refused(args[0]) else None)
        if octets is None:
            self.send("436 try later" if self.node.fetching(args[0]) else "430 no such blob")
            return
        self.send(f"226 {len(octets)} {args[0]}")
        self.writer.write(octets)
