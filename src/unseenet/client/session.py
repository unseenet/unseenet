"""Client session: vault, node connection, reading and posting.

Shared by the command line and the TUI. Everything persistent lives in the
encrypted vault (UN-RFC 0007); articles are cached in memory only.
"""

from __future__ import annotations

import asyncio
import random
import re
import base64
import json
from dataclasses import dataclass, field
from typing import NamedTuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..core import crypto
from ..core.article import Article, ArticleError, new_article, parse_date, validate_structure
from ..core.groups import (INBOX_SCHEME, KIND_CHAT, KIND_POST, MAX_RULES, VIEWS, decrypt_article,
                           encrypted_article, encryption_epoch, inbox_article, make_key_update,
                           make_manifest, manifest_article, message_kind, open_envelope,
                           open_inbox_article, personal_inbox_id, short_group_id, split_group_id)
from ..core.groups import _comments  # UN-RFC 0030 field check
from ..core.groups import RENEW_WHEN_LEFT, RENEW_WINDOW, is_key_bound, stored_expires
from ..core.tor import BRIDGE_MODES, TorError, TorProcess, bridges_for
from ..core.vault import Vault
from ..nntp import Client, NNTPError
from .. import names
from . import naming

DEFAULT_POW = 20
MAX_READ_MARKS = 5000
MAX_CACHED_PER_GROUP = 2000
SIG_SEPARATOR = "-- \n"         # the Usenet signature delimiter (RFC 3676, 4.3): dash dash space
MAX_SIG_LINES = 4               # the old netiquette limit
DEFAULT_SIGNATURE = "{name}  ·  {key}"   # until you set your own; empty means none
CACHE_SIDECAR = "cache"
SENT_SIDECAR = "sent"           # copies of private messages you sent (they are sealed to others)


class ForYouCount(NamedTuple):
    """Unread posts for you: replies to your posts and posts naming you (#109, #170)."""
    replies: int = 0
    mentions: int = 0

    @property
    def total(self) -> int:
        return self.replies + self.mentions


class SessionError(RuntimeError):
    pass


@dataclass
class Message:
    number: int
    message_id: str
    group: str
    subject: str = ""
    from_name: str = ""
    author_key: str = ""
    date: datetime | None = None
    body: str = ""
    references: list[str] = field(default_factory=list)
    encrypted: bool = False
    readable: bool = True
    error: str | None = None
    raw: bytes = field(default=b"", repr=False)
    private: bool = False                 # an inbox message (UN-RFC 0009)
    sender_key: str | None = None         # verified sender of a private message
    reply_inbox: str | None = None
    to_key: str | None = None             # a private message you sent: its recipient
    content_type: str = ""                # private messages: the inner Content-Type
    kind: str = KIND_POST               # private messages: a chat or a post (UN-RFC 0028)

    @property
    def author_fp(self) -> str:
        try:
            return crypto.fingerprint(crypto.key_from_text(self.author_key))[:4]
        except crypto.CryptoError:
            return "????"

    @property
    def thread_root(self) -> str:
        return self.references[0] if self.references else self.message_id


@dataclass
class GroupInfo:
    group_id: str
    description: str = ""
    type: str | None = None
    owner_key: str | None = None
    subscribed: bool = False
    nodes: list[str] = field(default_factory=list)   # the nodes that carry it, yours first

    @property
    def short(self) -> str:
        return short_group_id(self.group_id)


def art_body_text(body: str) -> str:
    """A body as it will appear in an article (LF endings, one final newline)."""
    body = body.replace("\r\n", "\n")
    return body if body.endswith("\n") else body + "\n"


def split_signature(body: str) -> tuple[str, str | None]:
    """Split a body into (text, signature). The signature follows the last '-- ' line."""
    if body.startswith(SIG_SEPARATOR):
        return "", body[len(SIG_SEPARATOR):]
    idx = body.rfind("\n" + SIG_SEPARATOR)
    if idx < 0:
        return body, None
    return body[:idx + 1], body[idx + 1 + len(SIG_SEPARATOR):]


def strip_reader_headers(raw: bytes) -> bytes:
    """Remove Path/Xref synthesized by the node for newsreaders (UN-RFC 0005, 3)."""
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = [ln for ln in head.split(b"\r\n") if not ln.lower().startswith((b"path:", b"xref:"))]
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


class Session:
    def __init__(self, vault: Vault, status=print):
        self.vault = vault
        self.status = status            # callback for progress messages
        self.tor: TorProcess | None = None
        self._tor_lock = asyncio.Lock()   # one Tor per session, however many connect at once
        self._clients: dict[str, Client] = {}          # one connection per node
        self._locks: dict[str, asyncio.Lock] = {}
        self.unreachable: list[str] = []               # nodes that did not answer last time
        self.cache: dict[str, dict[int, Message]] = {}
        self._raw: dict[str, dict[int, bytes]] = {}   # what the offline cache stores
        self._high: dict[str, int] = {}               # highest article number fetched
        d = self.vault.data
        d.setdefault("identities", {})
        d.setdefault("groups", {})
        d.setdefault("nodes", [])
        d.setdefault("subscribed", [])
        d.setdefault("read", {})
        d.setdefault("contacts", {})
        d.setdefault("ignored", {})                    # keys you do not want to see (#72)
        if d["nodes"]:          # groups from before several nodes: they live on the first
            for entry in d["groups"].values():
                entry.setdefault("node", d["nodes"][0])
        self.sent: list[dict] = self._load_sent()

    # ------------------------------------------------------------------
    # identities & settings
    # ------------------------------------------------------------------
    @property
    def data(self) -> dict:
        return self.vault.data

    def save(self) -> None:
        self.vault.save()

    def has_identity(self) -> bool:
        return bool(self.data["identities"])

    def default_identity_name(self) -> str:
        ids = self.data["identities"]
        if not ids:
            raise SessionError("no identity yet")
        name = self.data.get("default_identity")
        return name if name in ids else next(iter(ids))

    def identity(self, name: str | None = None) -> crypto.Identity:
        entry = self.data["identities"][name or self.default_identity_name()]
        return crypto.Identity.from_seed(bytes.fromhex(entry["seed"]))

    def display_name(self, name: str | None = None) -> str:
        return self.data["identities"][name or self.default_identity_name()]["display"]

    def signature_template(self, name: str | None = None) -> str:
        # no "signature" yet: the default; one set to "" by the user: none
        return self.data["identities"][name or self.default_identity_name()].get(
            "signature", DEFAULT_SIGNATURE)

    def set_signature(self, template: str, name: str | None = None) -> None:
        lines = template.strip("\n").split("\n") if template.strip() else []
        if len(lines) > MAX_SIG_LINES:
            raise SessionError(f"a signature has at most {MAX_SIG_LINES} lines")
        self.data["identities"][name or self.default_identity_name()]["signature"] = "\n".join(lines)
        self.save()

    def signature(self, name: str | None = None) -> str:
        """The signature with {name}, {key} and {fp} filled in ('' if none)."""
        template = self.signature_template(name)
        if not template:
            return ""
        ident = self.identity(name)
        for placeholder, value in (("{name}", self.display_name(name)), ("{key}", ident.key_text),
                                   ("{fp}", ident.fingerprint[:4])):
            template = template.replace(placeholder, value)
        return template

    def new_identity(self, name: str, display: str | None = None) -> crypto.Identity:
        ident = crypto.Identity.generate()
        self.data["identities"][name] = {"seed": ident.seed.hex(), "display": display or name,
                                         "signature": DEFAULT_SIGNATURE}
        self.data.setdefault("default_identity", name)
        self.save()
        return ident

    # ------------------------------------------------------------------
    # nodes: your identity is in the vault, so it is the same on every node.
    # Each group is read from one node (article numbers are per node); new
    # groups and your inbox go to the default node, the first in the list.
    # ------------------------------------------------------------------
    def add_node(self, address: str, default: bool = False) -> None:
        address = address.strip()
        if not address:
            raise SessionError("no address given")
        nodes = self.data["nodes"]
        if address in nodes:
            if not default:
                return
            nodes.remove(address)
        if default or not nodes:
            nodes.insert(0, address)
        else:
            nodes.append(address)
        self.save()

    def remove_node(self, address: str) -> list[str]:
        """Stop using a node. Its groups move to the default node; returns them."""
        nodes = self.data["nodes"]
        if address not in nodes:
            return []
        if len(nodes) == 1:
            raise SessionError("you need at least one node")
        nodes.remove(address)
        moved = [gid for gid, e in self.data["groups"].items() if e.get("node") == address]
        for gid in moved:
            self.data["groups"][gid]["node"] = nodes[0]
            self._forget_numbers(gid)
        client = self._clients.pop(address, None)
        if client is not None:
            client.writer.close()
        self.save()
        self.save_offline()
        return [g for g in moved if g in self.data["subscribed"]]

    @property
    def nodes(self) -> list[str]:
        return list(self.data["nodes"])

    @property
    def node(self) -> str | None:
        """The default node: new groups and your inbox live here."""
        return self.data["nodes"][0] if self.data["nodes"] else None

    def node_for(self, group_id: str | None) -> str | None:
        """The node a group is read from and posted to."""
        if group_id:
            address = self.data["groups"].get(group_id, {}).get("node")
            if address in self.data["nodes"]:
                return address
        return self.node

    def pin_group(self, group_id: str, address: str) -> None:
        """Read a group from ``address`` from now on."""
        if address not in self.data["nodes"]:
            raise SessionError(f"{address} is not one of your nodes")
        entry = self.group_entry(group_id)
        if entry.get("node") != address:
            if entry.get("node") is not None:
                self._forget_numbers(group_id)
            entry["node"] = address
            self.save()

    # --- the known nodes (UN-RFC 0010) ---
    def known_nodes(self) -> list:
        """The newest node list this client has: read from the network, else built in."""
        from ..known_nodes import KNOWN_NODES, KnownNode
        cached = self.data.get("known_nodes")
        if cached and cached.get("nodes"):
            return [KnownNode(**n) for n in cached["nodes"]]
        return list(KNOWN_NODES)

    async def refresh_known_nodes(self) -> bool:
        """Read the newest signed node list from the project's channel. True if it changed.

        The group ID carries the project key's fingerprint, its manifest is
        signed by that key, and only the owner and the manifest's posters may
        post: the node enforces that, and we check it again here.
        """
        from dataclasses import asdict
        from ..known_nodes import NODES_GROUP, PROJECT_KEY, parse_node_list
        subscribed = NODES_GROUP in self.data["subscribed"]
        try:
            messages = await self.fetch_group(NODES_GROUP)
        finally:
            if not subscribed:          # read it, but do not keep it around
                self.cache.pop(NODES_GROUP, None)
                self._raw.pop(NODES_GROUP, None)
                self._high.pop(NODES_GROUP, None)
        manifest = self.manifest_data(NODES_GROUP)
        if manifest.get("owner") != PROJECT_KEY:
            return False
        allowed = {PROJECT_KEY, *manifest.get("posters", [])}
        best = None
        for m in messages:
            if not m.readable or m.author_key not in allowed:
                continue
            try:
                updated, nodes = parse_node_list(m.body)
            except ValueError:
                continue
            if best is None or (m.date and (best[0] is None or m.date > best[0])):
                best = (m.date, updated, nodes)
        if best is None:
            return False
        new = {"updated": best[1], "nodes": [asdict(n) for n in best[2]]}
        if self.data.get("known_nodes") == new:
            return False
        self.data["known_nodes"] = new
        self.save()
        return True

    async def refresh_naming(self) -> bool:
        """Read the root list, hierarchy lists and names (UN-RFC 0018, 0019). True if changed."""
        return await naming.refresh(self)

    def group_label(self, group_id: str, also_known: set[str] = frozenset()) -> str:
        """The name to show for a group: without the fingerprint where UN-RFC 0018 allows."""
        return naming.group_label(self, group_id, also_known)

    def identity_label(self, key_text: str, from_name: str = "") -> str:
        """Petname, else @domain, else @name, else Name~abcd (UN-RFC 0019 section 8)."""
        return naming.identity_label(self, key_text, from_name)

    def _forget_numbers(self, group_id: str) -> None:
        """Article numbers belong to one node: drop them when a group moves."""
        for store in (self.cache, self._raw, self._high):
            store.pop(group_id, None)
        self.data["groups"].get(group_id, {}).pop("closed", None)   # numbers of the old node

    # ------------------------------------------------------------------
    # connection (one persistent connection; Tor circuits are slow to build)
    # ------------------------------------------------------------------
    async def _connect(self, address: str | None = None, quiet: bool = False) -> Client:
        address = address or self.node
        if not address:
            raise SessionError("no node configured")
        status = (lambda *_: None) if quiet else self.status
        socks = None
        if address.split(":")[0].endswith(".onion"):
            socks = await self._ensure_tor(status)
        status(f"Connecting to {address} ...")
        client = await Client.connect(address, socks)
        await client.fetch_capabilities()
        status(f"Connected to {address}")
        return client

    async def _ensure_tor(self, status) -> int:
        """Our Tor's SOCKS port, starting Tor first if it is not running.

        Several connections (each node, the watch connections) start at once. Without
        the lock each started its own Tor on the same data directory: the extra ones
        died ("another Tor process is running"), but first overwrote the control-port
        file, so a client could end up talking to a Tor that was gone.
        """
        async with self._tor_lock:
            if self.tor is not None and not self.tor.alive():
                await self.tor.stop()
                self.tor = None
            if self.tor is None:
                tor_dir = self.vault.path.resolve().parent / "unseenet-tor"
                try:
                    binary = TorProcess.find_binary()
                except TorError as exc:
                    raise SessionError(str(exc)) from exc
                try:
                    bridges = bridges_for(self.data.get("tor"), binary)
                except TorError as exc:
                    raise SessionError(f"Tor bridges: {exc}") from exc
                tor = TorProcess(tor_dir, binary, bridges=bridges)
                status("Starting Tor" + (" with bridges" if bridges else "") + " ...")
                try:
                    await tor.start()
                except TorError as exc:
                    await tor.stop()
                    hint = ("" if bridges else
                            " If this network blocks Tor, try bridges (Ctrl+P: Tor bridges).")
                    raise SessionError(f"{exc}.{hint}") from exc
                self.tor = tor
            return self.tor.socks_port

    async def watch(self, on_new, pattern: str = "*", node: str | None = None) -> bool:
        """Listen for new articles (UN-RFC 0008) on a second connection.

        Calls ``on_new(group_id, message_id)`` for each one. Returns False at once if the
        node cannot push; otherwise runs until the connection fails (raises).
        Watching "*" tells the node nothing about which groups you follow.
        """
        client = await self._connect(node, quiet=True)
        try:
            if client.capability("UNSEENET-WATCH") is None:
                return False
            await client.command(f"XUN-WATCH {pattern}", (290,))
            while True:
                line = await client.reader.readline()
                if not line:
                    raise ConnectionError("node closed the watch connection")
                parts = line.decode("utf-8", "replace").split()
                if parts and parts[0] == "291" and len(parts) >= 4:
                    await on_new(parts[1], parts[3])
        finally:
            client.writer.close()

    async def _call(self, fn, node: str | None = None):
        """Run ``fn(client)`` on a node (default: the default node), with one
        reconnect attempt on a broken connection."""
        address = node or self.node
        if not address:
            raise SessionError("no node configured")
        async with self._locks.setdefault(address, asyncio.Lock()):
            for attempt in (1, 2):
                if address not in self._clients:
                    self._clients[address] = await self._connect(address)
                client = self._clients[address]
                try:
                    return await fn(client)
                except (ConnectionError, OSError, asyncio.IncompleteReadError):
                    self._drop(address, client)
                    if attempt == 2:
                        raise
                except (NNTPError, SessionError):
                    raise                   # a complete answer: the connection is fine
                except BaseException:
                    # Interrupted half-way (cancelled, timed out, a bug): the rest of
                    # an answer may still be on its way, and the next command would
                    # read it as its own. Never reuse such a connection.
                    self._drop(address, client)
                    raise

    def _drop(self, address: str, client: Client) -> None:
        if self._clients.get(address) is client:
            del self._clients[address]
        try:
            client.writer.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Tor bridges, for networks that block Tor
    # ------------------------------------------------------------------
    def bridge_setting(self) -> dict:
        return dict(self.data.get("tor") or {"mode": "off"})

    async def set_bridges(self, mode: str, custom: list[str] | None = None) -> None:
        """Change how Tor connects; Tor is restarted at the next connection."""
        if mode not in BRIDGE_MODES:
            raise SessionError(f"unknown bridge mode {mode!r}")
        lines = [ln.strip() for ln in (custom or []) if ln.strip()]
        if mode == "custom" and not lines:
            raise SessionError("paste at least one bridge line")
        self.data["tor"] = {"mode": mode, "custom": lines}
        self.save()
        await self.close()

    async def close(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.quit()
            except Exception:  # noqa: BLE001
                pass
        self._clients.clear()
        async with self._tor_lock:
            if self.tor:
                await self.tor.stop()
                self.tor = None

    # ------------------------------------------------------------------
    # groups
    # ------------------------------------------------------------------
    def group_entry(self, group_id: str) -> dict:
        return self.data["groups"].setdefault(group_id, {"type": None, "owner": False, "keys": {}})

    async def list_groups(self, pattern: str = "*", node: str | None = None) -> list[GroupInfo]:
        """Groups on one node, or on all your nodes (merged; unreachable ones skipped)."""
        targets = [node] if node else self.nodes
        results = await asyncio.gather(
            *(self._call(lambda c: c.multiline(f"LIST NEWSGROUPS {pattern}", 215), n)
              for n in targets), return_exceptions=True)
        failed = [r for r in results if isinstance(r, BaseException)]
        for r in failed:
            if not isinstance(r, (OSError, ConnectionError, SessionError, NNTPError,
                                  asyncio.IncompleteReadError)):
                raise r
        if failed and len(failed) == len(results):
            raise failed[0]
        self.unreachable = [n for n, r in zip(targets, results) if isinstance(r, BaseException)]
        out: dict[str, GroupInfo] = {}
        subscribed = set(self.data["subscribed"])
        for address, lines in zip(targets, results):
            if isinstance(lines, BaseException):
                continue
            for line in lines:
                gid, _, desc = line.partition("\t")
                try:
                    split_group_id(gid)
                except ValueError:
                    continue
                if gid in out:
                    out[gid].nodes.append(address)
                    continue
                entry = self.data["groups"].get(gid, {})
                if gid in subscribed and desc and entry.get("title") != desc:
                    self.group_entry(gid)["title"] = desc       # remembered for offline use
                out[gid] = GroupInfo(gid, desc, entry.get("type"), subscribed=gid in subscribed,
                                     nodes=[address])
        for g in out.values():           # the node it is read from first
            home = self.node_for(g.group_id)
            if home in g.nodes:
                g.nodes.remove(home)
                g.nodes.insert(0, home)
        return list(out.values())

    def subscribe(self, group_id: str, on: bool = True, node: str | None = None) -> None:
        split_group_id(group_id)
        subs = self.data["subscribed"]
        if on and node:
            self.pin_group(group_id, node)
        elif on and self.node:
            self.group_entry(group_id).setdefault("node", self.node)
        if on and group_id not in subs:
            subs.append(group_id)
        elif not on and group_id in subs:
            subs.remove(group_id)
        self.save()

    async def peek_group(self, group_id: str, node: str | None = None,
                         max_heads: int = 300) -> tuple[dict, int]:
        """(manifest, number of posts) of a group you may not follow, for browsing.

        Reads only headers, and the manifest articles themselves; the manifest must be
        signed by the owner named in the group ID. Nothing is cached or subscribed.
        """
        from ..core.groups import Manifest

        async def run(c: Client) -> tuple[dict, int]:
            count, low, high = await c.group(group_id)
            best: dict = {}
            for n in range(low, min(high, low + max_heads - 1) + 1):
                try:
                    head = await c.multiline(f"HEAD {n}", 221)
                except NNTPError:
                    continue
                if not any(h.lower().replace(" ", "") == "control:manifest" for h in head):
                    continue
                raw = await c.article(str(n))
                try:
                    m = Manifest.from_article(Article.from_bytes(raw))
                except (ArticleError, ValueError, TypeError):
                    continue
                if m.group_id == group_id and m.serial >= int(best.get("serial", 0)):
                    best = dict(m.raw)
            return best, count

        cached = self.manifest_data(group_id)
        data, count = await self._call(run, node or self.node_for(group_id))
        return (cached if int(cached.get("serial", 0)) > int(data.get("serial", 0)) else data), count

    def subscribe_starter_groups(self) -> bool:
        """Subscribe to the project's groups once per vault (a new client has
        something to read). Groups unsubscribed later are not added again."""
        if self.data.get("starter_groups") or not self.node:
            return False
        from ..known_nodes import STARTER_GROUPS
        for gid in STARTER_GROUPS:
            if gid not in self.data["subscribed"]:
                self.data["subscribed"].append(gid)
                self.group_entry(gid).setdefault("node", self.node)
        self.data["starter_groups"] = True
        self.save()
        return True

    async def create_group(self, name: str, gtype: str, title: str = "", description: str = "",
                           min_pow: int = DEFAULT_POW, local: bool = False,
                           retention_days: int | None = None, rules: str = "",
                           view: str | None = None, low_latency: bool = False,
                           kinds: list[str] | None = None, node: str | None = None,
                           comments: str | None = None, comment_days: int | None = None) -> str:
        owner = self.identity()
        node = node or self.node
        if retention_days is None:
            retention_days = 30 if gtype == "inbox" else 90
        art = make_manifest(owner, name, gtype, title=title, description=description,
                            min_pow=min_pow, local=local, retention_days=retention_days,
                            rules=rules, view=view, low_latency=low_latency, kinds=kinds,
                            comments=comments if gtype == "channel" else None,
                            comment_days=comment_days if gtype == "channel" else None,
                            pow_bits=await self.required_pow(None, node=node))
        await self._post_article(art, node)
        entry = {"type": gtype, "owner": True, "keys": {}, "manifest": json.loads(art.body),
                 "owner_key": owner.key_text, "node": node}
        if gtype == "closed":
            keys = crypto.GroupKeys.generate()
            await self._post_article(make_key_update(
                owner, art.group, 1, keys, [],
                pow_bits=await self.required_pow(art.group, min_pow, node=node)), node)
            entry["keys"]["1"] = keys.secret.hex()
        self.data["groups"][art.group] = entry
        self.subscribe(art.group)
        return art.group

    def may_post(self, group_id: str) -> bool:
        """Whether a new post of yours would be accepted here (UN-RFC 0004, 2).
        Unknown groups count as yes: the node has the last word."""
        if group_id == self.my_inbox:
            return False                     # nobody posts to their own inbox
        entry = self.data["groups"].get(group_id, {})
        data = entry.get("manifest") or {}
        gtype = data.get("type") or entry.get("type")
        if entry.get("owner") or not gtype:
            return True
        if gtype == "channel":
            return self.identity().key_text in data.get("posters", [])
        if gtype == "closed":
            return bool(entry.get("keys"))    # a member: you have the group's key
        return True                          # open, moderated (goes to approval), inbox

    def may_reply(self, group_id: str) -> bool:
        """Whether a reply of yours would be accepted: as :meth:`may_post`, and in a
        channel open for comments, a comment from anyone (UN-RFC 0030)."""
        if self.may_post(group_id):
            return True
        data = self.manifest_data(group_id)
        return data.get("type") == "channel" and data.get("comments") == "open"

    # --- moderation (UN-RFC 0004 section 5, UN-RFC 0009 section 3) ---
    def moderates(self, group_id: str) -> bool:
        me = self.identity().key_text
        data = self.manifest_data(group_id)
        return bool(self.data["groups"].get(group_id, {}).get("owner")) \
            or data.get("owner") == me or me in data.get("moderators", [])

    def submission_targets(self, group_id: str) -> list[tuple[str, bytes | None]]:
        """(inbox, owner key or None) to send a submission to (UN-RFC 0009, 3)."""
        data = self.manifest_data(group_id)
        if data.get("submissions"):
            return [(data["submissions"], None)]
        keys = [data["owner"]] if data.get("owner") else []
        keys += [k for k in data.get("moderators", []) if k not in keys]
        return [(personal_inbox_id(crypto.key_from_text(k)), crypto.key_from_text(k)) for k in keys]

    async def _submit(self, group_id: str, subject: str, build) -> str:
        bits = await self.required_pow(group_id)
        loop = asyncio.get_running_loop()
        art = await loop.run_in_executor(None, lambda: build(bits))
        raw = art.to_bytes().decode("utf-8")
        delivered, errors = 0, []
        for inbox, owner_key in self.submission_targets(group_id):
            try:
                await self.send_private(inbox, f"Submission to {short_group_id(group_id)}: {subject}",
                                        raw, owner_key=owner_key, content_type=SUBMISSION_TYPE,
                                        remember=False)
                delivered += 1
            except (SessionError, OSError, ConnectionError) as exc:
                errors.append(str(exc))
        if not delivered:
            raise SessionError("could not reach the moderators: " + "; ".join(errors or ["no inbox"]))
        entry = self.group_entry(group_id)
        entry.setdefault("submitted", []).append(art.message_id)
        del entry["submitted"][:-200]
        self.data["read"].setdefault(group_id, []).append(art.message_id)
        self.save()
        return art.message_id

    def was_submitted(self, group_id: str, message_id: str) -> bool:
        return message_id in self.group_entry(group_id).get("submitted", [])

    def submissions(self) -> list[tuple["Message", Article]]:
        """Submissions waiting in your inbox for groups you moderate, oldest first."""
        done = set(self.data.get("moderation_done", []))
        out = []
        for m in self.private_messages():
            if not m.content_type.startswith(SUBMISSION_TYPE) or m.message_id in done:
                continue
            try:
                raw = m.body.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
                art = Article.from_bytes(raw)
                validate_structure(art, raw_size=len(raw))
            except (ArticleError, ValueError, UnicodeError):
                continue
            gid = art.group
            data = self.manifest_data(gid)
            if data.get("type") != "moderated" or not self.moderates(gid) \
                    or self.is_banned(gid, art["Author-Key"]):
                continue
            if any(x.message_id == art.message_id for x in self.cache.get(gid, {}).values()):
                continue                    # another moderator approved it already
            out.append((m, art))
        return out

    def _moderation_done(self, msg: "Message") -> None:
        done = self.data.setdefault("moderation_done", [])
        done.append(msg.message_id)
        del done[:-500]
        self.save()

    async def approve_submission(self, msg: "Message", art: Article) -> None:
        """Approve and post a submitted article; its Message-ID stays the same."""
        from ..core.groups import approve
        if not self.moderates(art.group):
            raise SessionError("you do not moderate this group")
        approve(art, self.identity())
        try:
            await self._post_article(art)
        except SessionError as exc:
            if "duplicate" not in str(exc).lower():
                raise                       # a duplicate: someone else approved it first
        self._moderation_done(msg)

    async def reject_submission(self, msg: "Message", reason: str = "") -> None:
        if reason.strip() and (msg.reply_inbox or msg.sender_key):
            target = self.reply_target(msg)
            if target:
                await self.send_private(target, "Not approved: " + msg.subject.split(": ", 1)[-1],
                                        reason.strip() + "\n", references=[msg.message_id])
        self._moderation_done(msg)

    def is_data_group(self, group_id: str) -> bool:
        """A group for programs, not people (UN-RFC 0008 section 3.1.1)."""
        from ..known_nodes import DATA_GROUPS
        return group_id in DATA_GROUPS or self.manifest_data(group_id).get("view") == "data"

    def manifest_data(self, group_id: str) -> dict:
        """The newest manifest seen for a group ({} if none yet)."""
        return dict(self.data["groups"].get(group_id, {}).get("manifest", {}))

    def text_type(self) -> str:
        """The Content-Type your posts get: Markdown, unless you turned it off (UN-RFC 0031)."""
        from ..core.markup import MARKDOWN_TYPE, PLAIN_TYPE
        return PLAIN_TYPE if self.data.get("plain_text") else MARKDOWN_TYPE

    def set_markdown(self, on: bool) -> None:
        self.data["plain_text"] = not on
        self.save()

    def group_kinds(self, group_id: str) -> tuple[str, ...]:
        """What a group takes: chat lines, posts with a subject, or both (UN-RFC 0028, 4.1)."""
        data = self.manifest_data(group_id)
        if data.get("type") == "inbox" or group_id == self.my_inbox:
            return (KIND_CHAT, KIND_POST)
        kinds = data.get("kinds")
        if isinstance(kinds, list) and kinds and all(k in (KIND_CHAT, KIND_POST) for k in kinds):
            return tuple(kinds)
        return (KIND_CHAT, KIND_POST)

    async def update_group(self, group_id: str, **changes) -> dict:
        """Publish a new manifest with a higher serial (owner only).

        Allowed changes: title, description, rules, view, kinds, low_latency, min_pow,
        retention_days. Type, owner and locality can never change (UN-RFC 0004, 4).
        """
        entry = self.data["groups"].get(group_id, {})
        if not entry.get("owner"):
            raise SessionError("only the owner can change a group")
        data = self.manifest_data(group_id)
        if not data:
            raise SessionError("the group's manifest has not been fetched yet")
        allowed = {"title", "description", "rules", "view", "low_latency", "min_pow",
                   "retention_days", "banned", "moderators", "posters", "kinds",
                   "comments", "comment_days"}
        if ("comments" in changes or "comment_days" in changes) and data.get("type") != "channel":
            raise SessionError("only channels take comments")
        if changes.get("comments") == "none":
            changes["comments"] = None            # the default is left out (UN-RFC 0030)
        if "kinds" in changes and changes["kinds"] is not None:
            kinds = list(dict.fromkeys(changes["kinds"]))
            if not kinds or any(k not in (KIND_CHAT, KIND_POST) for k in kinds):
                raise SessionError('kinds must be "chat", "post" or both')
            # both is the default and is left out of the manifest (UN-RFC 0028, 4.1)
            changes["kinds"] = None if set(kinds) == {KIND_CHAT, KIND_POST} else kinds
        for key, value in changes.items():
            if key not in allowed:
                raise SessionError(f"{key} cannot be changed")
            if value in (None, "", False, []) and key in ("title", "description", "rules",
                                                         "low_latency", "banned", "moderators",
                                                         "posters", "kinds", "comments",
                                                         "comment_days"):
                data.pop(key, None)
            else:
                data[key] = value
        if len(data.get("rules", "")) > MAX_RULES:
            raise SessionError(f"rules are limited to {MAX_RULES} characters")
        if data.get("view", "threads") not in VIEWS:
            raise SessionError("view must be threads or chat")
        try:
            _comments(data)
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        data["serial"] = int(data.get("serial", 1)) + 1
        art = manifest_article(self.identity(), group_id, data, await self.required_pow(None))
        await self._post_article(art)
        entry.update({"manifest": data, "title": data.get("title", "")})
        self.save()
        return data

    # --- bans (UN-RFC 0004, section 5.1) ---
    def banned(self, group_id: str) -> list[tuple[str, str]]:
        """(key, reason) of the keys the group's current manifest bans."""
        return [(b.get("key", ""), b.get("reason", ""))
                for b in self.manifest_data(group_id).get("banned", []) if isinstance(b, dict)]

    def is_banned(self, group_id: str, key_text: str | None) -> bool:
        return bool(key_text) and any(k == key_text for k, _ in self.banned(group_id))

    async def ban(self, group_id: str, key_text: str, reason: str = "") -> None:
        """Owner: ban a key from posting in the group (a new manifest)."""
        crypto.key_from_text(key_text)
        if key_text == self.identity().key_text:
            raise SessionError("you cannot ban yourself")
        if len(reason) > 200:
            raise SessionError("a reason is at most 200 characters")
        current = [b for b in self.manifest_data(group_id).get("banned", [])
                   if isinstance(b, dict) and b.get("key") != key_text]
        entry = {"key": key_text,
                 "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if reason.strip():
            entry["reason"] = reason.strip()
        await self.update_group(group_id, banned=current + [entry])

    async def unban(self, group_id: str, key_text: str) -> None:
        current = [b for b in self.manifest_data(group_id).get("banned", [])
                   if isinstance(b, dict) and b.get("key") != key_text]
        await self.update_group(group_id, banned=current)

    def rules_unseen(self, group_id: str) -> bool:
        """True if the group has rules the reader has not seen in this version."""
        data = self.manifest_data(group_id)
        if not data.get("rules"):
            return False
        return self.data.setdefault("rules_seen", {}).get(group_id, 0) < int(data.get("serial", 1))

    def mark_rules_seen(self, group_id: str) -> None:
        self.data.setdefault("rules_seen", {})[group_id] = int(self.manifest_data(group_id).get("serial", 1))
        self.save()

    async def required_pow(self, group_id: str | None, group_min: int | None = None,
                           node: str | None = None) -> int:
        """Postage to attach: max(node minimum, group minimum) - UN-RFC 0008 section 4."""
        async def node_min(c: Client) -> int:
            value = c.capability("UNSEENET-MINPOW")
            return int(value) if value and value.strip().isdigit() else DEFAULT_POW
        try:
            node_pow = await self._call(node_min, node or self.node_for(group_id))
        except (OSError, ConnectionError, SessionError):
            node_pow = DEFAULT_POW
        if group_min is None and group_id:
            manifest = self.manifest_data(group_id)
            # A group joined before manifests were kept has none cached yet; the
            # network default is the safe guess (the node will say if it wants more).
            group_min = int(manifest.get("min_pow", 0)) if manifest else DEFAULT_POW
        return max(node_pow, group_min or 0)

    async def _post_with_postage(self, group_id: str, build) -> Article:
        """Build with ``build(bits)`` and post; if the node asks for more postage
        ("need N bits"), rebuild once with N and post again. Returns the posted article."""
        bits = await self.required_pow(group_id)
        loop = asyncio.get_running_loop()
        art = await loop.run_in_executor(None, lambda: build(bits))
        try:
            await self._post_article(art)
            return art
        except SessionError as exc:
            m = re.search(r"need (\d+) bits", str(exc))
            if not m or int(m.group(1)) <= bits or int(m.group(1)) > 28:
                raise
            need = int(m.group(1))
        self.status(f"Node wants {need} bits of postage, computing again ...")
        art = await loop.run_in_executor(None, lambda: build(need))
        await self._post_article(art)
        entry = self.data["groups"].get(group_id)
        if entry is not None:                      # remember it for next time
            entry.setdefault("manifest", {})
            if int(entry["manifest"].get("min_pow", 0)) < need:
                entry["manifest"]["min_pow"] = need
        return art

    async def remove_group(self, group_id: str, reason: str = "") -> None:
        """UN-RFC 0013: remove a group you own from the whole network. Final."""
        entry = self.data["groups"].get(group_id, {})
        if not entry.get("owner"):
            raise SessionError("only the owner can remove a group")
        if group_id == self.my_inbox:
            raise SessionError("your personal inbox cannot be removed")
        art = new_article(group_id, None, reason or "Removed by its owner.\n",
                          extra=[("Control", "rmgroup")])
        bits = await self.required_pow(None)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: art.finalize(self.identity(), bits))
        await self._post_article(art)
        self.forget_group(group_id)

    def forget_group(self, group_id: str) -> None:
        """Unsubscribe and delete everything stored locally about a group."""
        if group_id in self.data["subscribed"]:
            self.data["subscribed"].remove(group_id)
        for store in (self.data["groups"], self.data["read"], self.cache, self._raw, self._high):
            store.pop(group_id, None)
        self.save()
        self.save_offline()

    async def invite(self, group_id: str, member_key: str) -> None:
        entry = self.data["groups"].get(group_id)
        if not entry or not entry.get("owner") or entry.get("type") != "closed":
            raise SessionError("you can only invite to closed groups you own")
        epoch = max(int(e) for e in entry["keys"])
        keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))
        art = make_key_update(self.identity(), group_id, epoch, keys,
                              [crypto.key_from_text(member_key)], grant_only=True,
                              pow_bits=await self.required_pow(group_id))
        await self._post_article(art)
        members = entry.setdefault("members", [])
        if member_key not in members:
            members.append(member_key)
        self.save()

    def members(self, group_id: str) -> list[str]:
        """Owner: the keys you invited to a closed group (envelopes do not say whom
        they are for, so this record is the list). Members invited from another
        device, or before this was recorded, are missing."""
        return list(self.data["groups"].get(group_id, {}).get("members", []))

    async def remove_member(self, group_id: str, member_key: str) -> int:
        """Owner: start a new epoch without the member (UN-RFC 0004, 6.1-6.2).
        The others get the new key; the removed member keeps what they read.
        Returns the new epoch."""
        entry = self.data["groups"].get(group_id)
        if not entry or not entry.get("owner") or entry.get("type") != "closed":
            raise SessionError("you can only remove members from closed groups you own")
        keep = [k for k in entry.get("members", []) if k != member_key]
        epoch = max(int(e) for e in entry["keys"]) + 1
        keys = crypto.GroupKeys.generate()
        art = make_key_update(self.identity(), group_id, epoch, keys,
                              [crypto.key_from_text(k) for k in keep], closes_previous=True,
                              pow_bits=await self.required_pow(group_id))
        await self._post_article(art)
        entry["keys"][str(epoch)] = keys.secret.hex()
        entry["members"] = keep
        self.save()
        return epoch

    async def set_role(self, group_id: str, role: str, key_text: str, on: bool = True) -> None:
        """Owner: add or remove a moderator or a poster (UN-RFC 0004, 3.1 and 5)."""
        if role not in ("moderators", "posters"):
            raise SessionError(f"unknown role {role}")
        crypto.key_from_text(key_text)
        if role == "posters" and self.group_entry(group_id).get("type") != "channel":
            raise SessionError("posters are for channels; other groups have moderators")
        current = [k for k in self.manifest_data(group_id).get(role, []) if k != key_text]
        if on:
            current.append(key_text)
        await self.update_group(group_id, **{role: current})

    # ------------------------------------------------------------------
    # inboxes and private messages (UN-RFC 0009)
    # ------------------------------------------------------------------
    @property
    def my_inbox(self) -> str:
        return personal_inbox_id(self.identity().public_key)

    async def ensure_inbox(self) -> str:
        """Make sure this identity's personal inbox exists on the node and is subscribed."""
        gid = self.my_inbox
        entry = self.group_entry(gid)
        entry.setdefault("node", self.node)
        if not entry.get("owner"):
            async def exists(c: Client) -> bool:
                try:
                    await c.group(gid)
                    return True
                except NNTPError:
                    return False
            if not await self._call(exists, self.node_for(gid)):
                # a serial above any we used before: the inbox may have expired (UN-RFC 0029, 8)
                serial = int(self.manifest_data(gid).get("serial", 0)) + 1
                art = make_manifest(self.identity(), "inbox", "inbox", retention_days=30,
                                    min_pow=DEFAULT_POW, serial=serial,
                                    pow_bits=await self.required_pow(gid))
                await self._post_article(art)
                entry["manifest"] = json.loads(art.body)
            entry.update({"type": "inbox", "owner": True})
        if gid not in self.data["subscribed"]:
            self.data["subscribed"].insert(0, gid)
        self.save()
        return gid

    async def inbox_owner(self, group_id: str) -> bytes:
        """The owner key of an inbox, from its manifest on the node."""
        entry = self.group_entry(group_id)
        if not entry.get("owner_key"):
            subscribed = group_id in self.data["subscribed"]
            await self.fetch_group(group_id)        # reads the manifest
            if not subscribed:                      # do not keep someone else's inbox around
                self.cache.pop(group_id, None)
                self._raw.pop(group_id, None)
                self._high.pop(group_id, None)
        if not entry.get("owner_key"):
            raise SessionError("that inbox does not exist on this node")
        if entry.get("type") != "inbox":
            raise SessionError("that group is not an inbox")
        return crypto.key_from_text(entry["owner_key"])

    def _expired(self, group_id: str, now: datetime | None = None) -> bool:
        """A key-bound group whose last seen manifest has run out (UN-RFC 0029, 5)."""
        exp = stored_expires(self.manifest_data(group_id))
        return (is_key_bound(group_id) and bool(self.manifest_data(group_id))
                and (exp is None or (now or datetime.now(timezone.utc)) >= exp))

    # ------------------------------------------------------------------
    # renewal of key-bound groups (UN-RFC 0029 section 4)
    # ------------------------------------------------------------------
    def key_bound_groups(self, name: str | None = None) -> list[str]:
        """The key-bound groups this identity owns and has a manifest for."""
        fp = self.identity(name).fingerprint
        out = []
        for gid, entry in self.data["groups"].items():
            if entry.get("owner") and entry.get("manifest") and is_key_bound(gid):
                try:
                    if split_group_id(gid)[1] == fp:
                        out.append(gid)
                except ValueError:
                    continue
        return sorted(out)

    def key_bound_expiry(self, name: str | None = None) -> datetime | None:
        """When this identity's key-bound groups run out, if not renewed (the earliest)."""
        dates = [stored_expires(self.manifest_data(g)) for g in self.key_bound_groups(name)]
        if not dates:
            return None
        if any(d is None for d in dates):
            return datetime.fromtimestamp(0, timezone.utc)   # from before UN-RFC 0029
        return min(dates)

    async def renew_key_bound(self, now: datetime | None = None,
                              rng: random.Random | None = None) -> list[str]:
        """Renew key-bound groups that are due, without asking (UN-RFC 0029 section 4).

        Each identity is renewed at a random moment, chosen on its own, within 30 days
        of becoming due, and all of its key-bound groups together at that moment. If
        expiry is near (or the manifest has no ``expires``), it renews at once.
        Returns the groups renewed."""
        now = now or datetime.now(timezone.utc)
        rng = rng or random.SystemRandom()
        renewed: list[str] = []
        for name, ident_entry in self.data["identities"].items():
            groups = self.key_bound_groups(name)
            expiry = self.key_bound_expiry(name)
            if not groups or expiry is None or expiry - now >= RENEW_WHEN_LEFT:
                ident_entry.pop("renew_at", None)
                continue
            urgent = expiry - now < RENEW_WINDOW * 2
            at = ident_entry.get("renew_at")
            if at is None and not urgent:
                at = (now + timedelta(seconds=rng.uniform(0, RENEW_WINDOW.total_seconds()))
                      ).timestamp()
                ident_entry["renew_at"] = at
                self.save()
            if not urgent and now.timestamp() < at:
                continue
            owner = self.identity(name)
            for gid in groups:
                data = self.manifest_data(gid)
                data["serial"] = int(data.get("serial", 1)) + 1     # the vault remembers it
                art = manifest_article(owner, gid, data, await self.required_pow(None), now=now)
                await self._post_article(art)
                self.group_entry(gid)["manifest"] = data
                renewed.append(gid)
            ident_entry.pop("renew_at", None)
            self.save()
        return renewed

    async def send_private(self, group_id: str, subject: str, body: str, *,
                           owner_key: bytes | None = None, references: list[str] | None = None,
                           anonymous: bool = False, content_type: str | None = None,
                           kind: str = KIND_POST, remember: bool = True) -> str:
        """Send a message to an inbox. Only its owner can read it.

        ``kind`` is ``"post"`` (a subject, read on its own, answered with a quote)
        or ``"chat"`` (a line in a running conversation, no subject) - UN-RFC 0028.
        """
        if kind == KIND_CHAT:
            subject = ""
        content_type = content_type or self.text_type()      # Markdown by default (UN-RFC 0031)
        if self._expired(group_id):          # UN-RFC 0029 section 6: look again first
            self.data["groups"].get(group_id, {}).pop("manifest", None)
            self.data["groups"].get(group_id, {}).pop("owner_key", None)
        if not self.manifest_data(group_id):
            try:
                owner_from_manifest = await self.inbox_owner(group_id)   # also learns its min_pow
            except SessionError as exc:
                raise SessionError("the receiver has no inbox you can reach") from exc
            owner_key = owner_key or owner_from_manifest
        owner_key = owner_key or await self.inbox_owner(group_id)
        sender = None if anonymous else self.identity()
        art = await self._post_with_postage(group_id, lambda bits: inbox_article(
            group_id, owner_key, from_name="" if anonymous else self.display_name(),
            subject=subject, body=body, sender=sender,
            reply_inbox=None if anonymous else self.my_inbox,
            references=references, content_type=content_type, kind=kind, pow_bits=bits))
        msgid = art.message_id
        if not remember:
            return msgid
        # The message is sealed to the recipient, so keep our own copy (encrypted, local only).
        self._remember_sent({"to": crypto.key_to_text(owner_key), "group": group_id, "msgid": msgid,
                             # where it falls among received messages: dates are rounded to
                             # 10 minutes for privacy, so they cannot order a conversation
                             "after": self._high.get(self.my_inbox, 0),
                             "subject": subject, "body": art_body_text(body), "kind": kind,
                             "references": references or [],
                             "date": datetime.now(timezone.utc).isoformat()})
        self.data["read"].setdefault(self.my_inbox, []).append(msgid)
        self.save()
        return msgid

    def reply_target(self, msg: "Message") -> str | None:
        """Where a reply to a private message goes."""
        if msg.reply_inbox:
            return msg.reply_inbox
        if msg.sender_key:
            return personal_inbox_id(crypto.key_from_text(msg.sender_key))
        return None

    # ------------------------------------------------------------------
    # contacts and conversations (client side only)
    # ------------------------------------------------------------------
    def add_contact(self, key_text: str, name: str) -> None:
        """Give a key a name of your own (a "petname"). Others cannot fake it."""
        crypto.key_from_text(key_text)
        if not name.strip():
            raise SessionError("a contact needs a name")
        if key_text == self.identity().key_text:
            raise SessionError("that is your own key")
        self.data["contacts"][key_text] = {"name": name.strip()}
        self.save()

    def remove_contact(self, key_text: str) -> None:
        self.data["contacts"].pop(key_text, None)
        self.save()

    def contact_name(self, key_text: str | None) -> str | None:
        entry = self.data["contacts"].get(key_text or "")
        return entry["name"] if entry else None

    # --- ignoring people: the reader's own killfile, never sent anywhere (#72) ---
    def ignore(self, key_text: str, label: str = "") -> None:
        crypto.key_from_text(key_text)
        if key_text == self.identity().key_text:
            raise SessionError("that is your own key")
        self.data["ignored"][key_text] = {
            "label": label.strip() or self.identity_label(key_text),
            "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.save()

    def unignore(self, key_text: str) -> None:
        self.data["ignored"].pop(key_text, None)
        self.save()

    def is_ignored(self, key_text: str | None) -> bool:
        return bool(key_text) and key_text in self.data["ignored"]

    def ignored(self) -> list[tuple[str, str]]:
        """(key, label) of the people you ignore, sorted by label."""
        return sorted(((k, v.get("label", k)) for k, v in self.data["ignored"].items()),
                      key=lambda kv: kv[1].lower())

    # --- replies to you and mentions of your names (#109); computed here, never sent ---
    def _remember_mine(self, msgid: str) -> None:
        mine = self.data.setdefault("mine", [])
        mine.append(msgid)
        del mine[:-2000]

    def my_message_ids(self) -> set[str]:
        keys = {self.identity(n).key_text for n in self.data["identities"]}
        ids = set(self.data.get("mine", []))
        for msgs in self.cache.values():
            ids.update(m.message_id for m in msgs.values() if m.author_key in keys)
        return ids

    def _mention_patterns(self) -> list["re.Pattern"]:
        """Your certified names, as they would be written in a post (UN-RFC 0019).
        Display names do not count: anyone can call themselves Andreas."""
        out = []
        for c in naming.my_names(self):
            text = naming.name_text(c.name)
            out.append(re.compile(r"(?<![a-z0-9@.-])" + re.escape(text) + r"(?![a-z0-9-]|\.[a-z0-9])",
                                  re.IGNORECASE))
        return out

    def for_me(self, msg: "Message", mine: set[str] | None = None,
               patterns: list | None = None) -> str | None:
        """'reply' if the post answers one of yours, 'mention' if it names you, else None."""
        if msg.private or not msg.readable:
            return None
        keys = {self.identity(n).key_text for n in self.data["identities"]}
        if msg.author_key in keys:
            return None
        mine = self.my_message_ids() if mine is None else mine
        if any(r in mine for r in msg.references):
            return "reply"
        patterns = self._mention_patterns() if patterns is None else patterns
        text = f"{msg.subject}\n{msg.body}"
        if any(p.search(text) for p in patterns):
            return "mention"
        return None

    def for_you(self, unread_only: bool = True) -> list["Message"]:
        """Replies to you and mentions of you in the groups you follow, newest first."""
        mine, patterns = self.my_message_ids(), self._mention_patterns()
        out = []
        for gid in self.data["subscribed"]:
            if gid == self.my_inbox:
                continue
            for m in self.visible(list(self.cache.get(gid, {}).values())):
                if (not unread_only or not self.is_read(m)) and self.for_me(m, mine, patterns):
                    out.append(m)
        return sorted(out, key=lambda m: m.date or datetime.min.replace(tzinfo=timezone.utc),
                      reverse=True)

    def for_you_count(self, group_id: str) -> int:
        return self.for_you_counts(group_id).total

    def for_you_counts(self, group_id: str | None = None) -> "ForYouCount":
        """Unread replies to you and unread mentions of you, counted apart (#170):
        in one group, or in all the groups you follow when group_id is None."""
        mine, patterns = self.my_message_ids(), self._mention_patterns()
        gids = ([group_id] if group_id is not None
                else [g for g in self.data["subscribed"] if g != self.my_inbox])
        replies = mentions = 0
        for gid in gids:
            for m in self.visible(list(self.cache.get(gid, {}).values())):
                if self.is_read(m):
                    continue
                why = self.for_me(m, mine, patterns)
                if why == "reply":
                    replies += 1
                elif why == "mention":
                    mentions += 1
        return ForYouCount(replies, mentions)

    def visible(self, msgs: list["Message"]) -> list["Message"]:
        """Leave out messages from people you ignore (your own are always shown)."""
        groups = {m.group for m in msgs}
        banned = {gid: {k for k, _ in self.banned(gid)} for gid in groups}
        if not self.data.get("show_blocked"):          # maintainers' blocks (UN-RFC 0018, 5.4)
            for gid in groups:
                banned[gid] |= set(self.hierarchy_blocks(gid))
        if not self.data["ignored"] and not any(banned.values()):
            return list(msgs)
        return [m for m in msgs if m.to_key is not None
                or not (self.is_ignored(m.sender_key or m.author_key)
                        or (not m.private and m.author_key in banned.get(m.group, ())))]

    def hierarchy_blocks(self, group_id: str) -> dict[str, tuple[str, str]]:
        """{key: (hierarchy, reason)} that maintainers block for this group."""
        if group_id.startswith("inbox@") or group_id not in self.data["groups"]:
            return {}
        try:
            return naming.blocks(self, group_id)
        except Exception:  # noqa: BLE001  lists that cannot be read block nothing
            return {}

    def hidden_by_blocks(self, group_id: str) -> list[tuple[str, str, int]]:
        """(hierarchy, reason, posts) hidden in a group by maintainers' blocks."""
        if self.data.get("show_blocked"):
            return []
        blocked = self.hierarchy_blocks(group_id)
        count: dict[str, int] = {}
        for m in self.cache.get(group_id, {}).values():
            if m.author_key in blocked:
                count[m.author_key] = count.get(m.author_key, 0) + 1
        return [(blocked[k][0], blocked[k][1], n) for k, n in count.items()]

    def set_show_blocked(self, on: bool) -> None:
        self.data["show_blocked"] = bool(on)
        self.save()

    def contacts(self) -> list[tuple[str, str]]:
        """(key, name) sorted by name."""
        return sorted(((k, v["name"]) for k, v in self.data["contacts"].items()),
                      key=lambda kv: kv[1].lower())

    def sent_messages(self, to: str | None = None) -> list["Message"]:
        """Your copies of the private messages you sent (to one key, or all).

        They are sealed to their recipients, so the node's copies are unreadable to
        you; these come from the encrypted ``sent`` sidecar of the vault.
        """
        mine = self.identity().key_text
        out = []
        for i, e in enumerate(self.sent):
            if to is not None and e.get("to") != to:
                continue
            msg = Message(-1 - i, e["msgid"], self.my_inbox, subject=e["subject"],
                          from_name="You", author_key=mine, body=e["body"],
                          references=e.get("references", []), encrypted=True, private=True,
                          sender_key=mine, reply_inbox=e.get("group"), to_key=e.get("to"),
                          kind=KIND_CHAT if e.get("kind") == KIND_CHAT else KIND_POST)
            try:
                msg.date = datetime.fromisoformat(e["date"])
            except (KeyError, ValueError):
                pass
            out.append(msg)
        return out

    def _in_order(self, received: list["Message"], sent: list["Message"]) -> list["Message"]:
        """Received and sent private messages together, oldest first. Inbox dates are
        rounded to 10 minutes for privacy, so a sent message is placed after the
        received messages that had arrived when it was written."""
        after = {e["msgid"]: e.get("after", 0) for e in self.sent}
        order = {m.message_id: (m.number, 0, 0) for m in received}
        for i, m in enumerate(sent):
            order[m.message_id] = (after.get(m.message_id, 0), 1, i)
        return sorted(received + sent, key=lambda m: order[m.message_id])

    def conversation(self, key_text: str, kind: str | None = None) -> list["Message"]:
        """Private messages between you and a key, both directions, oldest first.

        ``kind`` keeps only chats or only posts (UN-RFC 0028); None keeps both.
        """
        received = [m for m in self.cache.get(self.my_inbox, {}).values()
                    if m.sender_key == key_text and (kind is None or m.kind == kind)]
        sent = [m for m in self.sent_messages(key_text) if kind is None or m.kind == kind]
        return self._in_order(received, sent)

    def private_messages(self, kind: str | None = None) -> list["Message"]:
        """Your inbox and what you sent privately, oldest first; only one ``kind`` if given."""
        return self._in_order(
            [m for m in self.cache.get(self.my_inbox, {}).values() if kind is None or m.kind == kind],
            [m for m in self.sent_messages() if kind is None or m.kind == kind])

    def unread_from(self, key_text: str, kind: str | None = None) -> int:
        return sum(1 for m in self.cache.get(self.my_inbox, {}).values()
                   if m.sender_key == key_text and (kind is None or m.kind == kind)
                   and not self.is_read(m))

    def unread_private(self, kind: str | None = None) -> int:
        """Unread private messages of one kind (or all), from anyone."""
        return sum(1 for m in self.visible(list(self.cache.get(self.my_inbox, {}).values()))
                   if (kind is None or m.kind == kind) and not self.is_read(m))

    def _in_private_posts(self, m: "Message") -> bool:
        """Private posts; chats live in a conversation per person (chat_partners). An
        anonymous chat has no person to belong to, so it stays here."""
        return m.kind != KIND_CHAT or not (m.sender_key or m.to_key)

    def private_posts(self) -> list["Message"]:
        """What the "Private posts" view shows (UN-RFC 0028 section 6.2), oldest first."""
        return [m for m in self.private_messages() if self._in_private_posts(m)]

    def unread_private_posts(self) -> int:
        return sum(1 for m in self.visible(list(self.cache.get(self.my_inbox, {}).values()))
                   if self._in_private_posts(m) and not self.is_read(m))

    def chat_partners(self) -> list[str]:
        """Everyone you have a chat with: your contacts, and anyone else you have
        chatted with (so no chat ever goes missing, UN-RFC 0028 section 6.2).

        Contacts first, by name; then the others, the most recent chat first."""
        contacts = [k for k, _ in self.contacts()]
        last: dict[str, int] = {}
        for m in self.visible(list(self.cache.get(self.my_inbox, {}).values())):
            if m.kind == KIND_CHAT and m.sender_key:
                last[m.sender_key] = max(last.get(m.sender_key, -1), m.number)
        for i, e in enumerate(self.sent):
            if e.get("kind") == KIND_CHAT and e.get("to"):
                last[e["to"]] = max(last.get(e["to"], -1), e.get("after", 0))
        me = self.identity().key_text
        others = sorted((k for k in last if k not in contacts and k != me),
                        key=lambda k: last[k], reverse=True)
        return contacts + others

    def _load_sent(self) -> list[dict]:
        try:
            payload = self.vault.read_sidecar(SENT_SIDECAR)
        except Exception:  # noqa: BLE001
            return []
        return json.loads(payload).get("sent", []) if payload else []

    def _remember_sent(self, entry: dict) -> None:
        self.sent.append(entry)
        self.vault.write_sidecar(SENT_SIDECAR, json.dumps({"v": 1, "sent": self.sent}).encode())

    # --- reporting a post (#74): private messages to those who can act on it ---
    async def report_targets(self, msg: "Message") -> list[tuple[str, str, str]]:
        """(who, inbox, key) of the people who can act on a post: the group's owner,
        its moderators, the maintainers of its hierarchy and the operator of the
        node it was read from."""
        out: list[tuple[str, str, str]] = []
        data = self.manifest_data(msg.group)
        me = self.identity().key_text

        def add(who: str, key: str | None, inbox: str | None = None) -> None:
            if not key or key == me or any(k == key for _, _, k in out):
                return
            try:
                inbox = inbox or personal_inbox_id(crypto.key_from_text(key))
            except crypto.CryptoError:
                return
            out.append((who, inbox, key))

        if data.get("owner"):
            add(f"The group's owner ({self.identity_label(data['owner'])})", data["owner"])
        for k in data.get("moderators", []):
            add(f"Moderator {self.identity_label(k)}", k)
        for h in naming.governing(self, msg.group):
            add(f"Maintainer of {h.name}.* ({self.identity_label(h.maintainer)})", h.maintainer)
        try:
            info = await self.node_info(self.node_for(msg.group))
        except (SessionError, OSError, ConnectionError, ValueError):
            info = {}
        if info.get("operator") and info.get("contact"):
            add(f"The operator of {info.get('name', 'the node')}", info["operator"], info["contact"])
        return out

    async def report(self, msg: "Message", targets: list[tuple[str, str, str]], note: str = "",
                     anonymous: bool = False) -> int:
        """Send a report of a post to the chosen people. Returns how many got it."""
        if not targets:
            raise SessionError("choose at least one person to report to")
        quote = "\n".join("> " + line for line in (msg.body or "").rstrip("\n").splitlines()[:40])
        body = (f"Report of a post\n\nGroup: {msg.group}\nMessage-ID: {msg.message_id}\n"
                f"Author key: {msg.author_key}\n"
                + (f"\nNote from the reporter:\n{note.strip()}\n" if note.strip() else "")
                + f"\nThe post, as the reporter saw it:\nFrom: {msg.from_name}\n"
                f"Subject: {msg.subject}\n\n{quote}\n")
        sent, errors = 0, []
        for _, inbox, key in targets:
            try:
                await self.send_private(inbox, f"Report: {msg.subject or '(no subject)'}", body,
                                        owner_key=crypto.key_from_text(key),
                                        content_type=REPORT_TYPE + "; charset=utf-8",
                                        anonymous=anonymous,
                                        remember=False)
                sent += 1
            except (SessionError, OSError, ConnectionError) as exc:
                errors.append(str(exc))
        if not sent:
            raise SessionError("the report could not be sent: " + "; ".join(errors))
        return sent

    @staticmethod
    def reported_post(msg: "Message") -> tuple[str, str] | None:
        """(group, Message-ID) named in a report you received."""
        if not msg.content_type.startswith(REPORT_TYPE):
            return None
        found = dict(re.findall(r"^(Group|Message-ID): (\S+)$", msg.body or "", re.M))
        if "Group" in found and "Message-ID" in found:
            return found["Group"], found["Message-ID"]
        return None

    async def node_info(self, node: str | None = None) -> dict:
        """UN-RFC 0011 node information, or {} if the node does not offer it."""
        async def run(c: Client) -> dict:
            if c.capability("UNSEENET-NODEINFO") is None:
                return {}
            lines = await c.multiline("LIST UNSEENET.NODEINFO", 215)
            return json.loads(lines[0]) if lines else {}
        return await self._call(run, node)

    def _identity_for_fingerprint(self, fp: str) -> crypto.Identity | None:
        for entry in self.data["identities"].values():
            ident = crypto.Identity.from_seed(bytes.fromhex(entry["seed"]))
            if ident.fingerprint == fp:
                return ident
        return None

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------
    async def fetch_group(self, group_id: str) -> list[Message]:
        """Fetch new articles in a group; returns all cached messages, oldest first."""
        cache = self.cache.setdefault(group_id, {})
        raws = self._raw.setdefault(group_id, {})
        me = self.identity()
        entry = self.group_entry(group_id)

        def reader(since: int):
            async def run(c: Client):
                try:
                    _, low, high = await c.group(group_id)
                except NNTPError as exc:
                    if "removed by its owner" in exc.text:
                        raise SessionError("removed by its owner") from exc
                    raise SessionError("group not carried by this node") from exc
                start = max(low, since + 1)
                if not entry.get("manifest") and not entry.get("manifest_rescanned"):
                    # Joined before manifests were kept (or never seen it): read the group
                    # once from the start so title, rules, view and postage are known.
                    start = low
                    entry["manifest_rescanned"] = True
                fetched = []
                for n in range(start, high + 1):
                    raw = await c.article(str(n))
                    if raw is not None:
                        fetched.append((n, raw))
                return fetched, high
            return run

        home = self.node_for(group_id)
        try:
            fetched, high = await self._call(reader(self._high.get(group_id, 0)), home)
        except (SessionError, OSError, ConnectionError, asyncio.IncompleteReadError) as first:
            if "removed by its owner" in str(first):
                raise
            for other in (n for n in self.nodes if n != home):   # another node may carry it
                try:
                    fetched, high = await self._call(reader(0), other)
                except (SessionError, OSError, ConnectionError, asyncio.IncompleteReadError):
                    continue
                self.status(f"{short_group_id(group_id)} is now read from {other}")
                self.pin_group(group_id, other)
                cache = self.cache.setdefault(group_id, {})
                raws = self._raw.setdefault(group_id, {})
                break
            else:
                raise first
        changed = False
        for n, raw in fetched:
            raw = strip_reader_headers(raw)
            msg = self._parse(n, raw, group_id, entry, me)
            if msg is None:
                changed = True     # control article updated group state
                continue
            cache[n] = msg
            raws[n] = raw
        if high > self._high.get(group_id, 0):
            self._high[group_id] = high
        if entry.get("cancels") and self._apply_cancels(group_id):
            changed = True
        if changed:
            self.save()
        if fetched or changed:
            self.save_offline()
        return sorted(cache.values(), key=lambda m: m.number)

    # ------------------------------------------------------------------
    # offline cache (UN-RFC 0007: encrypted with the vault key)
    # ------------------------------------------------------------------
    def load_offline(self) -> int:
        """Load cached articles so groups can be read without a connection.

        Article numbers are local to a node, so the cache is only used for the
        node it was made with. Returns the number of articles loaded.
        """
        try:
            payload = self.vault.read_sidecar(CACHE_SIDECAR)
        except Exception:  # noqa: BLE001  damaged cache: start over, the node has it all
            return 0
        if not payload:
            return 0
        data = json.loads(payload)
        if data.get("v") not in (1, 2):
            return 0
        me = self.identity()
        loaded = 0
        for gid, g in data.get("groups", {}).items():
            # numbers only mean something on the node they came from
            if g.get("node", data.get("node")) != self.node_for(gid):
                continue
            entry = self.group_entry(gid)
            self._high[gid] = max(self._high.get(gid, 0), int(g.get("high", 0)))
            cache = self.cache.setdefault(gid, {})
            raws = self._raw.setdefault(gid, {})
            for n_text, b64raw in g.get("articles", {}).items():
                n, raw = int(n_text), base64.b64decode(b64raw)
                msg = self._parse(n, raw, gid, entry, me)
                if msg is not None:
                    cache[n], raws[n] = msg, raw
                    loaded += 1
            if entry.get("cancels"):
                self._apply_cancels(gid)
        return loaded

    def save_offline(self) -> None:
        groups = {}
        for gid, raws in self._raw.items():
            keep = sorted(raws)[-MAX_CACHED_PER_GROUP:]
            groups[gid] = {"node": self.node_for(gid), "high": self._high.get(gid, 0),
                           "articles": {str(n): base64.b64encode(raws[n]).decode() for n in keep}}
        payload = json.dumps({"v": 2, "groups": groups}).encode()
        self.vault.write_sidecar(CACHE_SIDECAR, payload)

    def may_cancel(self, msg: Message) -> bool:
        """Your own post, or any post in a group you own or moderate (UN-RFC 0004, 7.1)."""
        if msg is None or msg.private or msg.group not in self.data["groups"]:
            return False
        me = self.identity().key_text
        manifest = self.manifest_data(msg.group)
        return msg.author_key == me or manifest.get("owner") == me \
            or me in manifest.get("moderators", [])

    async def cancel(self, msg: Message, reason: str = "") -> str:
        """Withdraw a post from the network (UN-RFC 0004, section 7). Best effort:
        people who read it already, and nodes that ignore cancels, may keep it."""
        if not self.may_cancel(msg):
            raise SessionError("you can only withdraw your own posts, or posts in a group "
                               "you own or moderate")
        group_id = msg.group
        if self.group_entry(group_id).get("type") == "closed":
            reason = ""                     # the nodes could read it (section 7.5)
        me = self.identity()
        art = await self._post_with_postage(group_id, lambda bits: new_article(
            group_id, None, reason, extra=[("Control", f"cancel {msg.message_id}")]
        ).finalize(me, bits))
        entry = self.group_entry(group_id)
        entry.setdefault("cancels", {})[msg.message_id] = {"by": me.key_text, "date": art["Date"]}
        self._apply_cancels(group_id)
        self.save()
        self.save_offline()
        return art.message_id

    def _apply_cancels(self, group_id: str) -> bool:
        """Drop posts withdrawn by a valid cancel (UN-RFC 0004, 7.1 and 7.3).

        The client checks each cancel itself: signed (checked in _parse) by the
        target's author, or by the group's owner or a moderator. Cancels whose
        target has not arrived are kept for the group's retention, then dropped.
        True if anything changed."""
        entry = self.group_entry(group_id)
        cancels = entry.get("cancels") or {}
        cache = self.cache.get(group_id, {})
        raws = self._raw.get(group_id, {})
        manifest = self.manifest_data(group_id)
        privileged = {manifest.get("owner")} | set(manifest.get("moderators", []))
        by_id = {m.message_id: n for n, m in cache.items()}
        keep_days = int(manifest.get("retention_days", 90))
        now = datetime.now(timezone.utc)
        changed = False
        for target, c in list(cancels.items()):
            n = by_id.get(target)
            if n is None:
                try:
                    old = (now - parse_date(c.get("date", ""))).days > keep_days
                except (TypeError, ValueError):
                    old = True
                if old:                     # pending too long (section 7.2)
                    del cancels[target]
                    changed = True
                continue
            try:                            # the target's signer, also for private messages
                target_author = Article.from_bytes(raws[n])["Author-Key"] if n in raws \
                    else cache[n].author_key
            except (ArticleError, KeyError, ValueError):
                target_author = cache[n].author_key
            if c.get("by") == target_author or c.get("by") in privileged:
                del cache[n]
                raws.pop(n, None)
                changed = True
            else:                           # not valid for this target: forget it
                del cancels[target]
                changed = True
        return changed

    @staticmethod
    def _take_manifest(art: Article, group_id: str, entry: dict) -> bool:
        """Keep a manifest from a node only if it is valid (UN-RFC 0004, section 4):
        signed by the owner whose fingerprint is in the group ID, for this group,
        and of the same type as before. A client does not trust its node for this:
        a hostile node could otherwise serve a manifest signed by its own key, e.g.
        adding itself to the posters of unseenet.nodes or unseenet.names (#41).
        Of the valid ones the newest wins (section 3.2). True if it was taken."""
        from ..core.groups import Manifest
        try:
            # our own inbox from before UN-RFC 0029 has no expires: take it, to renew it
            m = Manifest.from_article(art, stored=bool(entry.get("owner")))
        except (ArticleError, ValueError, TypeError):
            return False
        if m.group_id != group_id:
            return False
        old = entry.get("manifest") or {}
        if old:
            if old.get("type") != m.type or old.get("owner") != m.raw.get("owner") \
                    or bool(old.get("local")) != m.local:
                return False                # type, owner and locality never change
            # Newer serial wins; on a tie the lower Message-ID (as Manifest.supersedes)
            if (m.serial, entry.get("manifest_id", "")) <= (int(old.get("serial", 0)), m.message_id):
                return False
        entry["manifest"] = dict(m.raw)
        entry["manifest_id"] = m.message_id
        entry["type"] = m.type
        entry["owner_key"] = m.raw.get("owner")
        if m.title:
            entry["title"] = m.title
        return True

    def _parse(self, n: int, raw: bytes, group_id: str, entry: dict, me) -> Message | None:
        try:
            art = Article.from_bytes(raw)
            validate_structure(art, raw_size=len(raw))
        except ArticleError as err:
            return Message(n, f"<invalid-{n}>", group_id, subject="(invalid article)",
                           readable=False, error=str(err))
        ctl = art.control
        if ctl and ctl[0] == "manifest":
            self._take_manifest(art, group_id, entry)
            return None
        if ctl and ctl[0] in ("key-update", "key-grant"):
            try:
                if ctl[0] == "key-update" and json.loads(art.body).get("closes_previous") is True:
                    closed = entry.setdefault("closed", {})        # epoch -> article number
                    closed.setdefault(ctl[1], n)
            except (ValueError, AttributeError):
                pass
            opened = open_envelope(art, me)
            if opened:
                epoch, keys = opened
                entry["keys"][str(epoch)] = keys.secret.hex()
                self._redecrypt(group_id)
            return None
        if ctl and ctl[0] == "cancel" and len(ctl) == 2:
            # checked against the target in _apply_cancels (UN-RFC 0004, 7.3)
            entry.setdefault("cancels", {}).setdefault(ctl[1], {
                "by": art["Author-Key"], "date": art.get("Date", "")})
            return None
        if ctl:
            return None
        msg = Message(n, art.message_id, group_id, author_key=art["Author-Key"],
                      references=(art.get("References") or "").split())
        try:
            msg.date = parse_date(art["Date"])
        except (TypeError, ValueError):
            pass
        if art.get("Encrypted", "").strip() == INBOX_SCHEME:
            msg.encrypted = msg.private = True
            self._open_private(msg, art, group_id)
        elif "Encrypted" in art:
            # posted with an old key after a member was removed (UN-RFC 0004, 6.5)
            try:
                epoch = encryption_epoch(art)
            except (ArticleError, ValueError):
                epoch = 0
            if any(int(e) > epoch and n > at for e, at in entry.get("closed", {}).items()):
                return None
            msg.encrypted = True
            msg.raw = raw
            self._decrypt_into(msg, art, entry)
        else:
            msg.subject, msg.from_name, msg.body = art.get("Subject", ""), art["From"], art.body
            msg.kind = message_kind(art)                     # UN-RFC 0028
            msg.content_type = art.get("Content-Type", "")   # Markdown or plain (UN-RFC 0031)
            naming.note_certificate(self, msg.author_key, art.get(names.HEADER))
        return msg

    def _open_private(self, msg: Message, art: Article, group_id: str) -> None:
        owner = self._identity_for_fingerprint(split_group_id(group_id)[1])
        if owner is None:
            msg.readable = False
            msg.subject = "(private message for the inbox owner)"
            return
        try:
            inner, sender = open_inbox_article(art, owner)
        except ArticleError as err:
            msg.readable, msg.error, msg.subject = False, str(err), "(unreadable private message)"
            return
        msg.subject, msg.body = inner.get("Subject", ""), inner.body
        msg.content_type = inner.get("Content-Type", "")
        msg.kind = message_kind(inner)
        msg.reply_inbox = inner.get("Reply-Inbox")
        if sender is None:
            msg.from_name, msg.author_key = "anonymous", ""
        else:
            msg.sender_key = crypto.key_to_text(sender)
            msg.author_key = msg.sender_key          # show the real sender, not the one-time key
            msg.from_name = inner.get("From", "")
            naming.note_certificate(self, msg.sender_key, inner.get(names.HEADER))

    def _decrypt_into(self, msg: Message, art: Article, entry: dict) -> None:
        key_hex = entry["keys"].get(str(encryption_epoch(art)))
        if not key_hex:
            msg.readable = False
            msg.subject = "(encrypted - you are not a member)"
            return
        inner = decrypt_article(art, crypto.GroupKeys(bytes.fromhex(key_hex)))
        msg.readable = True
        msg.subject, msg.from_name, msg.body = inner.get("Subject", ""), inner["From"], inner.body
        msg.kind = message_kind(inner)                       # inside the encryption (UN-RFC 0028)
        msg.content_type = inner.get("Content-Type", "")

    def _redecrypt(self, group_id: str) -> None:
        entry = self.group_entry(group_id)
        for msg in self.cache.get(group_id, {}).values():
            if msg.encrypted and not msg.readable and msg.raw:
                self._decrypt_into(msg, Article.from_bytes(msg.raw), entry)

    # ------------------------------------------------------------------
    # read marks
    # ------------------------------------------------------------------
    def is_read(self, msg: Message) -> bool:
        return msg.message_id in self.data["read"].get(msg.group, [])

    def mark_read(self, msg: Message, save: bool = True) -> None:
        marks = self.data["read"].setdefault(msg.group, [])
        if msg.message_id not in marks:
            marks.append(msg.message_id)
            del marks[:-MAX_READ_MARKS]
            if save:
                self.save()

    def unread_count(self, group_id: str) -> int:
        return sum(1 for m in self.visible(list(self.cache.get(group_id, {}).values()))
                   if not self.is_read(m))

    # ------------------------------------------------------------------
    # posting
    # ------------------------------------------------------------------
    async def _post_article(self, art: Article, node: str | None = None) -> str:
        raw = art.to_bytes()
        target = node or self.node_for(art.group)
        code, text = await self._call(lambda c: c.post(raw), target)
        if code != 240 and node is None and "not carried" in text:
            for other in (n for n in self.nodes if n != target):   # e.g. someone's inbox elsewhere
                try:
                    code, text = await self._call(lambda c: c.post(raw), other)
                except (OSError, ConnectionError, SessionError, asyncio.IncompleteReadError):
                    continue
                if code == 240:
                    if art.group in self.data["groups"]:
                        self.pin_group(art.group, other)
                    break
        if code != 240:
            raise SessionError(f"rejected by node: {text}")
        return art.message_id

    async def post(self, group_id: str, subject: str, body: str,
                   references: list[str] | None = None, kind: str = KIND_POST,
                   content_type: str | None = None) -> str:
        """Post to a group: a post (with a subject) or a chat line (UN-RFC 0028)."""
        if kind not in self.group_kinds(group_id):
            raise SessionError("this group does not take " +
                               ("chat lines" if kind == KIND_CHAT else "posts with a subject"))
        if kind == KIND_POST and not subject.strip():
            raise SessionError("a post needs a subject")
        content_type = content_type or self.text_type()      # Markdown by default (UN-RFC 0031)
        author = self.identity()
        entry = self.group_entry(group_id)
        cert = None
        if entry.get("type") == "closed":
            if not entry["keys"]:
                raise SessionError("you are not a member of this closed group")
            epoch = max(int(e) for e in entry["keys"])
            keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))

            def build(bits):                       # postage is CPU work: runs in a thread
                return encrypted_article(
                    group_id, epoch, keys, author, from_name=self.display_name(),
                    subject=subject, body=body, references=references, kind=kind,
                    content_type=content_type, pow_bits=bits)
        else:
            cert = naming.header_for(self, group_id)     # your name, once a week here (UN-RFC 0019)

            def build(bits):
                # a chat line has an empty subject; the kind is a header (UN-RFC 0028, 3.2-3.3)
                art = new_article(group_id, "" if kind == KIND_CHAT else subject, body,
                                  from_name=self.display_name(), references=references,
                                  extra=[("Content-Type", content_type), ("Message-Kind", kind)]
                                  + ([cert] if cert else []))
                return art.finalize(author, bits)
        gtype = self.manifest_data(group_id).get("type") or entry.get("type")
        if gtype == "moderated" and not self.moderates(group_id):
            return await self._submit(group_id, subject, build)
        msgid = (await self._post_with_postage(group_id, build)).message_id
        self._remember_mine(msgid)
        if cert:
            naming.sent_header(self, group_id)
        marks = self.data["read"].setdefault(group_id, [])   # your own posts are read
        marks.append(msgid)
        self.save()
        return msgid


SUBMISSION_TYPE = "message/unseenet"      # UN-RFC 0009 section 3
REPORT_TYPE = "text/x-unseenet-report"    # a report of a post (#74)


def default_vault_path() -> Path:
    """``unseenet.vault`` in the current directory, or in ``data/`` of a portable build."""
    from ..portable import default_vault_path as portable_default
    return portable_default()
