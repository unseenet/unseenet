"""Command-line entry points: ``unseenet-node`` and ``unseenet``.

The client keeps everything in one encrypted vault file (UN-RFC 0007), by default
``unseenet.vault`` in the current directory, so it can live on a USB stick.
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

from . import __version__
from .core import crypto
from .core.article import Article, ArticleError, new_article, validate_structure
from .core.groups import (decrypt_article, encrypted_article, encryption_epoch, make_key_update,
                          make_manifest, open_envelope, short_group_id, split_group_id)
from .core.store import Store
from .core.tor import TorProcess, open_connection  # noqa: F401  (re-exported for scripts)
from .core.vault import Vault, VaultError, seal, unseal
from .nntp import Client, NNTPError

DEFAULT_POW = 20


def _passphrase(prompt: str, env: str) -> str:
    return os.environ.get(env) or getpass.getpass(prompt)


def _kdf() -> dict:
    # Tests may lower the Argon2id cost; never do this for real data.
    if os.environ.get("UNSEENET_INSECURE_FAST_KDF") == "1":
        return {"ops": 1, "mem": 8192 * 1024}
    return {}


# ======================================================================
# Node
# ======================================================================

def load_node_config(path: Path | None):
    from .node.server import NodeConfig, PeerConfig

    if path is None:
        return NodeConfig()
    data = tomllib.loads(path.read_text())
    node = data.get("node", {})
    peers = [PeerConfig(**p) for p in data.get("peer", [])]
    for p in peers:
        if p.key:
            try:
                p.public_key()
            except crypto.CryptoError as exc:
                sys.exit(f"{path}: peer {p.name}: bad key {p.key!r} ({exc})")
        elif p.password:
            logging.getLogger("unseenet.node").warning(
                "peer %s uses a shared password; node keys are safer (UN-RFC 0016)", p.name)
    return NodeConfig(name=node.get("name", "unseenet"),
                      max_size=node.get("max_size", 65536),
                      min_pow=node.get("min_pow", 18),
                      retention_days=node.get("retention_days", 90),
                      new_groups=node.get("new_groups", "accept"),
                      trusted_owners=node.get("trusted_owners", []),
                      # only configured peers may push, unless the operator says otherwise
                      require_peer_auth=node.get("require_peer_auth", True),
                      pull_interval=float(node.get("pull_interval", 3600)),
                      operator=data.get("operator", {}),
                      peers=peers)


def load_node_key(data: Path, passphrase: str) -> crypto.Identity:
    """The node key (UN-RFC 0016), created on first start, sealed like the onion key."""
    key_file = data / "node_key.vault"
    if key_file.exists():
        return crypto.Identity.from_seed(unseal(key_file.read_bytes(), passphrase))
    key = crypto.Identity.generate()
    key_file.write_bytes(seal(key.seed, passphrase, **_kdf()))
    key_file.chmod(0o600)
    return key


async def run_node(args) -> None:
    from .node.peering import Feeder
    from .node.server import Node

    data = Path(args.data)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = load_node_config(Path(args.config) if args.config else None)
    passphrase = _passphrase("Node passphrase: ", "UNSEENET_NODE_PASSPHRASE")
    node_key = load_node_key(data, passphrase)
    print(f"Node key: {node_key.key_text}  (give it to the operators you peer with)")
    node = Node(Store(data / "articles.sqlite"), config, key=node_key)
    host, port = args.listen.rsplit(":", 1)
    server = await node.serve(host, int(port))
    print(f"ONNTP listening on {args.listen}")

    tor = None
    socks_port = None
    if not args.no_tor:
        tor = TorProcess(data / "tor", TorProcess.find_binary(args.tor))
        print("Starting Tor ...")
        await tor.start()
        socks_port = tor.socks_port
        key_file = data / "onion_key.vault"
        key = unseal(key_file.read_bytes(), passphrase).decode() if key_file.exists() else None
        onion, new_key = await tor.control.add_onion(key, 119, f"{host}:{port}")
        if new_key:
            key_file.write_bytes(seal(new_key.encode(), passphrase, **_kdf()))
        print(f"Node is reachable at {onion}")

    feeders = [asyncio.create_task(Feeder(node, peer, socks_port).run_forever())
               for peer in config.peers]
    from .node.pulling import Puller
    feeders += [asyncio.create_task(Puller(node, peer, socks_port).run_forever())
                for peer in config.peers if peer.pull]

    async def expire_loop():
        while True:
            node.store.expire(config.retention_days)
            await asyncio.sleep(3600)

    try:
        async with server:
            await asyncio.gather(server.serve_forever(), expire_loop(), *feeders)
    finally:
        if tor:
            await tor.stop()


def node_main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="unseenet-node", description="Run an Unseenet node.")
    p.add_argument("--data", default="node-data", help="data directory (put it on an encrypted disk)")
    p.add_argument("--config", help="TOML config file")
    p.add_argument("--listen", default="127.0.0.1:1119", help="local ONNTP address")
    p.add_argument("--tor", help="path to the tor binary")
    p.add_argument("--no-tor", action="store_true", help="local only, for development")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"unseenet-node {__version__}")
    p.add_argument("--drop-group", metavar="GROUP_ID",
                   help="stop carrying a group on this node, delete its posts, and exit")
    p.add_argument("--show-key", action="store_true",
                   help="print this node's key (for your peers' node.toml) and exit")
    p.add_argument("--sign", metavar="CHALLENGE",
                   help="sign a challenge with this node's key, to prove you run it "
                        "(e.g. when asking to be listed), and exit")
    p.add_argument("--undrop-group", metavar="GROUP_ID",
                   help="allow a group dropped with --drop-group again, and exit")
    args = p.parse_args(argv)
    if args.sign:
        key_file = Path(args.data) / "node_key.vault"
        if not key_file.exists():
            sys.exit(f"no node key in {args.data}; is --data the node's data directory?")
        key = load_node_key(Path(args.data), _passphrase("Node passphrase: ", "UNSEENET_NODE_PASSPHRASE"))
        print(key.sign_text(crypto.PURPOSE_NODE_CLAIM, args.sign.strip().encode()))
        return
    if args.show_key:
        data = Path(args.data)
        data.mkdir(parents=True, exist_ok=True, mode=0o700)
        print(load_node_key(data, _passphrase("Node passphrase: ", "UNSEENET_NODE_PASSPHRASE")).key_text)
        return
    if args.drop_group or args.undrop_group:
        from .node.server import Node
        node = Node(Store(Path(args.data) / "articles.sqlite"))
        if args.drop_group:
            n = node.drop_group(args.drop_group)
            print(f"Dropped {args.drop_group} from this node ({n} posts deleted). "
                  "Peers are not told; it is your node's decision only.")
        else:
            ok = node.store.lift_tombstone(args.undrop_group)
            print(f"{args.undrop_group} may be carried again." if ok else
                  "Not dropped by this node (groups removed by their owner cannot be restored).")
        return
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    try:
        asyncio.run(run_node(args))
    except KeyboardInterrupt:
        pass


# ======================================================================
# Client
# ======================================================================

class App:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.tor: TorProcess | None = None

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
            if self.tor is None:
                from .core.tor import TorError, bridges_for
                tor_dir = self.vault.path.parent / "unseenet-tor"
                binary = TorProcess.find_binary()
                try:
                    bridges = bridges_for(self.data.get("tor"), binary)
                except TorError as exc:
                    sys.exit(f"Tor bridges: {exc}")
                self.tor = TorProcess(tor_dir, binary, bridges=bridges)
                print("Starting Tor" + (" with bridges" if bridges else "") + " ...", file=sys.stderr)
                await self.tor.start()
            socks = self.tor.socks_port
        client = await Client.connect(address, socks)
        await client.fetch_capabilities()
        try:
            yield client
        finally:
            await client.quit()

    async def post(self, art: Article) -> None:
        async with self.connect() as c:
            code, text = await c.post(art.to_bytes())
        if code != 240:
            sys.exit(f"Rejected: {code} {text}")
        print(f"Posted {art.message_id}")


def _strip_reader_headers(raw: bytes) -> bytes:
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = [ln for ln in head.split(b"\r\n") if not ln.lower().startswith((b"path:", b"xref:"))]
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


async def client_command(args) -> None:
    path = Path(args.vault)
    passphrase = _passphrase("Vault passphrase: ", "UNSEENET_PASSPHRASE")
    try:
        vault = Vault.open(path, passphrase, **_kdf())
    except VaultError as exc:
        sys.exit(str(exc))
    app = App(vault)
    try:
        await COMMANDS[args.cmd](app, args)
    finally:
        if app.tor:
            await app.tor.stop()


async def c_id_new(app: App, args) -> None:
    ident = crypto.Identity.generate()
    app.data["identities"][args.name] = {"seed": ident.seed.hex(), "display": args.display or args.name}
    app.data.setdefault("default_identity", args.name)
    app.vault.save()
    print(f"{args.name}: {ident.key_text}")


async def c_whoami(app: App, args) -> None:
    for name, entry in app.data["identities"].items():
        ident = crypto.Identity.from_seed(bytes.fromhex(entry["seed"]))
        mark = "*" if name == app.data.get("default_identity") else " "
        print(f"{mark} {name:12} {entry['display']:20} {ident.key_text}")


async def c_node_add(app: App, args) -> None:
    if args.address not in app.data["nodes"]:
        app.data["nodes"].append(args.address)
        app.vault.save()
    print("Nodes:", ", ".join(app.data["nodes"]))


async def c_groups(app: App, args) -> None:
    async with app.connect() as c:
        lines = await c.multiline(f"LIST NEWSGROUPS {args.pattern}", 215)
    for line in lines:
        gid, _, desc = line.partition("\t")
        print(f"{short_group_id(gid):32} {desc}   ({gid})")


async def c_group_create(app: App, args) -> None:
    owner = app.identity(args.identity)
    art = make_manifest(owner, args.name, args.type, title=args.title or "",
                        description=args.description or "", min_pow=args.min_pow,
                        local=args.local, retention_days=30 if args.type == "inbox" else 90,
                        pow_bits=DEFAULT_POW)
    await app.post(art)
    group_id = art.group
    entry = {"type": args.type, "owner": True, "keys": {}}
    if args.type == "closed":
        keys = crypto.GroupKeys.generate()
        await app.post(make_key_update(owner, group_id, 1, keys, [], pow_bits=DEFAULT_POW))
        entry["keys"]["1"] = keys.secret.hex()
    app.data["groups"][group_id] = entry
    app.vault.save()
    print(f"Created {group_id}")


async def c_invite(app: App, args) -> None:
    owner = app.identity(args.identity)
    entry = app.data["groups"].get(args.group)
    if not entry or not entry.get("owner") or entry["type"] != "closed":
        sys.exit("You can only invite to closed groups you own.")
    epoch = max(int(e) for e in entry["keys"])
    keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))
    member = crypto.key_from_text(args.key)
    await app.post(make_key_update(owner, args.group, epoch, keys, [member],
                                   grant_only=True, pow_bits=DEFAULT_POW))
    print(f"Invite sent. Share this with the new member:\n  unseenet:join?g={args.group}"
          f"&n={app.data['nodes'][0]}")


async def c_post(app: App, args) -> None:
    author = app.identity(args.identity)
    body = sys.stdin.read() if args.body is None else args.body
    entry = app.data["groups"].get(args.group, {})
    if entry.get("type") == "closed":
        epoch = max(int(e) for e in entry["keys"])
        keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))
        art = encrypted_article(args.group, epoch, keys, author, from_name=app.display_name(args.identity),
                                subject=args.subject, body=body, pow_bits=DEFAULT_POW)
    else:
        art = new_article(args.group, args.subject, body, from_name=app.display_name(args.identity))
        art.finalize(author, DEFAULT_POW)
    await app.post(art)


async def c_read(app: App, args) -> None:
    split_group_id(args.group)
    me = app.identity(args.identity)
    entry = app.data["groups"].setdefault(args.group, {"type": None, "owner": False, "keys": {}})
    async with app.connect() as c:
        try:
            count, low, high = await c.group(args.group)
        except NNTPError:
            sys.exit("Group not carried by this node.")
        for n in range(low, high + 1):
            raw = await c.article(str(n))
            if raw is None:
                continue
            raw = _strip_reader_headers(raw)
            try:
                art = Article.from_bytes(raw)
                validate_structure(art, raw_size=len(raw))
            except ArticleError as err:
                print(f"[{n}] INVALID: {err}")
                continue
            ctl = art.control
            if ctl and ctl[0] == "manifest":
                entry["type"] = entry["type"] or json.loads(art.body)["type"]
                continue
            if ctl and ctl[0] in ("key-update", "key-grant"):
                opened = open_envelope(art, me)
                if opened:
                    epoch, keys = opened
                    entry["keys"][str(epoch)] = keys.secret.hex()
                continue
            if ctl:
                continue
            author = art["Author-Key"]
            short = crypto.fingerprint(art.author_key)[:4]
            if "Encrypted" in art:
                key_hex = entry["keys"].get(str(encryption_epoch(art)))
                if not key_hex:
                    print(f"[{n}] (encrypted, you are not a member of this epoch)")
                    continue
                inner = decrypt_article(art, crypto.GroupKeys(bytes.fromhex(key_hex)))
                frm, subj, body = inner["From"], inner["Subject"], inner.body
            else:
                frm, subj, body = art["From"], art["Subject"], art.body
            print(f"\n[{n}] {subj}\n    From: {frm} ({short}) {author[:20]}...\n    Date: {art['Date']}\n")
            print("    " + body.rstrip("\n").replace("\n", "\n    "))
    app.vault.save()


async def c_bridges(app: App, args) -> None:
    if args.mode:
        lines = [ln for ln in args.line or []]
        if args.mode == "custom" and not lines:
            sys.exit("custom bridges need at least one --line \"obfs4 1.2.3.4:443 ...\"")
        app.data["tor"] = {"mode": args.mode, "custom": lines}
        app.vault.save()
    setting = app.data.get("tor") or {"mode": "off"}
    print(f"Bridges: {setting['mode']}")
    for line in setting.get("custom", []) if setting["mode"] == "custom" else []:
        print(f"  {line}")


COMMANDS = {
    "id-new": c_id_new, "whoami": c_whoami, "node-add": c_node_add, "groups": c_groups,
    "group-create": c_group_create, "invite": c_invite, "post": c_post, "read": c_read,
    "bridges": c_bridges,
}


def client_main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="unseenet", description="Unseenet client.")
    from .portable import default_vault_path
    p.add_argument("--vault", default=str(default_vault_path()), help="encrypted vault file")
    p.add_argument("--identity", "-i", help="identity to use (default: first)")
    p.add_argument("--version", action="version", version=f"unseenet {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("id-new", help="create a new identity")
    s.add_argument("name")
    s.add_argument("--display", help="display name shown in From")
    sub.add_parser("whoami", help="list identities")
    s = sub.add_parser("node-add", help="add a node address (xyz.onion or host:port)")
    s.add_argument("address")
    s = sub.add_parser("groups", help="list groups on the node")
    s.add_argument("pattern", nargs="?", default="*")
    s = sub.add_parser("group-create", help="create a group you own")
    s.add_argument("name")
    s.add_argument("--type", choices=["open", "moderated", "channel", "closed", "inbox"], default="open")
    s.add_argument("--local", action="store_true", help="never replicated to other nodes (UN-RFC 0009)")
    s.add_argument("--title")
    s.add_argument("--description")
    s.add_argument("--min-pow", type=int, default=20)
    s = sub.add_parser("invite", help="give a key access to a closed group you own")
    s.add_argument("group")
    s.add_argument("key", help="the member's ed25519:... key")
    s = sub.add_parser("post", help="post to a group (body from --body or stdin)")
    s.add_argument("group")
    s.add_argument("--subject", "-s", required=True)
    s.add_argument("--body")
    s = sub.add_parser("read", help="read a group")
    s.add_argument("group")
    s = sub.add_parser("bridges", help="show or set Tor bridges, for networks that block Tor")
    s.add_argument("mode", nargs="?", choices=["off", "obfs4", "snowflake", "custom"])
    s.add_argument("--line", action="append", help="a bridge line (custom; repeat for more)")

    args = p.parse_args(argv)
    asyncio.run(client_command(args))
