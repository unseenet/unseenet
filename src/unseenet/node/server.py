"""ONNTP server and article acceptance (UN-RFC 0002 section 5, 0004, 0005)."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .. import __version__
from ..core.groups import canonical_json
from ..core import crypto
from ..core.article import MAX_SIZE, Article, ArticleError, parse_date, validate_structure
from ..core.groups import Manifest, check_permitted, parse_key_update, split_group_id
from ..core.store import Store
from ..nntp import MAX_LINE, dot_stuff, read_block

log = logging.getLogger("unseenet.node")


@dataclass
class PeerConfig:
    name: str
    address: str                # "xyz.onion" or "host:port" (testing)
    groups: str = "*"           # RFC 3977 wildmat over Group IDs
    password: str | None = None  # shared secret for AUTHINFO


@dataclass
class NodeConfig:
    name: str = "unseenet"              # how this node introduces itself to peers
    max_size: int = MAX_SIZE
    min_pow: int = 18
    retention_days: int = 90
    new_groups: str = "accept"            # "accept" | "trusted" | "manual"
    trusted_owners: list[str] = field(default_factory=list)
    peers: list[PeerConfig] = field(default_factory=list)
    forward_delay: tuple[float, float] = (0.0, 60.0)  # UN-RFC 0005, section 5.5
    require_peer_auth: bool = False
    # UN-RFC 0011: who runs this node and how to reach them
    operator: dict = field(default_factory=dict)   # key, contact, description, logging


def wildmat(pattern: str, text: str) -> bool:
    """RFC 3977 wildmat: comma-separated patterns, '!' negates, last match wins."""
    result = False
    for pat in pattern.split(","):
        neg = pat.startswith("!")
        if fnmatch.fnmatchcase(text, pat[1:] if neg else pat):
            result = not neg
    return result


class Node:
    def __init__(self, store: Store, config: NodeConfig | None = None):
        self.store = store
        self.config = config or NodeConfig()
        self._listeners: list[asyncio.Event] = []

    def subscribe(self) -> asyncio.Event:
        """An event that is set whenever a new article is queued for peers."""
        event = asyncio.Event()
        self._listeners.append(event)
        return event

    # ------------------------------------------------------------------
    # Acceptance pipeline
    # ------------------------------------------------------------------
    def accept(self, raw: bytes, source: str | None = None,
               now: datetime | None = None, from_peer: bool = False) -> Article:
        """Validate and store an article. Raises ArticleError with an RFC 0005 reason.

        ``from_peer`` is true for articles pushed by another node (IHAVE/TAKETHIS),
        authenticated or not; ``source`` names the peer when it authenticated.
        """
        art = Article.from_bytes(raw)
        validate_structure(art, raw_size=len(raw), max_size=self.config.max_size, now=now)
        if self.store.seen(art.message_id):
            raise ArticleError("duplicate")
        now = now or datetime.now(timezone.utc)
        ctl = art.control
        is_manifest = ctl == ["manifest"]
        removed = self.store.tombstone(art.group)
        if removed:
            raise ArticleError("group", "group was removed by its owner" if removed == "owner"
                               else "group was dropped by this node")

        manifest = self.store.manifest(art.group)
        if ctl == ["rmgroup"]:
            return self._accept_rmgroup(art, manifest, raw, source, from_peer)
        if not is_manifest:
            if manifest is None:
                raise ArticleError("group", "group not carried")
            if manifest.local and from_peer:
                raise ArticleError("group", "local group: never accepted from peers")
            retention = min(self.config.retention_days, manifest.retention_days)
            if parse_date(art["Date"]) < now - timedelta(days=retention):
                raise ArticleError("date", "older than retention")

        required = self.config.min_pow
        if manifest is not None and not is_manifest:
            required = max(required, manifest.min_pow)
        if art.proven_pow() < required:
            raise ArticleError("postage", f"need {required} bits")

        if is_manifest:
            self._accept_manifest(art, manifest, raw, from_peer)
        elif ctl:
            self._accept_control(art, manifest, raw)
        else:
            self._check_cancelled(art, manifest)
            check_permitted(art, manifest, self.store.epochs(art.group))
            self.store.add(art, raw)
        self._enqueue(art, source)
        log.info("accepted %s in %s", art.message_id, art.group)
        return art

    def _accept_rmgroup(self, art: Article, manifest: Manifest | None, raw: bytes,
                        source: str | None, from_peer: bool) -> Article:
        """UN-RFC 0013: the owner removes the group from the network."""
        author = art.author_key
        if manifest is not None:
            if author != manifest.owner:
                raise ArticleError("permission", "only the group's owner can remove it")
            if manifest.local and from_peer:
                raise ArticleError("group", "local group: never accepted from peers")
        elif crypto.fingerprint(author) != split_group_id(art.group)[1]:
            raise ArticleError("permission", "only the group's owner can remove it")
        if art.proven_pow() < self.config.min_pow:          # exempt from the group's own minimum
            raise ArticleError("postage", f"need {self.config.min_pow} bits")
        local = manifest is not None and manifest.local
        self.store.remember(art.message_id)
        self.store.add_tombstone(art.group, "owner", art.message_id, raw)
        deleted = self.store.remove_group(art.group)
        if not local:
            self._enqueue(art, source, force=True)
        log.info("group %s removed by its owner (%d articles deleted)", art.group, deleted)
        return art

    def drop_group(self, group_id: str) -> int:
        """UN-RFC 0013 section 3: the operator stops carrying a group on this node."""
        self.store.add_tombstone(group_id, "operator")
        return self.store.remove_group(group_id)

    def _accept_manifest(self, art: Article, current: Manifest | None, raw: bytes,
                         from_peer: bool = False) -> None:
        m = Manifest.from_article(art)
        if m.local and from_peer:
            raise ArticleError("group", "local group: never accepted from peers")
        if current is not None:
            if m.type != current.type or m.owner != current.owner or m.local != current.local:
                raise ArticleError("permission", "manifest may not change type, owner or locality")
        elif not self._allow_new_group(m):
            raise ArticleError("group", "node does not accept this new group")
        self.store.add(art, raw)
        if m.supersedes(current):
            self.store.set_manifest(m)

    def _allow_new_group(self, m: Manifest) -> bool:
        if self.config.new_groups == "accept":
            return True
        if self.config.new_groups == "trusted":
            return crypto.key_to_text(m.owner) in self.config.trusted_owners
        return False  # "manual": operator adds groups out of band

    def _accept_control(self, art: Article, manifest: Manifest, raw: bytes) -> None:
        ctl = art.control or []
        author = art.author_key
        if ctl[0] in ("key-update", "key-grant"):
            if manifest.type != "closed" or author != manifest.owner:
                raise ArticleError("permission", "only the owner of a closed group may issue keys")
            epoch, member_key, _ = parse_key_update(art)
            self.store.add(art, raw)
            if member_key is not None:
                self.store.set_epoch(art.group, epoch, member_key)
        elif ctl[0] == "cancel" and len(ctl) == 2:
            target = ctl[1]
            meta = self.store.get_meta(target)
            privileged = author == manifest.owner or author in manifest.moderators
            if meta is not None:
                group_id, target_author = meta
                if group_id != art.group:
                    raise ArticleError("permission", "cancel for another group")
                if not privileged and crypto.key_from_text(target_author) != author:
                    raise ArticleError("permission", "not allowed to cancel")
                self.store.delete(target)
            else:
                self.store.add_cancel(target, art["Author-Key"], art.group)
            self.store.add(art, raw)
        else:
            raise ArticleError("syntax", f"unknown control {ctl[0]!r}")

    def _check_cancelled(self, art: Article, manifest: Manifest) -> None:
        pending = self.store.cancel_for(art.message_id)
        if not pending:
            return
        author_key, group_id = pending
        canceller = crypto.key_from_text(author_key)
        if group_id == art.group and (canceller == art.author_key or canceller == manifest.owner
                                      or canceller in manifest.moderators):
            self.store.remember(art.message_id)
            raise ArticleError("permission", "article was cancelled")

    def _enqueue(self, art: Article, source: str | None, force: bool = False) -> None:
        manifest = self.store.manifest(art.group)
        if not force and manifest is not None and manifest.local:
            return                       # local groups never leave this node (UN-RFC 0009, 4)
        lo, hi = self.config.forward_delay
        for peer in self.config.peers:
            if peer.name != source and wildmat(peer.groups, art.group):
                self.store.enqueue(peer.name, art.message_id, time.time() + random.uniform(lo, hi))
        for event in self._listeners:
            event.set()

    def node_info(self) -> dict:
        cfg = self.config
        op = cfg.operator or {}
        info = {"v": 1, "name": cfg.name, "software": f"unseenet {__version__}",
                "policy": {"new_groups": cfg.new_groups, "min_pow": cfg.min_pow,
                           "retention_days": cfg.retention_days, "max_size": cfg.max_size,
                           "archive": False,
                           "logging": op.get("logging", "accepted articles only, no reading activity")}}
        for key in ("operator", "contact", "description"):
            value = op.get("key" if key == "operator" else key)
            if value:
                info[key] = value
        return info

    # ------------------------------------------------------------------
    # ONNTP server
    # ------------------------------------------------------------------
    async def serve(self, host: str = "127.0.0.1", port: int = 1119) -> asyncio.base_events.Server:
        return await asyncio.start_server(self._session, host, port, limit=MAX_LINE * 200)

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        session = Session(self, reader, writer)
        try:
            await session.run()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()


class Session:
    def __init__(self, node: Node, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.node, self.reader, self.writer = node, reader, writer
        self.group: str | None = None
        self.current: int | None = None
        self.peer: str | None = None
        self._user: str | None = None

    def send(self, line: str) -> None:
        self.writer.write(line.encode("utf-8") + b"\r\n")

    async def run(self) -> None:
        self.send(f"200 Unseenet node {__version__} ready (posting ok)")
        while True:
            await self.writer.drain()
            raw = await asyncio.wait_for(self.reader.readline(), timeout=600)
            if not raw:
                return
            if len(raw) > MAX_LINE:
                self.send("501 line too long")
                continue
            parts = raw.decode("utf-8", "replace").strip().split()
            if not parts:
                continue
            cmd, args = parts[0].upper(), parts[1:]
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
            handler = getattr(self, "cmd_" + cmd.lower().replace(".", "_"), None)
            if handler is None:
                self.send("500 unknown command")
                continue
            await handler(args)

    # --- capabilities & misc ---
    async def cmd_capabilities(self, args):
        cfg = self.node.config
        self.send("101 capability list follows")
        for cap in ("VERSION 2", "READER", "POST", "IHAVE", "STREAMING", "AUTHINFO USER",
                    "LIST ACTIVE NEWSGROUPS", "NEWNEWS", "UNSEENET 1",
                    f"UNSEENET-MAXSIZE {cfg.max_size}", f"UNSEENET-MINPOW {cfg.min_pow}",
                    "UNSEENET-NODEINFO"):
            self.send(cap)
        self.send(".")

    async def cmd_date(self, args):
        self.send("111 " + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))

    async def cmd_help(self, args):
        self.send("100 help text follows")
        self.send("See UN-RFC 0005 for the supported command profile.")
        self.send(".")

    async def cmd_authinfo(self, args):
        if len(args) < 2:
            self.send("501 syntax")
        elif args[0].upper() == "USER":
            self._user = args[1]
            self.send("381 password required")
        elif args[0].upper() == "PASS" and self._user:
            for peer in self.node.config.peers:
                if peer.name == self._user and peer.password and peer.password == args[1]:
                    self.peer = peer.name
                    self.send("281 authentication accepted")
                    return
            self.send("481 authentication failed")
        else:
            self.send("482 authentication commands issued out of sequence")

    # --- lists ---
    async def cmd_list_active(self, args):
        pattern = args[0] if args else "*"
        self.send("215 list follows")
        for gid, high, low, _ in self.node.store.groups():
            if wildmat(pattern, gid):
                self.send(f"{gid} {high} {low} y")
        self.send(".")

    async def cmd_list_newsgroups(self, args):
        pattern = args[0] if args else "*"
        self.send("215 descriptions follow")
        for gid, _, _, desc in self.node.store.groups():
            if wildmat(pattern, gid):
                self.send(f"{gid}\t{desc}")
        self.send(".")

    async def cmd_list_unseenet_nodeinfo(self, args):
        """UN-RFC 0011: who runs this node and its policy."""
        self.send("215 node information follows")
        self.send(canonical_json(self.node.node_info()))
        self.send(".")

    # --- group navigation ---
    async def cmd_group(self, args):
        removed = self.node.store.tombstone(args[0]) if args else None
        if removed:
            self.send("411 no such group (removed by its owner)" if removed == "owner"
                      else "411 no such group (dropped by this node)")
            return
        if not args or self.node.store.manifest(args[0]) is None:
            self.send("411 no such group")
            return
        self.group = args[0]
        nums = self.node.store.numbers(self.group)
        self.current = nums[0] if nums else None
        low, high = (nums[0], nums[-1]) if nums else (1, 0)
        self.send(f"211 {len(nums)} {low} {high} {self.group}")

    async def cmd_listgroup(self, args):
        if args:
            await self.cmd_group(args[:1])
            if self.group != args[0]:
                return
        if not self.group:
            self.send("412 no group selected")
            return
        nums = self.node.store.numbers(self.group)
        low, high = (nums[0], nums[-1]) if nums else (1, 0)
        self.send(f"211 {len(nums)} {low} {high} {self.group} list follows")
        for n in nums:
            self.send(str(n))
        self.send(".")

    def _lookup(self, args) -> tuple[int, str, bytes] | None:
        store = self.node.store
        if args and args[0].startswith("<"):
            raw = store.get(args[0])
            if raw is None:
                self.send("430 no such article")
                return None
            return 0, args[0], raw
        if not self.group:
            self.send("412 no group selected")
            return None
        number = int(args[0]) if args and args[0].isdigit() else self.current
        found = store.by_number(self.group, number) if number else None
        if not found:
            self.send("423 no such article number")
            return None
        self.current = number
        return number, found[0], found[1]

    def _reader_headers(self, number: int) -> bytes:
        # Synthesized for newsreaders only, never part of the article (UN-RFC 0005, 3).
        xref = f"\r\nXref: unseenet {self.group}:{number}" if number and self.group else ""
        return ("Path: not-for-mail" + xref).encode()

    async def _send_part(self, args, code: int, part: str):
        found = self._lookup(args)
        if not found:
            return
        number, msgid, raw = found
        head, _, body = raw.partition(b"\r\n\r\n")
        if not self.peer:
            head = head + b"\r\n" + self._reader_headers(number)
        payload = {"article": head + b"\r\n\r\n" + body, "head": head + b"\r\n", "body": body,
                   "stat": None}[part]
        self.send(f"{code} {number} {msgid}")
        if payload is not None:
            self.writer.write(dot_stuff(payload))

    async def cmd_article(self, args):
        await self._send_part(args, 220, "article")

    async def cmd_head(self, args):
        await self._send_part(args, 221, "head")

    async def cmd_body(self, args):
        await self._send_part(args, 222, "body")

    async def cmd_stat(self, args):
        await self._send_part(args, 223, "stat")

    async def cmd_newnews(self, args):
        if len(args) < 3:
            self.send("501 syntax: NEWNEWS wildmat yyyymmdd hhmmss [GMT]")
            return
        try:
            stamp = datetime.strptime(args[1] + args[2], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            self.send("501 bad date")
            return
        self.send("230 list of new articles follows")
        for msgid, gid in self.node.store.received_since(int(stamp.timestamp())):
            if wildmat(args[0], gid):
                self.send(msgid)
        self.send(".")

    # --- posting ---
    def _try_accept(self, raw: bytes, from_peer: bool = False) -> ArticleError | None:
        try:
            self.node.accept(raw, source=self.peer, from_peer=from_peer)
            return None
        except ArticleError as err:
            log.debug("rejected: %s", err)
            return err

    async def cmd_post(self, args):
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

    def _peer_allowed(self) -> bool:
        if self.node.config.require_peer_auth and not self.peer:
            self.send("480 peer authentication required")
            return False
        return True

    async def cmd_ihave(self, args):
        if not args or not self._peer_allowed():
            return
        if self.node.store.seen(args[0]):
            self.send("435 not wanted")
            return
        self.send("335 send it")
        await self.writer.drain()
        raw = await read_block(self.reader, self.node.config.max_size + 1024)
        self.send("235 transferred" if self._try_accept(raw, from_peer=True) is None else "437 rejected")

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
        self.send(f"{239 if self._try_accept(raw, from_peer=True) is None else 439} {args[0]}")
