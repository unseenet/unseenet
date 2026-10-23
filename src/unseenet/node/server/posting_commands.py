"""Posting from a client: POST (with the blobs staged on this connection, UN-RFC 0027).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class PostingCommands:
    async def cmd_post(self, args):
        """``POST`` (RFC 3977 6.3.1): a client's article - ``340`` send it, then ``240``
        taken or ``441`` with the reason. Blobs staged with BLOBPOST on this connection
        go with it (UN-RFC 0027 section 6)."""
        self.send("340 send article")
        await self.writer.drain()
        try:
            raw = await read_block(self.reader, self.node.config.max_size)
        except ValueError:
            self.send("441 size")
            return
        err = self._try_accept(raw)
        self.send("240 article received" if err is None
                  else f"441 {err.reason}{': ' + err.detail if err.detail else ''}")
