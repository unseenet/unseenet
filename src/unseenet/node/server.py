"""ONNTP server and article acceptance (UN-RFC 0002 section 5, 0004, 0005)."""

from __future__ import annotations

import asyncio
import fnmatch
import hmac
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .. import __version__
from ..core.groups import canonical_json
from ..core import crypto
from ..core.article import MAX_SIZE, Article, ArticleError, parse_date, validate_structure
from ..core.groups import (INBOX_SCHEME, Manifest, check_permitted, parse_key_update,
                           split_group_id)
from ..core.store import Store
from ..nntp import MAX_LINE, dot_stuff, read_block
from .stats import Stats

log = logging.getLogger("unseenet.node")


@dataclass
class PeerConfig:
    name: str
    address: str                # "xyz.onion" or "host:port" (testing)
    groups: str = "*"           # RFC 3977 wildmat over Group IDs
    key: str | None = None      # the peer's node key, "ed25519:..." (UN-RFC 0016)
    pull: str = "*"             # wildmat of groups to catch up on from this peer (UN-RFC 0017)
    accept: str = "*"           # wildmat of groups to take from this peer, pushed or pulled
    password: str | None = None  # legacy shared secret for AUTHINFO

    def public_key(self) -> bytes | None:
        return crypto.key_from_text(self.key) if self.key else None


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
    excludes: str = ""                   # wildmat of groups not carried by choice (UN-RFC 0021)
    pull_interval: float = 3600.0        # seconds between catch-up pulls (UN-RFC 0017)
    honour_blocks: bool = False          # UN-RFC 0018 section 8.2: maintainers' blocks
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
    def __init__(self, store: Store, config: NodeConfig | None = None,
                 key: crypto.Identity | None = None):
        self.store = store
        self.config = config or NodeConfig()
        # The node key identifies this node to its peers (UN-RFC 0016). A real node
        # keeps it sealed in its data directory; without one (tests) it is temporary.
        self.key = key or crypto.Identity.generate()
        self._listeners: list[asyncio.Event] = []
        self._watchers: list[tuple[str, asyncio.Queue]] = []   # UN-RFC 0008 section 2
        self.stats = Stats()                  # for the operator's monitor (node/stats.py)
        self._blocks: dict[str, tuple[float, dict]] = {}   # group name -> (time, blocks)

    def watch(self, pattern: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._watchers.append((pattern, queue))
        return queue

    def unwatch(self, queue: asyncio.Queue) -> None:
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
        for peer in self.config.peers:
            if peer.name == name:
                return peer
        return None

    def subscribe(self) -> asyncio.Event:
        """An event that is set whenever a new article is queued for peers."""
        event = asyncio.Event()
        self._listeners.append(event)
        return event

    # ------------------------------------------------------------------
    # Acceptance pipeline
    # ------------------------------------------------------------------
    def accept(self, raw: bytes, source: str | None = None,
               now: datetime | None = None, from_peer: bool = False,
               how: str | None = None) -> Article:
        """Validate and store an article. Raises ArticleError with an RFC 0005 reason.

        ``from_peer`` is true for articles pushed by another node (IHAVE/TAKETHIS),
        authenticated or not; ``source`` names the peer when it authenticated.
        ``how`` is only for the counters: "client", "peer" or "pull".
        """
        try:
            art = self._accept(raw, source, now, from_peer)
        except ArticleError as err:
            self.stats.rejected_one(err.reason)
            raise
        self.stats.accepted_one(how or ("peer" if from_peer else "client"))
        return art

    def _accept(self, raw: bytes, source: str | None, now: datetime | None,
                from_peer: bool) -> Article:
        art = Article.from_bytes(raw)
        validate_structure(art, raw_size=len(raw), max_size=self.config.max_size, now=now)
        if self.store.seen(art.message_id):
            raise ArticleError("duplicate")
        if from_peer and source is not None:
            peer = self.peer_config(source)
            if peer is not None and not wildmat(peer.accept, art.group):
                raise ArticleError("group", f"not accepted from peer {source}")
        now = now or datetime.now(timezone.utc)
        ctl = art.control
        is_manifest = ctl == ["manifest"]
        if self.config.excludes and wildmat(self.config.excludes, art.group):
            raise ArticleError("group", "excluded by this node")
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
            self._check_blocked(art)
            self.store.add(art, raw)
        self._enqueue(art, source)
        self._notify_watchers(art)
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
                self.store.set_epoch(art.group, epoch, member_key, art.message_id)
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
                stored = self.store.get(target)
                if stored is not None and Article.from_bytes(stored).control:
                    # manifests, key updates, cancels: never cancelled (UN-RFC 0004, 7.1)
                    raise ArticleError("permission", "control articles cannot be cancelled")
                self.store.delete(target)
            else:
                self.store.add_cancel(target, art["Author-Key"], art.group)
            self.store.add(art, raw)
        else:
            raise ArticleError("syntax", f"unknown control {ctl[0]!r}")

    # --- maintainers' blocks (UN-RFC 0018 sections 5.4 and 8.2) ---
    BLOCKS_TTL = 300.0

    def _check_blocked(self, art: Article) -> None:
        if not self.config.honour_blocks or art.group.startswith("inbox@"):
            return
        blocked = self.blocks_for(art.group)
        hit = blocked.get(art["Author-Key"])
        if hit:
            raise ArticleError("permission", f"blocked in {hit[0]}.* by its maintainer: {hit[1]}")

    def blocks_for(self, group_id: str) -> dict[str, tuple[str, str]]:
        """{key: (hierarchy, reason)} blocked for a group, from the lists this node
        carries (the project's root list and the maintainers' lists)."""
        from .. import hierarchies as hz
        name = group_id.rpartition("@")[0] or group_id
        cached = self._blocks.get(name)
        if cached and time.monotonic() - cached[0] < self.BLOCKS_TTL:
            return cached[1]
        from ..known_nodes import PROJECT_KEY
        root = self._newest_list(hz.HIERARCHIES_GROUP, PROJECT_KEY,
                                 lambda body: hz.parse_root_list(body)[1])
        if root is None:
            root = hz.builtin_root_list()[1]
        lists: dict = {"unseenet": hz.builtin_checkgroups()}
        h = hz.policy_of(name.split(".")[0], root)
        for _ in range(hz.MAX_DEPTH + 1):
            if h.policy != "governed":
                break
            lst = self._newest_list(h.list, h.maintainer,
                                    lambda body, n=h.name: hz.parse_hierarchy_list(body, n))
            if lst is None:
                lst = lists.get(h.name)
            if lst is None:
                break
            lists[h.name] = lst
            deeper = [x for x in lst.sub.values() if hz._within(name, x.name)]
            if not deeper:
                break
            h = max(deeper, key=lambda x: len(x.name))
        result = hz.blocks_for(name, root, lists)
        self._blocks[name] = (time.monotonic(), result)
        return result

    def _newest_list(self, group_id: str | None, owner: str | None, parse):
        """The newest valid list posted in a channel group by its owner or posters."""
        if not group_id or not owner:
            return None
        manifest = self.store.manifest(group_id)
        if manifest is None or crypto.key_to_text(manifest.owner) != owner:
            return None
        allowed = {manifest.owner, *manifest.posters}
        best = None
        for n in self.store.numbers(group_id):
            found = self.store.by_number(group_id, n)
            if not found:
                continue
            try:
                art = Article.from_bytes(found[1])
                if art.control or art.author_key not in allowed:
                    continue
                value = parse(art.body)
                date = parse_date(art["Date"])
            except (ArticleError, ValueError, KeyError, TypeError, crypto.CryptoError):
                continue
            if best is None or date > best[0]:
                best = (date, value)
        return best[1] if best else None

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
        if manifest is not None and manifest.low_latency:
            lo = hi = 0.0                # chat groups: no random delay (UN-RFC 0008, 3.2)
        for peer in self.config.peers:
            if peer.name != source and wildmat(peer.groups, art.group):
                self.store.enqueue(peer.name, art.message_id, time.time() + random.uniform(lo, hi))
        for event in self._listeners:
            event.set()

    def excludes(self) -> str:
        """UN-RFC 0021 section 3: `excludes` from node.toml, plus every dropped group."""
        parts = [p for p in self.config.excludes.split(",") if p]
        parts += [g for g in self.store.dropped_groups() if g not in parts]
        return ",".join(parts)

    def node_info(self) -> dict:
        cfg = self.config
        op = cfg.operator or {}
        info = {"v": 1, "name": cfg.name, "software": f"unseenet {__version__}",
                "node_key": self.key.key_text,
                "policy": {"new_groups": cfg.new_groups, "min_pow": cfg.min_pow,
                           "retention_days": cfg.retention_days, "max_size": cfg.max_size,
                           "archive": False, "honours_blocks": cfg.honour_blocks,
                           "logging": op.get("logging", "accepted articles only, no reading activity")}}
        excludes = self.excludes()
        if excludes:
            info["policy"]["excludes"] = excludes
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
        self.stats.session_opened()
        try:
            await session.run()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.stats.session_closed(was_peer=session.peer is not None)
            writer.close()


class Session:
    def __init__(self, node: Node, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.node, self.reader, self.writer = node, reader, writer
        self.group: str | None = None
        self.current: int | None = None
        self.peer: str | None = None
        self._user: str | None = None
        self._challenge: tuple[bytes, bytes] | None = None   # (claimed key, nonce)
        self._auth_failures = 0

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
            handler = getattr(self, "cmd_" + cmd.lower().replace(".", "_").replace("-", "_"), None)
            if handler is None:
                self.send("500 unknown command")
                continue
            await handler(args)

    # --- capabilities & misc ---
    async def cmd_capabilities(self, args):
        cfg = self.node.config
        self.send("101 capability list follows")
        for cap in ("VERSION 2", "READER", "POST", "IHAVE", "STREAMING", "AUTHINFO USER",
                    "LIST ACTIVE NEWSGROUPS OVERVIEW.FMT HEADERS", "NEWNEWS", "OVER MSGID", "HDR",
                    "UNSEENET 1",
                    f"UNSEENET-MAXSIZE {cfg.max_size}", f"UNSEENET-MINPOW {cfg.min_pow}",
                    "UNSEENET-NODEINFO", "UNSEENET-WATCH", "UNSEENET-PEERKEY"):
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
                if (peer.name == self._user and peer.password
                        and hmac.compare_digest(peer.password.encode(), args[1].encode())):
                    self.peer = peer.name
                    self.node.stats.peer_authenticated()
                    self.send("281 authentication accepted")
                    return
            await self._auth_failed()
        else:
            self.send("482 authentication commands issued out of sequence")

    # --- peer authentication with node keys (UN-RFC 0016) ---
    async def cmd_xun_peer(self, args):
        """XUN-PEER <key>: a node claims a key; we answer with ours and a challenge."""
        if len(args) != 1:
            self.send("501 syntax: XUN-PEER <node key>")
            return
        try:
            claimed = crypto.key_from_text(args[0])
        except crypto.CryptoError:
            self.send("501 malformed key")
            return
        nonce = os.urandom(32)
        self._challenge = (claimed, nonce)
        # The same answer whether or not the key is a configured peer: no probing.
        self.send(f"383 {self.node.key.key_text} {crypto.b64(nonce)}")

    async def cmd_xun_peer_proof(self, args):
        """XUN-PEER-PROOF <signature> over nonce || our key || its key."""
        if self._challenge is None:
            self.send("482 XUN-PEER first")
            return
        claimed, nonce = self._challenge
        self._challenge = None                      # one attempt per challenge
        if len(args) != 1:
            self.send("501 syntax: XUN-PEER-PROOF <signature>")
            return
        peer = next((p for p in self.node.config.peers
                     if p.key and p.public_key() == claimed), None)
        try:
            sig = crypto.sig_from_text(args[0])
        except crypto.CryptoError:
            sig = b""
        message = nonce + self.node.key.public_key + claimed
        if peer is not None and sig and crypto.verify(claimed, crypto.PURPOSE_PEER_AUTH,
                                                       message, sig):
            self.peer = peer.name
            self.node.stats.peer_authenticated()
            self.send("281 peer authenticated")
            log.info("peer %s authenticated by key", peer.name)
            return
        await self._auth_failed()

    async def _auth_failed(self) -> None:
        self._auth_failures += 1
        await asyncio.sleep(min(self._auth_failures, 5))     # slow down guessing
        self.send("481 authentication failed")
        if self._auth_failures >= 3:
            await self.writer.drain()
            raise ConnectionError("too many failed authentications")

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
        if part in ("article", "body") and not self.peer:
            self.node.stats.served_one()          # how many, never which (UN-RFC 0011)

    async def cmd_article(self, args):
        await self._send_part(args, 220, "article")

    async def cmd_head(self, args):
        await self._send_part(args, 221, "head")

    async def cmd_body(self, args):
        await self._send_part(args, 222, "body")

    async def cmd_stat(self, args):
        await self._send_part(args, 223, "stat")

    # --- overview (RFC 3977 sections 8.3-8.5; UN-RFC 0005 section 2.4) ---
    OVERVIEW_FMT = ("Subject:", "From:", "Date:", "Message-ID:", "References:",
                    ":bytes", ":lines", "Xref:full")

    def _range(self, args) -> list[tuple[int, str, bytes]] | None:
        """Articles named by a message-id, a number, n-, n-m or (none) the current one."""
        store = self.node.store
        if args and args[0].startswith("<"):
            raw = store.get(args[0])
            if raw is None:
                self.send("430 no such article")
                return None
            return [(0, args[0], raw)]
        if not self.group:
            self.send("412 no group selected")
            return None
        nums = store.numbers(self.group)
        if not args:
            if self.current is None:
                self.send("420 no current article")
                return None
            lo = hi = self.current
        else:
            first, dash, last = args[0].partition("-")
            try:
                lo = int(first)
                hi = (int(last) if last else (nums[-1] if nums else lo)) if dash else lo
            except ValueError:
                self.send("501 syntax: range n, n- or n-m")
                return None
        out = []
        for n in nums:
            if lo <= n <= hi:
                found = store.by_number(self.group, n)
                if found:
                    out.append((n, found[0], found[1]))
        if not out:
            self.send("423 no articles in that range")
            return None
        return out

    @staticmethod
    def _clean(value: str) -> str:
        return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")

    def _overview_fields(self, number: int, raw: bytes) -> dict[str, str]:
        """The overview of one article. Articles a newsreader cannot show get a
        fixed subject, so readers do not show empty lines (#21)."""
        try:
            art = Article.from_bytes(raw)
        except ArticleError:
            return {"Subject:": "(invalid article)"}
        ctl = art.control
        encrypted = art.get("Encrypted", "")
        if ctl and ctl[0] == "manifest":
            subject = "(group settings)"
        elif ctl:
            subject = f"(control: {ctl[0]})"
        elif encrypted.strip() == INBOX_SCHEME or art.group.startswith("inbox@"):
            subject = "(private message)"
        elif encrypted:
            subject = "(encrypted)"
        else:
            subject = art.get("Subject") or "(no subject)"
        head, _, body = raw.partition(b"\r\n\r\n")
        group = self.group or art.group
        return {
            "Subject:": subject, "From:": art.get("From") or "(unknown)",
            "Date:": art.get("Date", ""), "Message-ID:": art.message_id,
            "References:": art.get("References", ""), ":bytes": str(len(raw)),
            ":lines": str(body.count(b"\n") + (1 if body and not body.endswith(b"\n") else 0)),
            "Xref:full": f"Xref: unseenet {group}:{number}" if number else "",
        }

    async def cmd_over(self, args):
        found = self._range(args)
        if found is None:
            return
        self.send("224 overview information follows")
        for number, _, raw in found:
            f = self._overview_fields(number, raw)
            self.send("\t".join([str(number)] + [self._clean(f.get(k, "")) for k in self.OVERVIEW_FMT]))
        self.send(".")

    cmd_xover = cmd_over

    async def cmd_list_overview_fmt(self, args):
        self.send("215 order of fields in overview database")
        for field_ in self.OVERVIEW_FMT:
            self.send(field_)
        self.send(".")

    async def cmd_hdr(self, args, code: int = 225):
        if not args:
            self.send("501 syntax: HDR field [range|message-id]")
            return
        name = args[0]
        found = self._range(args[1:])
        if found is None:
            return
        key = name if name.startswith(":") else name.rstrip(":").lower()
        self.send(f"{code} headers follow")
        for number, _, raw in found:
            f = self._overview_fields(number, raw)
            if key.startswith(":"):
                value = f.get(key, "")
            else:
                over = {k.rstrip(":").lower(): v for k, v in f.items() if not k.startswith(":")}
                if key in over and key != "xref:full":
                    value = over[key]
                else:
                    try:
                        value = Article.from_bytes(raw).get(name.rstrip(":"), "") or ""
                    except ArticleError:
                        value = ""
            self.send(f"{number} {self._clean(value)}")
        self.send(".")

    async def cmd_xhdr(self, args):
        await self.cmd_hdr(args, code=221)

    async def cmd_list_headers(self, args):
        self.send("215 headers and metadata items supported")
        self.send(":")
        self.send(".")

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
        for gid, *_ in store.groups():
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
