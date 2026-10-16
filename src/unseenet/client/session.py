"""Client session: vault, node connection, reading and posting.

Shared by the command line and the TUI. Everything persistent lives in the
encrypted vault (UN-RFC 0007); articles are cached in memory only.
"""

from __future__ import annotations

import asyncio
import re
import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..core import crypto
from ..core.article import Article, ArticleError, new_article, parse_date, validate_structure
from ..core.groups import (INBOX_SCHEME, MAX_RULES, VIEWS, decrypt_article, encrypted_article,
                           encryption_epoch, inbox_article, make_key_update, make_manifest,
                           manifest_article, open_envelope, open_inbox_article, personal_inbox_id,
                           short_group_id, split_group_id)
from ..core.tor import BRIDGE_MODES, TorError, TorProcess, bridges_for
from ..core.vault import Vault
from ..nntp import Client, NNTPError

DEFAULT_POW = 20
MAX_READ_MARKS = 5000
MAX_CACHED_PER_GROUP = 2000
SIG_SEPARATOR = "-- \n"         # the Usenet signature delimiter (RFC 3676, 4.3): dash dash space
MAX_SIG_LINES = 4               # the old netiquette limit
DEFAULT_SIGNATURE = "{name}  ·  {key}"   # until you set your own; empty means none
CACHE_SIDECAR = "cache"
SENT_SIDECAR = "sent"           # copies of private messages you sent (they are sealed to others)


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

    def _forget_numbers(self, group_id: str) -> None:
        """Article numbers belong to one node: drop them when a group moves."""
        for store in (self.cache, self._raw, self._high):
            store.pop(group_id, None)

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
                           node: str | None = None) -> str:
        owner = self.identity()
        node = node or self.node
        if retention_days is None:
            retention_days = 30 if gtype == "inbox" else 90
        art = make_manifest(owner, name, gtype, title=title, description=description,
                            min_pow=min_pow, local=local, retention_days=retention_days,
                            rules=rules, view=view, low_latency=low_latency,
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

    def manifest_data(self, group_id: str) -> dict:
        """The newest manifest seen for a group ({} if none yet)."""
        return dict(self.data["groups"].get(group_id, {}).get("manifest", {}))

    async def update_group(self, group_id: str, **changes) -> dict:
        """Publish a new manifest with a higher serial (owner only).

        Allowed changes: title, description, rules, view, low_latency, min_pow, retention_days.
        Type, owner and locality can never change (UN-RFC 0004, 4).
        """
        entry = self.data["groups"].get(group_id, {})
        if not entry.get("owner"):
            raise SessionError("only the owner can change a group")
        data = self.manifest_data(group_id)
        if not data:
            raise SessionError("the group's manifest has not been fetched yet")
        allowed = {"title", "description", "rules", "view", "low_latency", "min_pow", "retention_days"}
        for key, value in changes.items():
            if key not in allowed:
                raise SessionError(f"{key} cannot be changed")
            if value in (None, "", False) and key in ("title", "description", "rules", "low_latency"):
                data.pop(key, None)
            else:
                data[key] = value
        if len(data.get("rules", "")) > MAX_RULES:
            raise SessionError(f"rules are limited to {MAX_RULES} characters")
        if data.get("view", "threads") not in VIEWS:
            raise SessionError("view must be threads or chat")
        data["serial"] = int(data.get("serial", 1)) + 1
        art = manifest_article(self.identity(), group_id, data, await self.required_pow(None))
        await self._post_article(art)
        entry.update({"manifest": data, "title": data.get("title", "")})
        self.save()
        return data

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
                art = make_manifest(self.identity(), "inbox", "inbox", retention_days=30,
                                    min_pow=DEFAULT_POW, pow_bits=await self.required_pow(gid))
                await self._post_article(art)
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

    async def send_private(self, group_id: str, subject: str, body: str, *,
                           owner_key: bytes | None = None, references: list[str] | None = None,
                           anonymous: bool = False) -> str:
        """Send a message to an inbox. Only its owner can read it."""
        if not self.manifest_data(group_id):
            owner_from_manifest = await self.inbox_owner(group_id)   # also learns its min_pow
            owner_key = owner_key or owner_from_manifest
        owner_key = owner_key or await self.inbox_owner(group_id)
        sender = None if anonymous else self.identity()
        art = await self._post_with_postage(group_id, lambda bits: inbox_article(
            group_id, owner_key, from_name="" if anonymous else self.display_name(),
            subject=subject, body=body, sender=sender,
            reply_inbox=None if anonymous else self.my_inbox,
            references=references, pow_bits=bits))
        msgid = art.message_id
        # The message is sealed to the recipient, so keep our own copy (encrypted, local only).
        self._remember_sent({"to": crypto.key_to_text(owner_key), "group": group_id, "msgid": msgid,
                             # where it falls among received messages: dates are rounded to
                             # 10 minutes for privacy, so they cannot order a conversation
                             "after": self._high.get(self.my_inbox, 0),
                             "subject": subject, "body": art_body_text(body),
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

    def contacts(self) -> list[tuple[str, str]]:
        """(key, name) sorted by name."""
        return sorted(((k, v["name"]) for k, v in self.data["contacts"].items()),
                      key=lambda kv: kv[1].lower())

    def conversation(self, key_text: str) -> list["Message"]:
        """All private messages between you and a key, both directions, oldest first."""
        received = [m for m in self.cache.get(self.my_inbox, {}).values()
                    if m.sender_key == key_text]
        mine = self.identity().key_text
        sent = []
        for i, e in enumerate(self.sent):
            if e.get("to") != key_text:
                continue
            msg = Message(-1 - i, e["msgid"], self.my_inbox, subject=e["subject"],
                          from_name="You", author_key=mine, body=e["body"],
                          references=e.get("references", []), encrypted=True, private=True,
                          sender_key=mine)
            try:
                msg.date = datetime.fromisoformat(e["date"])
            except (KeyError, ValueError):
                pass
            sent.append(msg)
        after = {e["msgid"]: e.get("after", 0) for e in self.sent}
        order = {m.message_id: (m.number, 0, 0) for m in received}
        for i, m in enumerate(sent):
            order[m.message_id] = (after.get(m.message_id, 0), 1, i)
        return sorted(received + sent, key=lambda m: order[m.message_id])

    def unread_from(self, key_text: str) -> int:
        return sum(1 for m in self.cache.get(self.my_inbox, {}).values()
                   if m.sender_key == key_text and not self.is_read(m))

    def _load_sent(self) -> list[dict]:
        try:
            payload = self.vault.read_sidecar(SENT_SIDECAR)
        except Exception:  # noqa: BLE001
            return []
        return json.loads(payload).get("sent", []) if payload else []

    def _remember_sent(self, entry: dict) -> None:
        self.sent.append(entry)
        self.vault.write_sidecar(SENT_SIDECAR, json.dumps({"v": 1, "sent": self.sent}).encode())

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
        if changed:
            self.save()
        if fetched:
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
        return loaded

    def save_offline(self) -> None:
        groups = {}
        for gid, raws in self._raw.items():
            keep = sorted(raws)[-MAX_CACHED_PER_GROUP:]
            groups[gid] = {"node": self.node_for(gid), "high": self._high.get(gid, 0),
                           "articles": {str(n): base64.b64encode(raws[n]).decode() for n in keep}}
        payload = json.dumps({"v": 2, "groups": groups}).encode()
        self.vault.write_sidecar(CACHE_SIDECAR, payload)

    def _parse(self, n: int, raw: bytes, group_id: str, entry: dict, me) -> Message | None:
        try:
            art = Article.from_bytes(raw)
            validate_structure(art, raw_size=len(raw))
        except ArticleError as err:
            return Message(n, f"<invalid-{n}>", group_id, subject="(invalid article)",
                           readable=False, error=str(err))
        ctl = art.control
        if ctl and ctl[0] == "manifest":
            data = json.loads(art.body)
            if int(data.get("serial", 0)) >= int(entry.get("manifest", {}).get("serial", 0)):
                entry["manifest"] = data            # the newest one wins (UN-RFC 0004, 3.2)
                entry["type"] = data.get("type")
                entry["owner_key"] = data.get("owner")
                if data.get("title"):
                    entry["title"] = data["title"]
            return None
        if ctl and ctl[0] in ("key-update", "key-grant"):
            opened = open_envelope(art, me)
            if opened:
                epoch, keys = opened
                entry["keys"][str(epoch)] = keys.secret.hex()
                self._redecrypt(group_id)
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
            msg.encrypted = True
            msg.raw = raw
            self._decrypt_into(msg, art, entry)
        else:
            msg.subject, msg.from_name, msg.body = art["Subject"], art["From"], art.body
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
        msg.reply_inbox = inner.get("Reply-Inbox")
        if sender is None:
            msg.from_name, msg.author_key = "anonymous", ""
        else:
            msg.sender_key = crypto.key_to_text(sender)
            msg.author_key = msg.sender_key          # show the real sender, not the one-time key
            msg.from_name = inner.get("From", "")

    def _decrypt_into(self, msg: Message, art: Article, entry: dict) -> None:
        key_hex = entry["keys"].get(str(encryption_epoch(art)))
        if not key_hex:
            msg.readable = False
            msg.subject = "(encrypted - you are not a member)"
            return
        inner = decrypt_article(art, crypto.GroupKeys(bytes.fromhex(key_hex)))
        msg.readable = True
        msg.subject, msg.from_name, msg.body = inner["Subject"], inner["From"], inner.body

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
        return sum(1 for m in self.cache.get(group_id, {}).values() if not self.is_read(m))

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
                   references: list[str] | None = None) -> str:
        author = self.identity()
        entry = self.group_entry(group_id)
        if entry.get("type") == "closed":
            if not entry["keys"]:
                raise SessionError("you are not a member of this closed group")
            epoch = max(int(e) for e in entry["keys"])
            keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))

            def build(bits):                       # postage is CPU work: runs in a thread
                return encrypted_article(
                    group_id, epoch, keys, author, from_name=self.display_name(),
                    subject=subject, body=body, references=references, pow_bits=bits)
        else:
            def build(bits):
                art = new_article(group_id, subject, body, from_name=self.display_name(),
                                  references=references)
                return art.finalize(author, bits)
        msgid = (await self._post_with_postage(group_id, build)).message_id
        marks = self.data["read"].setdefault(group_id, [])   # your own posts are read
        marks.append(msgid)
        self.save()
        return msgid


def default_vault_path() -> Path:
    """``unseenet.vault`` in the current directory, or in ``data/`` of a portable build."""
    from ..portable import default_vault_path as portable_default
    return portable_default()
