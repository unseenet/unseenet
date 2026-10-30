"""``XUN-FETCH``: an article a share refers to (UN-RFC 0060 section 6.1).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file

FETCHES_PER_MINUTE = 30          # section 6.2 step 6: fetches one connection starts


class FetchCommands:
    async def cmd_xun_fetch(self, args):
        """``XUN-FETCH <message-id> <group-id>``: ``220 0 <message-id>`` and the article (or
        its newest version), ``436`` while the node fetches it from a peer, ``430`` when
        it is gone or nowhere, ``503`` when the node does not fetch that group."""
        if len(args) != 2 or not (args[0].startswith("<") and args[0].endswith(">")):
            self.send("501 XUN-FETCH <message-id> <group-id>")
            return
        mid, gid = args
        try:
            split_group_id(gid)
        except ValueError:
            self.send("501 not a Group ID")
            return
        if not self.peer and self.node.held_target(mid, gid) is None:
            now = time.monotonic()
            recent = getattr(self, "_fetch_requests", [])
            recent = [t for t in recent if now - t < 60]
            if len(recent) >= FETCHES_PER_MINUTE:
                self._fetch_requests = recent
                self.send("436 too many fetches; try again in a minute")
                return
            recent.append(now)
            self._fetch_requests = recent
        code, raw = await self.node.fetch_target(mid, gid)
        if code == 220 and raw is not None:
            self.send(f"220 0 {Article.from_bytes(raw).message_id}")
            self.writer.write(dot_stuff(raw))
            if not self.peer:
                self.node.stats.served_one()
        else:
            self.send({430: "430 no such article", 436: "436 try later",
                       503: "503 not fetched here"}[code])
