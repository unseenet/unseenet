"""Client session: vault, node connection, reading and posting.

Shared by the command line and the TUI. Everything persistent lives in the
encrypted vault (UN-RFC 0007); articles are cached in memory only.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..core import crypto
from ..core.article import Article, ArticleError, new_article, parse_date, validate_structure
from ..core.groups import (decrypt_article, encrypted_article, encryption_epoch, make_key_update,
                           make_manifest, open_envelope, short_group_id, split_group_id)
from ..core.tor import TorProcess
from ..core.vault import Vault
from ..nntp import Client, NNTPError

DEFAULT_POW = 20
MAX_READ_MARKS = 5000
MAX_CACHED_PER_GROUP = 2000
CACHE_SIDECAR = "cache"


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

    @property
    def short(self) -> str:
        return short_group_id(self.group_id)


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
        self._client: Client | None = None
        self._lock = asyncio.Lock()
        self.cache: dict[str, dict[int, Message]] = {}
        self._raw: dict[str, dict[int, bytes]] = {}   # what the offline cache stores
        self._high: dict[str, int] = {}               # highest article number fetched
        d = self.vault.data
        d.setdefault("identities", {})
        d.setdefault("groups", {})
        d.setdefault("nodes", [])
        d.setdefault("subscribed", [])
        d.setdefault("read", {})

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

    def new_identity(self, name: str, display: str | None = None) -> crypto.Identity:
        ident = crypto.Identity.generate()
        self.data["identities"][name] = {"seed": ident.seed.hex(), "display": display or name}
        self.data.setdefault("default_identity", name)
        self.save()
        return ident

    def add_node(self, address: str) -> None:
        if address not in self.data["nodes"]:
            self.data["nodes"].append(address)
            self.save()

    @property
    def node(self) -> str | None:
        return self.data["nodes"][0] if self.data["nodes"] else None

    # ------------------------------------------------------------------
    # connection (one persistent connection; Tor circuits are slow to build)
    # ------------------------------------------------------------------
    async def _connect(self) -> Client:
        address = self.node
        if not address:
            raise SessionError("no node configured")
        socks = None
        if address.split(":")[0].endswith(".onion"):
            if self.tor is None:
                tor_dir = self.vault.path.resolve().parent / "unseenet-tor"
                tor = TorProcess(tor_dir, TorProcess.find_binary())
                self.status("Starting Tor ...")
                await tor.start()
                self.tor = tor
            socks = self.tor.socks_port
        self.status(f"Connecting to {address} ...")
        client = await Client.connect(address, socks)
        await client.fetch_capabilities()
        self.status(f"Connected to {address}")
        return client

    async def _call(self, fn):
        """Run ``fn(client)`` with one reconnect attempt on a broken connection."""
        async with self._lock:
            for attempt in (1, 2):
                if self._client is None:
                    self._client = await self._connect()
                try:
                    return await fn(self._client)
                except (ConnectionError, OSError, asyncio.IncompleteReadError):
                    self._client = None
                    if attempt == 2:
                        raise

    async def close(self) -> None:
        if self._client:
            try:
                await self._client.quit()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        if self.tor:
            await self.tor.stop()
            self.tor = None

    # ------------------------------------------------------------------
    # groups
    # ------------------------------------------------------------------
    def group_entry(self, group_id: str) -> dict:
        return self.data["groups"].setdefault(group_id, {"type": None, "owner": False, "keys": {}})

    async def list_groups(self, pattern: str = "*") -> list[GroupInfo]:
        lines = await self._call(lambda c: c.multiline(f"LIST NEWSGROUPS {pattern}", 215))
        out = []
        subscribed = set(self.data["subscribed"])
        for line in lines:
            gid, _, desc = line.partition("\t")
            try:
                split_group_id(gid)
            except ValueError:
                continue
            entry = self.data["groups"].get(gid, {})
            if gid in subscribed and desc and entry.get("title") != desc:
                self.group_entry(gid)["title"] = desc       # remembered for offline use
            out.append(GroupInfo(gid, desc, entry.get("type"), subscribed=gid in subscribed))
        return out

    def subscribe(self, group_id: str, on: bool = True) -> None:
        split_group_id(group_id)
        subs = self.data["subscribed"]
        if on and group_id not in subs:
            subs.append(group_id)
        elif not on and group_id in subs:
            subs.remove(group_id)
        self.save()

    async def create_group(self, name: str, gtype: str, title: str = "", description: str = "",
                           min_pow: int = DEFAULT_POW) -> str:
        owner = self.identity()
        art = make_manifest(owner, name, gtype, title=title, description=description,
                            min_pow=min_pow, pow_bits=DEFAULT_POW)
        await self._post_article(art)
        entry = {"type": gtype, "owner": True, "keys": {}}
        if gtype == "closed":
            keys = crypto.GroupKeys.generate()
            await self._post_article(make_key_update(owner, art.group, 1, keys, [], pow_bits=DEFAULT_POW))
            entry["keys"]["1"] = keys.secret.hex()
        self.data["groups"][art.group] = entry
        self.subscribe(art.group)
        return art.group

    async def invite(self, group_id: str, member_key: str) -> None:
        entry = self.data["groups"].get(group_id)
        if not entry or not entry.get("owner") or entry.get("type") != "closed":
            raise SessionError("you can only invite to closed groups you own")
        epoch = max(int(e) for e in entry["keys"])
        keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))
        art = make_key_update(self.identity(), group_id, epoch, keys,
                              [crypto.key_from_text(member_key)], grant_only=True, pow_bits=DEFAULT_POW)
        await self._post_article(art)

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------
    async def fetch_group(self, group_id: str) -> list[Message]:
        """Fetch new articles in a group; returns all cached messages, oldest first."""
        cache = self.cache.setdefault(group_id, {})
        raws = self._raw.setdefault(group_id, {})
        me = self.identity()
        entry = self.group_entry(group_id)

        async def run(c: Client):
            try:
                _, low, high = await c.group(group_id)
            except NNTPError as exc:
                raise SessionError("group not carried by this node") from exc
            start = max(low, self._high.get(group_id, 0) + 1)
            fetched = []
            for n in range(start, high + 1):
                raw = await c.article(str(n))
                if raw is not None:
                    fetched.append((n, raw))
            return fetched, high

        fetched, high = await self._call(run)
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
        if data.get("v") != 1 or data.get("node") != self.node:
            return 0
        me = self.identity()
        loaded = 0
        for gid, g in data.get("groups", {}).items():
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
            groups[gid] = {"high": self._high.get(gid, 0),
                           "articles": {str(n): base64.b64encode(raws[n]).decode() for n in keep}}
        payload = json.dumps({"v": 1, "node": self.node, "groups": groups}).encode()
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
            entry["type"] = data.get("type")
            entry["owner_key"] = data.get("owner")
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
        if "Encrypted" in art:
            msg.encrypted = True
            msg.raw = raw
            self._decrypt_into(msg, art, entry)
        else:
            msg.subject, msg.from_name, msg.body = art["Subject"], art["From"], art.body
        return msg

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
    async def _post_article(self, art: Article) -> str:
        raw = art.to_bytes()
        code, text = await self._call(lambda c: c.post(raw))
        if code != 240:
            raise SessionError(f"rejected by node: {text}")
        return art.message_id

    async def post(self, group_id: str, subject: str, body: str,
                   references: list[str] | None = None) -> str:
        author = self.identity()
        entry = self.group_entry(group_id)
        loop = asyncio.get_running_loop()
        if entry.get("type") == "closed":
            if not entry["keys"]:
                raise SessionError("you are not a member of this closed group")
            epoch = max(int(e) for e in entry["keys"])
            keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))
            # postage is CPU work; keep the UI responsive
            art = await loop.run_in_executor(None, lambda: encrypted_article(
                group_id, epoch, keys, author, from_name=self.display_name(),
                subject=subject, body=body, references=references, pow_bits=DEFAULT_POW))
        else:
            art = new_article(group_id, subject, body, from_name=self.display_name(),
                              references=references)
            await loop.run_in_executor(None, lambda: art.finalize(author, DEFAULT_POW))
        msgid = await self._post_article(art)
        marks = self.data["read"].setdefault(group_id, [])   # your own posts are read
        marks.append(msgid)
        self.save()
        return msgid


def default_vault_path() -> Path:
    return Path("unseenet.vault")
