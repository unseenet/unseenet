"""The command line: `unseenet` (a client) and `unseenet-node` (a node).

The CLI is one more client on the shared core, like the TUI and unseenet-gui: what it
does goes through ``Session`` (``unseenet.client.session``). Split by area:

    node.py       unseenet-node: node.toml, the node key, running a node
    basics.py     id-new, whoami, node-add
    groups.py     groups, group-create, group-edit, group-show, group-remove, invite
    messages.py   post, withdraw, read
    network.py    tor, bridges, gateways
    services.py   ripen, serve (for services, bots and gateways)
    kept.py       pin, pins, page-put, page-remove, pages, feed-start, site-start
    following.py  profile, follow, unfollow, following, timeline, address, open
    main.py       the `unseenet` parser and which function each command runs

This file holds what the parts share - the ``App`` around the vault and its ``Session``,
the passphrase and key derivation, ``client_command``, ``emit`` (text or ``--json``) -
and re-exports every part's names, so ``unseenet.cli`` is still the one module to
import (``cli.client_main``, ``cli.node_main``, ``cli.c_post``, ...).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import sys
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path

from .. import __version__
from ..core import crypto
from ..core.article import Article, ArticleError, new_article, validate_structure
from ..core.groups import (decrypt_article, encrypted_article, encryption_epoch, make_key_update,
                          make_manifest, open_envelope, personal_inbox_id, short_group_id,
                          split_group_id)
from ..core.store import Store
from ..core.tor import TorProcess, open_connection  # noqa: F401  (re-exported for scripts)
from ..core.vault import Vault, VaultError, seal, unseal
from ..nntp import Client, NNTPError

DEFAULT_POW = 20


def _passphrase(prompt: str, env: str) -> str:
    return os.environ.get(env) or getpass.getpass(prompt)


def _kdf() -> dict:
    # Tests may lower the Argon2id cost; never do this for real data.
    if os.environ.get("UNSEENET_INSECURE_FAST_KDF") == "1":
        return {"ops": 1, "mem": 8192 * 1024}
    return {}


class App:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.tor: TorProcess | None = None
        self._session = None

    @property
    def session(self):
        """Posting goes through Session (#287): postage, key ripening (UN-RFC 0025)
        and its header are the same code as in every client."""
        if self._session is None:
            from ..client.session import Session, SessionError
            self._session = Session(self.vault, status=lambda m: print(m, file=sys.stderr))
            try:
                self._session.act_as(getattr(self, "acting_as", None))     # -i, for this run
            except SessionError as exc:
                sys.exit(str(exc))
        return self._session

    async def bits(self, group_id: str | None, ident: crypto.Identity) -> int:
        """The postage a post by ``ident`` needs, after ripening it where the node
        asks for it (UN-RFC 0025: a new key ripens for a few minutes first)."""
        s = self.session
        name = s._identity_named_by(ident.public_key)
        if name is not None and await s.node_wants_ripening():
            await s.ensure_ripe(name)
        return await s.postage_for(group_id)

    @property
    def data(self) -> dict:
        return self.vault.data

    def identity(self, name: str | None = None) -> crypto.Identity:
        ids = self.data["identities"]
        if not ids:
            sys.exit("No identity yet. Run: unseenet id new <name>")
        name = name or self.data.get("default_identity") or next(iter(ids))
        return crypto.Identity.from_seed(bytes.fromhex(ids[name]["seed"]))

    def display_name(self, name: str | None = None) -> str:
        name = name or self.data.get("default_identity") or next(iter(self.data["identities"]))
        return self.data["identities"][name]["display"]

    @asynccontextmanager
    async def connect(self):
        nodes = self.data["nodes"]
        if not nodes:
            sys.exit("No node configured. Run: unseenet node add <address>")
        address = nodes[0]
        socks = None
        if address.split(":")[0].endswith(".onion"):
            from ..core.tor import TorError, check_socks, existing_tor
            try:
                existing = existing_tor(self.data.get("tor"))
                if existing is not None:
                    await check_socks(existing)
            except TorError as exc:
                sys.exit(f"Tor: {exc}")
            if existing is not None:
                socks = existing
            elif self.tor is None:
                from ..core.tor import bridges_for
                tor_dir = self.vault.path.parent / "unseenet-tor"
                binary = TorProcess.find_binary()
                try:
                    bridges = bridges_for(self.data.get("tor"), binary)
                except TorError as exc:
                    sys.exit(f"Tor bridges: {exc}")
                self.tor = TorProcess(tor_dir, binary, bridges=bridges)
                print("Starting Tor" + (" with bridges" if bridges else "") + " ...", file=sys.stderr)
                await self.tor.start()
            if existing is None:
                socks = self.tor.socks_port
        client = await Client.connect(address, socks)
        await client.fetch_capabilities()
        try:
            yield client
        finally:
            await client.quit()

    async def post(self, art: Article) -> None:
        from ..client.session import SessionError
        try:
            await self.session.post_article(art)
        except SessionError as exc:
            sys.exit(f"Rejected: {exc}")
        print(f"Posted {art.message_id}")


def _strip_reader_headers(raw: bytes) -> bytes:
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = [ln for ln in head.split(b"\r\n") if not ln.lower().startswith((b"path:", b"xref:"))]
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


async def client_command(args) -> None:
    """Open the vault (passphrase from ``UNSEENET_PASSPHRASE`` or the terminal) and
    run one ``unseenet`` command on it, closing the session and Tor after."""
    path = Path(args.vault)
    passphrase = _passphrase("Vault passphrase: ", "UNSEENET_PASSPHRASE")
    try:
        vault = Vault.open(path, passphrase, **_kdf())
    except VaultError as exc:
        sys.exit(str(exc))
    app = App(vault)
    app.acting_as = getattr(args, "identity", None)
    try:
        await COMMANDS[args.cmd](app, args)
    finally:
        if app._session is not None:
            await app._session.close()
        if app.tor:
            await app.tor.stop()


def _owner_of(app: App, group_id: str) -> tuple[str, crypto.Identity] | None:
    """The identity in this vault whose key owns the group ID, if any."""
    try:
        _, fp = split_group_id(group_id)
    except ValueError:
        return None
    for name, entry in app.data["identities"].items():
        ident = crypto.Identity.from_seed(bytes.fromhex(entry["seed"]))
        if crypto.fingerprint(ident.public_key) == fp:
            return name, ident
    return None


def _session(app: App, args):
    """The app's Session, acting as ``args.identity`` when given (-i)."""
    from ..client.session import SessionError
    s = app.session
    if getattr(args, "identity", None):
        try:
            s.act_as(args.identity)
        except SessionError as exc:
            sys.exit(str(exc))
    return s


def emit(args, text: str, data=None) -> None:
    """Print for people, or JSON for scripts with --json."""
    if getattr(args, "json", False):
        print(json.dumps(data if data is not None else {"text": text}, ensure_ascii=False))
    else:
        print(text)


# every shared name, for the parts (`from . import *`), underscored ones too
__all__ = [n for n in dir() if not n.startswith('__') or n == '__version__']

from .node import *  # noqa: E402,F401,F403
from .basics import *  # noqa: E402,F401,F403
from .groups import *  # noqa: E402,F401,F403
from .messages import *  # noqa: E402,F401,F403
from .network import *  # noqa: E402,F401,F403
from .services import *  # noqa: E402,F401,F403
from .kept import *  # noqa: E402,F401,F403
from .following import *  # noqa: E402,F401,F403
from .main import *  # noqa: E402,F401,F403
from . import node, basics, groups, messages, network, services, kept, following, main  # noqa: E402

# the parts' names belong to the module too (cli.c_post, cli.node_main, ...)
__all__ += [n for p in (node, basics, groups, messages, network, services, kept, following, main) for n in p.__all__]
