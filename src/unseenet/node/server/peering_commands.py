"""Peers and catching up: IHAVE, CHECK, TAKETHIS (UN-RFC 0005 section 5), NEWNEWS with the
groups' state first (UN-RFC 0017), XUN-RECONCILE (UN-RFC 0040) and XUN-MANIFESTS
(UN-RFC 0041).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class PeeringCommands:
    async def cmd_newnews(self, args):
        if len(args) < 3:
            self.send("501 syntax: NEWNEWS wildmat yyyymmdd hhmmss [GMT]")
            return
        try:
            stamp = datetime.strptime(args[1] + args[2], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            self.send("501 bad date")
            return
        store, pattern, since = self.node.store, args[0], int(stamp.timestamp())
        self.send("230 list of new articles follows")
        listed: set[str] = set()
        # UN-RFC 0017: first the state of every matching group, whatever its age, so
        # that a node catching up can accept what follows; then what arrived since.
        # Key-bound groups are not in part 1 (UN-RFC 0040 section 5): their state is
        # reconciled, and what changes still comes in part 2.
        for gid, *_ in store.groups(ordinary=True):
            if wildmat(pattern, gid):
                for msgid in store.state_ids(gid):
                    if msgid not in listed:
                        listed.add(msgid)
                        self.send(msgid)
            await self.writer.drain()
        for msgid, gid in store.received_since(since):
            if msgid not in listed and wildmat(pattern, gid):
                listed.add(msgid)
                self.send(msgid)
        for msgid, gid in store.removals_since(since):
            if wildmat(pattern, gid):
                self.send(msgid)
        self.send(".")

    async def cmd_xun_reconcile(self, args):
        """UN-RFC 0040 section 4.3: compare key-bound state by range fingerprints.

        Open to readers too, so anyone can check a node; a reader gets one exchange
        (MAX_ROUNDS rounds) per connection, an authenticated peer is not limited."""
        try:
            block = await read_block(self.reader, RECONCILE_MAX_BYTES)
        except ValueError:
            self.send("501 reconciliation message too large")
            return
        if not self.peer:
            self._reconcile_rounds += 1
            if self._reconcile_rounds > reconcile.MAX_ROUNDS:
                self.send("400 too many reconciliation rounds; connect again")
                await self.writer.drain()
                raise ConnectionError("reconciliation round limit")
        try:
            ranges = reconcile.parse_message(block.decode("utf-8", "replace").splitlines())
        except (reconcile.ReconcileError, ValueError) as err:
            self.send(f"501 {err}")
            return
        store = self.node.store
        store.kb_sweep()
        lines = reconcile.format_message(reconcile.answer(store, ranges))
        self.send("295 reconcile")
        self.writer.write(dot_stuff("\r\n".join(lines).encode()) if lines else b".\r\n")

    MANIFESTS_PER_MINUTE = 60          # requests from an unauthenticated reader

    async def cmd_xun_manifests(self, args):
        """UN-RFC 0041: the current manifests of up to MANIFESTS_MAX groups at once.

        One answer per line, in order, as ARTICLE/STAT answer: 220 with the article
        as stored (no Path/Xref), 223 if the client holds the current one, 411 if we
        have none, 431 for lines past _s.MANIFESTS_ANSWER_BYTES (section 2.3)."""
        try:
            block = await read_block(self.reader, MANIFESTS_MAX * (MAX_LINE + 2))
        except ValueError:
            self.send(f"501 more than {MANIFESTS_MAX} lines")
            return
        entries: list[tuple[str, str | None]] = []
        for line in block.decode("utf-8", "replace").splitlines():
            parts = line.split()
            if not parts or len(parts) > 2 or (len(parts) == 2 and not (
                    parts[1].startswith("<") and parts[1].endswith(">"))):
                self.send("501 malformed line: <group-id> [<message-id>]")
                return
            entries.append((parts[0], parts[1] if len(parts) == 2 else None))
        if not entries or len(entries) > MANIFESTS_MAX:
            self.send(f"501 between 1 and {MANIFESTS_MAX} lines")
            return
        if len({gid for gid, _ in entries}) != len(entries):
            self.send("501 a Group ID appears twice")
            return
        if not self.peer:
            now = time.monotonic()
            self._manifest_requests = [t for t in self._manifest_requests if now - t < 60]
            if len(self._manifest_requests) >= self.MANIFESTS_PER_MINUTE:
                self.send("400 too many manifest requests; wait a minute")
                return
            self._manifest_requests.append(now)
        store, sent, full = self.node.store, 0, False
        self.send(f"296 {len(entries)} manifests follow")
        for gid, held in entries:
            if full:
                self.send(f"431 {gid}")
                continue
            m = None if store.tombstone(gid) else store.manifest(gid)
            raw = store.get(m.message_id) if m else None
            if raw is None:
                self.send(f"411 {gid}")
            elif held == m.message_id:
                self.send(f"223 0 {m.message_id} {gid}")
            elif sent and sent + len(raw) > _s.MANIFESTS_ANSWER_BYTES:
                full = True
                self.send(f"431 {gid}")
            else:
                sent += len(raw)
                self.send(f"220 0 {m.message_id} {gid}")
                self.writer.write(dot_stuff(raw))
                await self.writer.drain()

    async def cmd_ihave(self, args):
        if not args or not self._peer_allowed():
            return
        if self.node.store.seen(args[0]):
            self.send("435 not wanted")
            return
        self.send("335 send it")
        await self.writer.drain()
        raw = await read_block(self.reader, self.node.config.max_size + 1024)
        err = self._try_accept(raw, from_peer=True)
        self.send("235 transferred" if err is None
                  else "436 try again later" if err.reason == "later" else "437 rejected")

    async def cmd_check(self, args):
        if not args or not self._peer_allowed():
            return
        self.send(f"{438 if self.node.store.seen(args[0]) else 238} {args[0]}")

    async def cmd_takethis(self, args):
        if not args:
            self.send("501 syntax")
            return
        raw = await read_block(self.reader, self.node.config.max_size + 1024)
        if self.node.config.require_peer_auth and not self.peer:
            self.send(f"439 {args[0]}")
            return
        err = self._try_accept(raw, from_peer=True)
        # 431 after TAKETHIS: our peers retry it later (UN-RFC 0005 5.2, UN-RFC 0030 4.1)
        self.send(f"{239 if err is None else 431 if err.reason == 'later' else 439} {args[0]}")
