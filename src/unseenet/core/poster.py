"""Posting without a person at the keyboard: for bots, gateways and scripts.

    from unseenet.core.poster import Poster, load_key

    async with Poster(load_key(), from_name="Daily news") as p:
        result = await p.post("alt.news@<fingerprint>", "Today", "Something happened.\\n")
        print(result.message_id, result.accepted)

A :class:`Poster` never prompts. It takes a key (see :func:`load_key`), the
nodes to post to (the built-in list of known nodes by default, UN-RFC 0010),
and a Tor: its own, one that is already running, or none for nodes on the
local network. It builds, signs and adds postage (UN-RFC 0006), says what
kind of message it is (UN-RFC 0028), posts the same article to every node
that answers, adds postage if a node asks for more, and tries again later
when a node says "later" - e.g. a comment that arrived before its thread
(UN-RFC 0030 section 4.1).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import crypto
from .article import Article, new_article
from .groups import KIND_CHAT, MESSAGE_KINDS
from .tor import TorProcess, open_connection

MAX_POW = 28
DEFAULT_NODE_POW = 20
SEED_ENV = "UNSEENET_SEED"                    # the key, as a hex seed
VAULT_PASSPHRASE_ENV = "UNSEENET_VAULT_PASSPHRASE"
TOR_SOCKS_ENV = "UNSEENET_TOR_SOCKS"          # port of a Tor that is already running


class PosterError(RuntimeError):
    pass


def load_key(*, key_file: str | Path | None = None, vault: str | Path | None = None,
             identity: str | None = None, seed_env: str = SEED_ENV,
             passphrase_env: str = VAULT_PASSPHRASE_ENV) -> crypto.Identity:
    """The key to post with, from the first of these that is given:

    - ``key_file``: a file holding the 32-byte seed in hex;
    - ``vault``: an Unseenet vault, unlocked with the passphrase in the
      environment variable ``passphrase_env``; ``identity`` picks one of its
      identities (the vault's default otherwise);
    - the environment variable ``seed_env`` holding the seed in hex.

    Never asks for anything; raises PosterError if no key can be found.
    """
    try:
        if key_file is not None:
            return crypto.Identity.from_seed(bytes.fromhex(Path(key_file).read_text().strip()))
        if vault is not None:
            from .vault import Vault
            passphrase = os.environ.get(passphrase_env)
            if not passphrase:
                raise PosterError(f"set {passphrase_env} to unlock {vault}")
            data = Vault.open(Path(vault), passphrase).data
            ids = data.get("identities") or {}
            name = identity or data.get("default_identity") or next(iter(ids), None)
            if name not in ids:
                raise PosterError(f"no identity {name!r} in {vault}")
            return crypto.Identity.from_seed(bytes.fromhex(ids[name]["seed"]))
        seed = os.environ.get(seed_env, "").strip()
        if seed:
            return crypto.Identity.from_seed(bytes.fromhex(seed))
    except (OSError, ValueError, KeyError) as exc:
        raise PosterError(f"cannot load the key: {exc}") from exc
    raise PosterError(f"no key: give a key file or a vault, or set {seed_env}")


def known_node_addresses() -> list[str]:
    """The addresses of the built-in list of known nodes (UN-RFC 0010)."""
    from ..known_nodes import builtin_list
    return [n.address for n in builtin_list()[1]]


@dataclass
class PostResult:
    message_id: str
    accepted: list[str] = field(default_factory=list)          # nodes that have it now
    refused: dict[str, str] = field(default_factory=dict)      # node -> the node's reason
    unreachable: dict[str, str] = field(default_factory=dict)  # node -> what went wrong

    @property
    def ok(self) -> bool:
        return bool(self.accepted)


class Poster:
    """Post to Unseenet from a program. Use as ``async with Poster(key) as p``.

    ``nodes``: addresses (``xyz.onion`` or ``host:port``); the known-node list
    by default. ``tor``: ``"auto"`` (a running Tor if ``UNSEENET_TOR_SOCKS``
    names its SOCKS port, else our own if any node is an onion, else none),
    ``"own"``, ``"none"``, or the SOCKS port of a running Tor as an int.
    """

    def __init__(self, key: crypto.Identity, nodes: list[str] | None = None, *,
                 from_name: str = "Unseenet bot", tor: str | int = "auto", tor_binary: str | None = None,
                 connect_timeout: float = 120.0, later_attempts: int = 3,
                 later_pause: float = 60.0, log=None):
        self.key = key
        self.nodes = list(nodes) if nodes is not None else known_node_addresses()
        self.from_name = from_name
        self.tor, self.tor_binary = tor, tor_binary
        self.connect_timeout = connect_timeout
        self.later_attempts, self.later_pause = later_attempts, later_pause
        self.log = log or (lambda msg: None)
        self.socks_port: int | None = None
        self._tor: TorProcess | None = None
        self._tmp: tempfile.TemporaryDirectory | None = None

    # --- Tor ---
    async def __aenter__(self) -> "Poster":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    async def start(self) -> None:
        mode = self.tor
        if isinstance(mode, int):
            self.socks_port = mode
            return
        if mode == "auto":
            env = os.environ.get(TOR_SOCKS_ENV, "").strip()
            if env.isdigit():
                self.socks_port = int(env)
                return
            mode = "own" if any(_is_onion(a) for a in self.nodes) else "none"
        if mode == "none":
            return
        if mode != "own":
            raise PosterError(f"unknown tor setting {self.tor!r}")
        self._tmp = tempfile.TemporaryDirectory(prefix="unseenet-poster-")
        self._tor = TorProcess(Path(self._tmp.name), TorProcess.find_binary(self.tor_binary))
        self.log("Starting Tor ...")
        await self._tor.start(timeout=180)
        self.socks_port = self._tor.socks_port

    async def stop(self) -> None:
        if self._tor is not None:
            await self._tor.stop()
            self._tor = None
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None

    # --- posting ---
    def build(self, group: str, subject: str, body: str, *, kind: str = "post",
              references: list[str] | None = None,
              content_type: str = "text/plain; charset=utf-8",
              extra: list[tuple[str, str]] | None = None) -> Article:
        """An unsigned article; :meth:`post_article` signs it with postage."""
        if kind not in MESSAGE_KINDS:
            raise ValueError(f"kind must be one of {MESSAGE_KINDS}")
        if kind != KIND_CHAT and not subject.strip():
            raise ValueError("a post needs a subject")
        if not body.endswith("\n"):
            body += "\n"
        headers = [("Content-Type", content_type), ("Message-Kind", kind), *(extra or [])]
        return new_article(group, "" if kind == KIND_CHAT else subject, body,
                           from_name=self.from_name or "Unseenet bot", references=references,
                           extra=headers)

    async def post(self, group: str, subject: str, body: str, **kw) -> PostResult:
        """Post a message to every node; see :meth:`build` for the arguments."""
        return await self.post_article(self.build(group, subject, body, **kw))

    async def post_article(self, art: Article, bits: int = 0) -> PostResult:
        """Sign ``art`` and post it to every node. Signing is deterministic, so
        adding postage for a node that asks for more keeps the Message-ID."""
        art.finalize(self.key, bits)
        result = PostResult(art.message_id)
        for address in self.nodes:
            bits = await self._post_to(address, art, bits, result)
        return result

    async def _post_to(self, address: str, art: Article, bits: int, result: PostResult) -> int:
        loop = asyncio.get_running_loop()
        for attempt in range(1, self.later_attempts + 1):
            try:
                client = await self._connect(address)
            except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
                result.unreachable[address] = str(exc) or type(exc).__name__
                self.log(f"{address}: not reached ({exc})")
                return bits
            try:
                value = client.capability("UNSEENET-MINPOW")
                need = int(value) if value and value.strip().isdigit() else DEFAULT_NODE_POW
                for _ in range(2):                    # once more if it asks for more postage
                    if need > bits:
                        bits = min(need, MAX_POW)
                        await loop.run_in_executor(None, art.finalize, self.key, bits)
                    code, text = await client.post(art.to_bytes())
                    need = _needed_bits(text) if code == 441 else 0
                    if not need or need <= bits or need > MAX_POW:
                        break
            except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
                result.unreachable[address] = str(exc) or type(exc).__name__
                return bits
            finally:
                await _quit(client)
            if code == 240 or text.startswith("duplicate"):
                result.accepted.append(address)
                self.log(f"{address}: posted")
                return bits
            if text.startswith("later") and attempt < self.later_attempts:
                self.log(f"{address}: later ({text}); trying again")
                await asyncio.sleep(self.later_pause * attempt)
                continue
            result.refused[address] = f"{code} {text}"
            self.log(f"{address}: refused {code} {text}")
            return bits
        return bits

    async def _connect(self, address: str):
        from ..nntp import Client
        reader, writer = await asyncio.wait_for(open_connection(address, self.socks_port),
                                                self.connect_timeout)
        client = Client(reader, writer)
        code, text = await client._response()
        if code not in (200, 201):
            writer.close()
            raise ConnectionError(f"{code} {text}")
        await client.fetch_capabilities()
        return client

    # --- reading back ---
    async def article(self, message_id: str) -> Article | None:
        """The article from the first node that has it (to check that a post arrived)."""
        for address in self.nodes:
            try:
                client = await self._connect(address)
            except (OSError, ConnectionError, asyncio.TimeoutError, ValueError):
                continue
            try:
                raw = await client.article(message_id)
            except (OSError, ConnectionError, ValueError):
                raw = None
            finally:
                await _quit(client)
            if raw is not None:
                from ..nntp import strip_reader_headers
                return Article.from_bytes(strip_reader_headers(raw))
        return None

    async def recent_threads(self, group: str, limit: int = 50) -> list[tuple[str, str]]:
        """(Message-ID, subject) of the newest thread roots in a group, newest first,
        from the first node that answers - e.g. for a bot to skip what it posted."""
        from ..nntp import NNTPError
        for address in self.nodes:
            try:
                client = await self._connect(address)
            except (OSError, ConnectionError, asyncio.TimeoutError, ValueError):
                continue
            try:
                _, low, high = await client.group(group)
                span = f"{max(low, high - 4 * limit)}-{high}"
                lines = await client.multiline(f"OVER {span}", 224)
                control = {ln.split(" ", 1)[0] for ln in await client.multiline(f"HDR Control {span}", 225)
                           if len(ln.split(" ", 1)) > 1 and ln.split(" ", 1)[1].strip()}
            except (NNTPError, OSError, ConnectionError, ValueError):
                continue
            finally:
                await _quit(client)
            roots = []
            for line in lines:      # number, subject, from, date, message-id, references, ...
                f = line.split("\t")
                if len(f) > 5 and not f[5].strip() and f[0] not in control:  # not manifests
                    roots.append((f[4], f[1]))
            return roots[::-1][:limit]
        return []


def _is_onion(address: str) -> bool:
    return address.rpartition(":")[0].endswith(".onion") or address.endswith(".onion")


def _needed_bits(text: str) -> int:
    """N from a node's "postage: need N bits"."""
    import re
    m = re.search(r"need (\d+) bits", text)
    return int(m.group(1)) if m else 0


async def _quit(client) -> None:
    try:
        await asyncio.wait_for(client.quit(), 10)
    except (OSError, ConnectionError, asyncio.TimeoutError, ValueError):
        client.writer.close()
