"""Lists and push: LIST ACTIVE and NEWSGROUPS (ordinary groups only, UN-RFC 0040 section 3),
XUN-WATCH (UN-RFC 0008), and the node's information (UN-RFC 0011).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class ListsCommands:
    # --- lists ---
    async def cmd_list_active(self, args):
        pattern = args[0] if args else "*"
        self.send("215 list follows")
        for gid, high, low, _ in self.node.store.groups(ordinary=True):   # UN-RFC 0040, 3
            if wildmat(pattern, gid):
                self.send(f"{gid} {high} {low} y")
        self.send(".")

    async def cmd_list_newsgroups(self, args):
        pattern = args[0] if args else "*"
        self.send("215 descriptions follow")
        for gid, _, _, desc in self.node.store.groups(ordinary=True):
            if wildmat(pattern, gid):
                self.send(f"{gid}\t{desc}")
        self.send(".")

    async def cmd_xun_watch(self, args):
        """UN-RFC 0008: tell the client about new articles until it sends DONE."""
        pattern = args[0] if args else "*"
        queue = self.node.watch(pattern)
        self.send("290 watching")
        await self.writer.drain()
        line_task = asyncio.ensure_future(self.reader.readline())
        get_task = asyncio.ensure_future(queue.get())
        try:
            while True:
                done, _ = await asyncio.wait({line_task, get_task}, timeout=300,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    self.send("293 keepalive")
                if get_task in done:
                    group, number, msgid = get_task.result()
                    self.send(f"291 {group} {number} {msgid}")
                    get_task = asyncio.ensure_future(queue.get())
                await self.writer.drain()
                if line_task in done:
                    line = line_task.result()
                    if not line:
                        raise ConnectionError("client went away while watching")
                    if line.strip().upper() == b"DONE":
                        self.send("292 done")
                        return
                    line_task = asyncio.ensure_future(self.reader.readline())
        finally:
            self.node.unwatch(queue)
            for task in (line_task, get_task):
                task.cancel()

    async def cmd_list_unseenet_nodeinfo(self, args):
        """UN-RFC 0011: who runs this node and its policy."""
        self.send("215 node information follows")
        self.send(canonical_json(self.node.node_info()))
        self.send(".")
