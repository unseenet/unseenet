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
                          make_manifest, open_envelope, personal_inbox_id, short_group_id,
                          split_group_id)
from .core.store import Store
from .core.tor import TorProcess, open_connection  # noqa: F401  (re-exported for scripts)
from .core.vault import Vault, VaultError, seal, unseal
from .nntp import Client, NNTPError

DEFAULT_POW = 20


def _min_ripe(path, value):
    """node.toml ``min_ripe``: a level 0-4 or "-" for none (UN-RFC 0025 section 5)."""
    from .core import ripening
    try:
        return ripening.parse_min(str(value))
    except (ValueError, ripening.RipeningError):
        sys.exit(f"{path}: min_ripe must be a level 0-4 or \"-\", not {value!r}")


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
                      min_ripe=_min_ripe(path, node.get("min_ripe", 0)),
                      retention_days=node.get("retention_days", 90),
                      new_groups=node.get("new_groups", "accept"),
                      trusted_owners=node.get("trusted_owners", []),
                      # only configured peers may push, unless the operator says otherwise
                      require_peer_auth=node.get("require_peer_auth", True),
                      pull_interval=float(node.get("pull_interval", 3600)),
                      honour_blocks=bool(node.get("honour_blocks", False)),
                      profiles=str(node.get("profiles", "accept")),
                      avatars=str(node.get("avatars", "refuse")),
                      sites=str(node.get("sites", "refuse")),
                      excludes=str(node.get("excludes", "")),
                      operator=data.get("operator", {}),
                      max_clients=_max_clients(path, data.get("limits", {}).get("max_clients", "auto")),
                      blobs=_blobs_config(path, data.get("blobs", {})),
                      peers=peers)


def _blobs_config(path: Path, b: dict) -> dict | None:
    """[blobs] (UN-RFC 0027 section 8): off unless ``enabled = true``. The
    recommended first setting is 1 MiB, 30 days, encrypted off, for every group."""
    from .core import blobs as bl
    if not b.get("enabled", False):
        return None
    size = b.get("max_size", bl.MIN_NODE_BLOB)
    if isinstance(size, bool) or not isinstance(size, int) or not bl.MIN_NODE_BLOB <= size <= bl.MAX_BLOB:
        sys.exit(f"{path}: [blobs] max_size must be {bl.MIN_NODE_BLOB} to {bl.MAX_BLOB} octets")
    days = b.get("retention_days", 30)
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        sys.exit(f"{path}: [blobs] retention_days must be a positive number")
    out = {"max_size": size, "retention_days": days, "encrypted": bool(b.get("encrypted", False)),
           "groups": str(b.get("groups", "*")),
           # section 7.3: refusal lists only from keys the operator names; none by default
           "refusal_keys": [str(k) for k in b.get("refusal_keys", [])],
           "refusal_groups": str(b.get("refusal_groups", "*"))}
    for name, default in (("daily_per_key", bl.DAILY_PER_KEY), ("daily_per_group", bl.DAILY_PER_GROUP)):
        value = b.get(name, default)                    # section 8.1
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            sys.exit(f"{path}: [blobs] {name} must be a number of octets")
        out[name] = value
    for k in out["refusal_keys"]:
        try:
            crypto.key_from_text(k)
        except crypto.CryptoError:
            sys.exit(f"{path}: [blobs] refusal_keys: bad key {k!r}")
    return out


def _max_clients(path: Path, value):
    """[limits] max_clients: "auto" or a number of open client connections (#296)."""
    if value == "auto" or (isinstance(value, int) and not isinstance(value, bool) and value > 0):
        return value
    sys.exit(f"{path}: [limits] max_clients must be \"auto\" or a positive number")


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
    logging.getLogger("unseenet").addHandler(node.stats.log)   # the monitor's log lines
    host, port = args.listen.rsplit(":", 1)
    server = await node.serve(host, int(port))
    print(f"ONNTP listening on {args.listen}")
    monitor = None
    if args.monitor != "off":
        from .node.stats import serve as serve_stats
        where = args.monitor or str(data / "monitor.sock")
        try:
            monitor = await serve_stats(node.stats, node, where, data)
            print(f"Stats for unseenet-monitor on {where}")
            node.stats.note(f"unseenet-node {__version__} started; stats on {where}")
        except (OSError, ValueError, NotImplementedError) as exc:
            print(f"No stats interface ({exc})", file=sys.stderr)

    tor = None
    socks_port = None
    if not args.no_tor:
        tor = TorProcess(data / "tor", TorProcess.find_binary(args.tor))
        print("Starting Tor ...")
        await tor.start()
        node.stats.tor = tor
        socks_port = tor.socks_port
        key_file = data / "onion_key.vault"
        key = unseal(key_file.read_bytes(), passphrase).decode() if key_file.exists() else None
        onion, new_key = await tor.control.add_onion(key, 119, f"{host}:{port}")
        if new_key:
            key_file.write_bytes(seal(new_key.encode(), passphrase, **_kdf()))
            key_file.chmod(0o600)
        node.stats.onion = onion
        print(f"Node is reachable at {onion}")
        node.stats.note(f"Tor is running; the node is reachable at {onion}")

    feeders = [asyncio.create_task(Feeder(node, peer, socks_port).run_forever())
               for peer in config.peers]
    from .node.pulling import Puller
    feeders += [asyncio.create_task(Puller(node, peer, socks_port).run_forever())
                for peer in config.peers if peer.pull]
    if config.blobs is not None:               # blobs follow their article (UN-RFC 0027, 6.3)
        from .node.blobfetch import BlobFollower
        feeders.append(asyncio.create_task(BlobFollower(node, socks_port).run_forever()))

    async def expire_loop():
        while True:
            node.store.expire(config.retention_days)
            node.sweep_blobs()                 # UN-RFC 0027 section 7: what nothing keeps
            await asyncio.sleep(3600)

    try:
        async with server:
            await asyncio.gather(server.serve_forever(), expire_loop(), *feeders)
    finally:
        if monitor is not None:
            monitor.close()
        if tor:
            await tor.stop()


def node_main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="unseenet-node", description="Run an Unseenet node.")
    p.add_argument("--data", default="node-data", help="data directory (put it on an encrypted disk)")
    p.add_argument("--config", help="TOML config file")
    p.add_argument("--listen", default="127.0.0.1:1119", help="local ONNTP address")
    p.add_argument("--tor", help="path to the tor binary")
    p.add_argument("--no-tor", action="store_true", help="local only, for development")
    p.add_argument("--monitor", metavar="SOCKET",
                   help="where unseenet-monitor reads this node's stats: a Unix socket "
                        "(default: monitor.sock in --data), 127.0.0.1:PORT, or 'off'. "
                        "Only ever on this computer, never over Tor")
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
    p.add_argument("--refuse-blob", metavar="BLOB_ID",
                   help="refuse a blob: delete it and never stage, fetch or serve it again "
                        "(UN-RFC 0027 section 7.3), and exit; a running node follows at once")
    p.add_argument("--reason", default="", help="why, with --refuse-blob (kept on this node only)")
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
    if args.refuse_blob:
        from .core import blobs as bl
        if not bl.valid_id(args.refuse_blob):
            sys.exit(f"not a blob ID: {args.refuse_blob}")
        store = Store(Path(args.data) / "articles.sqlite")
        store.refuse_blob(args.refuse_blob, args.reason)
        bl.BlobStore(Path(args.data) / "blobs").delete(args.refuse_blob)
        store.forget_blob(args.refuse_blob)
        print(f"Refused {args.refuse_blob}: deleted, and not staged, fetched or served again. "
              "Articles that reference it stay.")
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
        self._session = None

    @property
    def session(self):
        """Posting goes through Session (#287): postage, key ripening (UN-RFC 0025)
        and its header are the same code as in every client."""
        if self._session is None:
            from .client.session import Session, SessionError
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
            from .core.tor import TorError, check_socks, existing_tor
            try:
                existing = existing_tor(self.data.get("tor"))
                if existing is not None:
                    await check_socks(existing)
            except TorError as exc:
                sys.exit(f"Tor: {exc}")
            if existing is not None:
                socks = existing
            elif self.tor is None:
                from .core.tor import bridges_for
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
        from .client.session import SessionError
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


async def c_groups(app: App, args) -> None:
    async with app.connect() as c:
        lines = await c.multiline(f"LIST NEWSGROUPS {args.pattern}", 215)
    for line in lines:
        gid, _, desc = line.partition("\t")
        if args.mine:
            owner = _owner_of(app, gid)
            if owner is None:
                continue
            desc = f"{desc}   [owned by {owner[0]}]"
        print(f"{short_group_id(gid):32} {desc}   ({gid})")


async def c_group_remove(app: App, args) -> None:
    """UN-RFC 0013: remove groups you own from the whole network. Final."""
    plan = []
    for gid in args.group:
        try:
            split_group_id(gid)
        except ValueError:
            sys.exit(f"{gid}: give the full group ID (name@fingerprint), "
                     "see 'unseenet groups --mine'")
        owner = _owner_of(app, gid)
        if owner is None:
            sys.exit(f"{gid}: none of the identities in this vault owns it")
        if gid == personal_inbox_id(owner[1].public_key):
            sys.exit(f"{gid}: a personal inbox cannot be removed")
        plan.append((gid, *owner))

    print("Removing a group is final: every node deletes it and its posts, and the")
    print("group ID can never be used again, not even by you. Saved copies remain.")
    for gid, name, _ in plan:
        print(f"  {gid}   (owner: {name})")
    if not args.yes:
        if not sys.stdin.isatty():
            sys.exit("Not removed. Add --yes to confirm when not running interactively.")
        if input("Type 'remove' to go ahead: ").strip() != "remove":
            sys.exit("Not removed.")

    reason = (args.reason or "Removed by its owner.").rstrip("\n") + "\n"
    for gid, _, ident in plan:
        art = new_article(gid, None, reason, extra=[("Control", "rmgroup")])
        art.finalize(ident, await app.bits(None, ident))
        await app.post(art)
        if gid in app.data.get("subscribed", []):
            app.data["subscribed"].remove(gid)
        app.data["groups"].pop(gid, None)
        app.vault.save()
        print(f"Removed {gid}")


async def c_withdraw(app: App, args) -> None:
    """UN-RFC 0004 section 7: withdraw posts - your own, or any in a group you own or
    moderate; ``--all`` every post in such a group (a demo's reset)."""
    from .client.session import SessionError
    ids = [args.message_id] if isinstance(args.message_id, str) else list(args.message_id or [])
    every = getattr(args, "all", False)
    if not ids and not every:
        sys.exit("Give Message-IDs, or --all.")
    if not getattr(args, "json", False):
        print("Withdrawing is best effort: nodes delete the post and clients stop showing")
        print("it, but people who read it may have kept a copy.")
    if not args.yes:
        if not sys.stdin.isatty():
            sys.exit("Not withdrawn. Add --yes to confirm when not running interactively.")
        what = "every post" if every else ", ".join(ids)
        if input(f"Withdraw {what} from {args.group}? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Not withdrawn.")
    s = _session(app, args)
    reason = getattr(args, "reason", None) or ""
    try:
        if every:
            done = await s.withdraw_all(args.group, keep=set(getattr(args, "keep", None) or []),
                                        reason=reason)
        else:
            done = []
            for mid in ids:
                await s.withdraw(args.group, mid, reason)
                done.append(mid if mid.startswith("<") else f"<{mid}>")
    except SessionError as exc:
        sys.exit(f"Not withdrawn: {exc}")
    emit(args, f"Withdrawn {len(done)}: " + " ".join(done), {"withdrawn": done})


def _session(app: App, args):
    """The app's Session, acting as ``args.identity`` when given (-i)."""
    from .client.session import SessionError
    s = app.session
    if getattr(args, "identity", None):
        try:
            s.act_as(args.identity)
        except SessionError as exc:
            sys.exit(str(exc))
    return s


def _group_fields(args) -> tuple[dict, dict]:
    """(Session.update_group/create_group fields, extra manifest fields) from options."""
    fields, extra = {}, {}
    for opt, key in (("title", "title"), ("description", "description"), ("min_pow", "min_pow"),
                     ("retention_days", "retention_days"), ("view", "view"),
                     ("comments", "comments"), ("comment_days", "comment_days")):
        value = getattr(args, opt, None)
        if value is not None:
            fields[key] = value
    if getattr(args, "kinds", None):
        fields["kinds"] = [k.strip() for k in args.kinds.split(",") if k.strip()]
    if getattr(args, "rules", None):
        text = sys.stdin.read() if args.rules == "-" else Path(args.rules).read_text()
        fields["rules"] = text
        fields["rules_type"] = ("text/markdown; charset=utf-8; variant=unseenet"
                                if args.rules.endswith(".md") else None)
    if getattr(args, "attachments", None) is not None:
        extra["attachments"] = None if args.attachments == 0 else (
            {"max_size": args.attachments} | ({"types": args.types.split(",")} if args.types else {}))
    for opt in ("max_pins", "max_pages", "home"):
        if getattr(args, opt, None) is not None:
            extra[opt] = getattr(args, opt)
    return fields, extra


def emit(args, text: str, data=None) -> None:
    """Print for people, or JSON for scripts with --json."""
    if getattr(args, "json", False):
        print(json.dumps(data if data is not None else {"text": text}, ensure_ascii=False))
    else:
        print(text)


async def c_group_show(app: App, args) -> None:
    """The group's current manifest: who owns it, who may post, and its settings."""
    from .client.session import SessionError
    try:
        m = await _session(app, args).fetch_manifest(args.group)
    except SessionError as exc:
        sys.exit(f"Could not read the manifest: {exc}")
    if m is None:
        sys.exit("The node does not carry that group.")
    emit(args, json.dumps(m.raw, indent=2, ensure_ascii=False), m.raw)


async def c_group_edit(app: App, args) -> None:
    """A new manifest for a group you own (UN-RFC 0004 section 4): roles, bans and
    settings, all in one."""
    from .client.session import SessionError
    s = _session(app, args)
    try:
        await s.fetch_manifest(args.group)
        data = s.manifest_data(args.group)
        if not data:
            sys.exit("The node does not carry that group.")
        fields, extra = _group_fields(args)
        fields |= extra
        for role, add, remove in (("posters", args.add_poster, args.remove_poster),
                                  ("moderators", args.add_moderator, args.remove_moderator)):
            if add or remove:
                keys = [k for k in data.get(role, []) if k not in (remove or [])]
                fields[role] = keys + [k for k in (add or []) if k not in keys]
        if args.ban or args.unban:
            banned = [b for b in data.get("banned", []) if isinstance(b, dict)
                      and b.get("key") not in (args.unban or []) and b.get("key") not in (args.ban or [])]
            for key in args.ban or []:
                crypto.key_from_text(key)
                entry = {"key": key}
                if args.reason:
                    entry["reason"] = args.reason[:200]
                banned.append(entry)
            fields["banned"] = banned
        if not fields:
            sys.exit("Nothing to change.")
        new = await s.update_group(args.group, **fields)
    except (SessionError, ValueError, crypto.CryptoError) as exc:
        sys.exit(f"Not changed: {exc}")
    emit(args, f"Changed {args.group} (serial {new['serial']})", new)


async def c_group_create(app: App, args) -> None:
    from .client.session import SessionError
    fields, extra = _group_fields(args)
    s = _session(app, args)
    try:
        gid = await s.create_group(
            args.name, args.type, title=fields.get("title", ""),
            description=fields.get("description", ""), min_pow=fields.get("min_pow", 20),
            local=getattr(args, "local", False), retention_days=fields.get("retention_days"),
            rules=fields.get("rules", ""), rules_type=fields.get("rules_type"),
            view=fields.get("view"), kinds=fields.get("kinds"),
            comments=fields.get("comments") if args.type == "channel" else None,
            comment_days=fields.get("comment_days") if args.type == "channel" else None,
            moderators=getattr(args, "moderator", None) or [],
            posters=getattr(args, "poster", None) or [], extra=extra or None)
    except (SessionError, ValueError) as exc:
        sys.exit(f"Not created: {exc}")
    emit(args, f"Created {gid}", {"group": gid})


async def c_invite(app: App, args) -> None:
    owner = app.identity(args.identity)
    entry = app.data["groups"].get(args.group)
    if not entry or not entry.get("owner") or entry["type"] != "closed":
        sys.exit("You can only invite to closed groups you own.")
    epoch = max(int(e) for e in entry["keys"])
    keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))
    member = crypto.key_from_text(args.key)
    await app.post(make_key_update(owner, args.group, epoch, keys, [member], grant_only=True,
                                   pow_bits=await app.bits(args.group, owner)))
    print(f"Invite sent. Share this with the new member:\n  unseenet:join?g={args.group}"
          f"&n={app.data['nodes'][0]}")


async def c_post(app: App, args) -> None:
    from .core import portals
    author = app.identity(args.identity)
    entry = app.data["groups"].get(args.group, {})
    found = portals.portals(entry.get("manifest") or {})
    if found and not args.publish_outside_tor:      # UN-RFC 0023 section 3.5
        sys.exit(portals.warning(args.group.rpartition("@")[0], found)
                 + "\n\nAdd --publish-outside-tor to post anyway.")
    body = sys.stdin.read() if args.body is None else args.body
    if getattr(args, "attach", None):
        await _post_with_files(app, args, author, body)
        return
    if entry.get("type") == "closed":
        epoch = max(int(e) for e in entry["keys"])
        keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))
        art = encrypted_article(args.group, epoch, keys, author, from_name=app.display_name(args.identity),
                                subject=args.subject, body=body,
                                pow_bits=await app.bits(args.group, author))
    else:
        art = new_article(args.group, args.subject, body, from_name=app.display_name(args.identity))
        art.finalize(author, await app.bits(args.group, author))
    await app.post(art)


async def _post_with_files(app: App, args, author, body: str) -> None:
    """For testing nodes only (#148): upload files with BLOBPOST and post an article
    that references them (UN-RFC 0027). Plain groups only; the clients' real
    attachments are #149 and unseenet-gui#63, with metadata removed first."""
    import mimetypes
    from .core import blobs as bl
    if app.data["groups"].get(args.group, {}).get("type") in ("closed", "inbox"):
        sys.exit("--attach is a test tool for open groups; encrypted files come with the clients")
    if len(args.attach) > bl.MAX_PER_ARTICLE:
        sys.exit(f"at most {bl.MAX_PER_ARTICLE} files")
    files = [(Path(f).name, Path(f).read_bytes()) for f in args.attach]
    headers = [("Blobs", " ".join(f"{bl.blob_id(d)}={len(d)}" for _, d in files))]
    for i, (name, data) in enumerate(files, 1):
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        headers.append((f"Attachment-{i}", f"{bl.blob_id(data)}; type={mime}; size={len(data)}; "
                                           f"name={crypto.b64(name.encode()[:128])}"))
    art = new_article(args.group, args.subject, body, from_name=app.display_name(args.identity),
                      extra=headers)
    art.finalize(author, await app.bits(args.group, author) + bl.extra_bits(art))
    header = app.session.ripening_header()
    if header:
        art.set("Key-Ripening", header)
    async with app.connect() as c:
        for _, data in files:
            bid = bl.blob_id(data)
            code, text = await c.command(f"BLOBPOST {bid} {len(data)}")
            if code == 345:
                c.writer.write(data)
                await c.writer.drain()
                code, text = await c._response()
            if code != 245:
                sys.exit(f"The node did not take {bid}: {code} {text}")
        code, text = await c.post(art.to_bytes())
    if code != 240:
        sys.exit(f"Rejected: {code} {text}")
    print(f"Posted {art.message_id} with {len(files)} file(s)")


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
                data = json.loads(art.body)
                entry["type"] = entry["type"] or data["type"]
                if int(data.get("serial", 0)) >= int((entry.get("manifest") or {}).get("serial", 0)):
                    entry["manifest"] = data           # the newest: for its portals (c_post)
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
            print(f"\n[{n}] {subj}\n    From: {frm} ({short}) {author[:20]}...\n    Date: {art['Date']}"
                  f"\n    Message-ID: {art.message_id}\n")
            print("    " + body.rstrip("\n").replace("\n", "\n    "))
    from .core import portals
    found = portals.portals(entry.get("manifest") or {})
    if found:
        print("\nAlso published outside Tor, through portals:\n  "
              + portals.describe(found).replace("\n", "\n  "))
    app.vault.save()


async def c_bridges(app: App, args) -> None:
    if args.mode:
        lines = [ln for ln in args.line or []]
        if args.mode == "custom" and not lines:
            sys.exit("custom bridges need at least one --line \"obfs4 1.2.3.4:443 ...\"")
        app.data["tor"] = {**(app.data.get("tor") or {}), "mode": args.mode, "custom": lines}
        app.vault.save()
    setting = app.data.get("tor") or {"mode": "off"}
    print(f"Bridges: {setting['mode']}")
    for line in setting.get("custom", []) if setting["mode"] == "custom" else []:
        print(f"  {line}")


async def c_tor(app: App, args) -> None:
    """Which Tor to use: our own, or one that is already running (Tails, Whonix)."""
    from .core.tor import Socks, TorError, existing_tor, parse_socks
    if args.use:
        tor = dict(app.data.get("tor") or {"mode": "off"})
        value = args.use.strip()
        if value.lower() == "auto":
            tor.pop("socks", None)
        elif value.lower() == "own":
            tor["socks"] = "own"
        else:
            try:
                tor["socks"] = str(Socks(*parse_socks(value)))
            except TorError as exc:
                sys.exit(str(exc))
        app.data["tor"] = tor
        app.vault.save()
    print(f"Setting: {(app.data.get('tor') or {}).get('socks') or 'auto'}")
    try:
        socks = existing_tor(app.data.get("tor"))
    except TorError as exc:
        sys.exit(str(exc))
    print(f"In use:  the Tor at {socks} ({socks.source})" if socks else
          "In use:  Unseenet starts its own Tor")


async def c_gateways(app: App, args) -> None:
    """The gateway directory (UN-RFC 0038 section 6): what to invite on other networks."""
    from .core.gateways import DIRECTORY_GROUP, current
    arts = []
    async with app.connect() as c:
        try:
            _, low, high = await c.group(args.directory or DIRECTORY_GROUP)
        except NNTPError:
            sys.exit("The gateway directory is not carried by this node.")
        for n in range(low, high + 1):
            raw = await c.article(str(n))
            if raw is None:
                continue
            try:
                art = Article.from_bytes(_strip_reader_headers(raw))
            except ArticleError:
                continue
            if not art.control:
                arts.append(art)
    found = current(arts)
    if args.network:
        found = [a for a in found if any(n.network == args.network for n in a.networks)]
    if not found:
        print("No gateway has announced itself in the last 30 days.")
        return
    print("Gateways that announced themselves (a list, not a recommendation):\n")
    for a in found:
        print(f"{a.name}  [{a.fingerprint}]  last announced {a.date:%Y-%m-%d}")
        for n in a.networks:
            if args.network and n.network != args.network:
                continue
            does = [w for w, on in (("import", n.imports), ("export", n.exports),
                                    ("portals", n.portals), ("takes invitations", n.requests)) if on]
            print(f"  {n.network}: {n.account}  ({', '.join(does)})")
        print(f"  operator {a.operator[:20]}...  contact {a.contact}")
        print(f"  serves {len(a.groups)} group(s)")
        if a.policy:
            print(f"  policy: {a.policy}")
        print()


async def ripen_command(args) -> None:
    """unseenet ripen: ripen a key (UN-RFC 0025) up to a level, e.g. when setting up
    a gateway or a bot. Needs only the key's public half to compute; ``--publish``
    signs and posts its ripe@ manifest. A stopped run goes on where it was."""
    import time
    from .client.session import Session, SessionError
    from .core import ripening as rp
    if not rp.available():
        sys.exit("key ripening needs chiavdf (pip install chiavdf)")
    if getattr(args, "public_key", None):
        return _ripen_public(args)
    if args.key_file:
        from .core.poster import PosterError, load_key
        try:
            ident = load_key(key_file=args.key_file)
        except PosterError as exc:
            sys.exit(str(exc))
        state = args.state or f"{args.key_file}.state.json"
        s = Session.from_key(ident, state, status=lambda *_: None)
    else:
        passphrase = _passphrase("Vault passphrase: ", "UNSEENET_PASSPHRASE")
        try:
            s = Session(Vault.open(Path(args.vault), passphrase, **_kdf()), status=lambda *_: None)
        except VaultError as exc:
            sys.exit(str(exc))
    for address in args.node or []:
        s.add_node(address)
    name = args.identity
    start, t0 = time.monotonic(), s.ripening(name).t
    print(f"{s.identity(name).key_text}: level {_lv(s.ripening(name).level)}, t = {t0:,}")
    while True:
        chain = s.ripening(name)
        if chain.level is not None and chain.level >= args.to:
            break
        if not await s.ripen_segment(name):
            break
        chain = s.ripening(name)
        rate = (chain.t - t0) / max(1e-9, time.monotonic() - start)
        nxt = rp.next_threshold(chain.t)
        eta = f", next level in about {(nxt - chain.t) / rate / 60:.0f} min" if nxt else ""
        print(f"  level {_lv(chain.level)}, t = {chain.t:,} ({rate:,.0f}/s){eta}", flush=True)
    if args.publish:
        try:
            await s.publish_ripening(name)
        except (SessionError, OSError, ConnectionError) as exc:
            sys.exit(f"could not publish ripe@: {exc}")
        print(f"published {s.ripe_group(name)}")
    await s.close()


async def serve_command(args) -> None:
    """unseenet serve: the local client API (UN-RFC 0046). With ``--key-file`` it
    runs as a service (section 3.2), unlocked from the start; otherwise the front
    end unlocks the vault through it. The first line on standard output is
    ``UNSEENET-API 1 <url> <token>`` (section 3.1)."""
    try:
        from .client.localapi import server
    except ImportError:
        sys.exit("the local API needs aiohttp (pip install unseenet[api])")
    from .client.localapi import LocalAPI
    from .client.session import Session
    api_file = Path(args.api_file) if args.api_file else None
    if args.key_file:
        from .core.poster import PosterError, load_key
        try:
            ident = load_key(key_file=args.key_file)
        except PosterError as exc:
            sys.exit(str(exc))
        s = Session.from_key(ident, args.state or f"{args.key_file}.state.json",
                             status=lambda *_: None)
        for address in args.node or []:
            s.add_node(address)
        if not s.node:
            sys.exit("a service needs a node: --node <address>")
        api = LocalAPI(session=s, service=True)
        await api.start()
    else:
        if args.node:
            sys.exit("--node is for a service; a person chooses a node when setting up")
        api = LocalAPI(Path(args.vault))
        api_file = api_file or Path(f"{args.vault}.api")

    def ready(port: int, token: str) -> None:
        print(server.announce_line(port, token), flush=True)
    await server.serve(api, port=args.port, on_ready=ready, api_file=api_file)


def _ripen_public(args) -> None:
    """Ripen from the public key alone, on any machine: the secret is not needed to
    compute, only to publish. The state file is then copied next to the key file,
    where ``Session.from_key`` (and ``unseenet ripen --key-file --publish``) find it."""
    import json
    from .client.headless import STATE_VERSION
    from .core import ripening as rp
    try:
        pk = crypto.key_from_text(args.public_key)
    except crypto.CryptoError as exc:
        sys.exit(f"not a key: {exc}")
    text = crypto.key_to_text(pk)
    path = Path(args.state or f"{crypto.fingerprint(pk)}.state.json")
    state = json.loads(path.read_text()) if path.exists() else {"v": STATE_VERSION, "data": {}}
    data = state["data"]
    if data.setdefault("key", text) != text:
        sys.exit(f"{path} belongs to another key ({data['key']})")
    entry = data.setdefault("ripening", {}).setdefault(text, {"segments": [], "published": 0})
    while True:
        chain = rp.Chain([rp.Segment.from_dict(s) for s in entry["segments"]])
        if chain.level is not None and chain.level >= args.to:
            break
        length = rp.next_segment_length(chain.t)
        if not length:
            break
        entry["segments"].append(rp.prove_segment(pk, chain.end, length).to_dict())
        path.write_text(json.dumps(state, separators=(",", ":")))   # a stop loses one segment
        print(f"  level {_lv(rp.level(chain.t + length))}, t = {chain.t + length:,}", flush=True)
    print(f"{path}: copy it next to the key file as <key file>.state.json")


def _lv(level) -> str:
    return "-" if level is None else str(level)


COMMANDS = {
    "id-new": c_id_new, "whoami": c_whoami, "node-add": c_node_add, "groups": c_groups,
    "group-create": c_group_create, "group-remove": c_group_remove, "invite": c_invite,
    "withdraw": c_withdraw, "group-edit": c_group_edit, "group-show": c_group_show,
    "post": c_post, "read": c_read,
    "bridges": c_bridges, "tor": c_tor, "gateways": c_gateways,
}


def _group_options(s, *, create: bool) -> None:
    """The settings group-create and group-edit share (UN-RFC 0004, 0008, 0027-0035)."""
    s.add_argument("--title")
    s.add_argument("--description")
    s.add_argument("--min-pow", type=int, help="postage in bits (create: default 20)")
    s.add_argument("--retention-days", type=int, help="how long posts circulate (UN-RFC 0012)")
    s.add_argument("--view", choices=["threads", "chat", "feed", "pages"],
                   help="how the group is shown (pages: channels only)")
    s.add_argument("--kinds", help="chat, post or chat,post (UN-RFC 0028)")
    s.add_argument("--rules", metavar="FILE", help="the group's rules from a file (.md: Markdown), - for stdin")
    s.add_argument("--comments", choices=["none", "open"],
                   help="channels: whether readers may comment on posts (UN-RFC 0030)")
    s.add_argument("--comment-days", type=int,
                   help="channels: days after a post during which it takes comments")
    s.add_argument("--attachments", type=int, metavar="MAX_SIZE",
                   help="allow files up to this many octets (UN-RFC 0027); 0 to stop")
    s.add_argument("--types", help="with --attachments: allowed media types, e.g. image/*,application/pdf")
    s.add_argument("--max-pins", type=int, help="pins in force, 0-25 (UN-RFC 0033)")
    s.add_argument("--max-pages", type=int, help="sites: pages in force, 1-100 (UN-RFC 0035)")
    s.add_argument("--home", help="sites: the path of the home page")


def client_main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="unseenet", description="Unseenet client.")
    from .portable import default_vault_path
    p.add_argument("--vault", default=str(default_vault_path()), help="encrypted vault file")
    p.add_argument("--identity", "-i", help="identity to use (default: first)")
    p.add_argument("--version", action="version", version=f"unseenet {__version__}")
    p.add_argument("--json", action="store_true", help="answer in JSON, for scripts")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("id-new", help="create a new identity")
    s.add_argument("name")
    s.add_argument("--display", help="display name shown in From")
    sub.add_parser("whoami", help="list identities")
    s = sub.add_parser("node-add", help="add a node address (xyz.onion or host:port)")
    s.add_argument("address")
    s = sub.add_parser("groups", help="list groups on the node")
    s.add_argument("pattern", nargs="?", default="*")
    s.add_argument("--mine", action="store_true", help="only groups owned by an identity in this vault")
    s = sub.add_parser("group-create", help="create a group you own")
    s.add_argument("name")
    s.add_argument("--type", choices=["open", "moderated", "channel", "closed", "inbox"], default="open")
    s.add_argument("--local", action="store_true", help="never replicated to other nodes (UN-RFC 0009)")
    s.add_argument("--moderator", action="append", metavar="KEY", help="a moderator's key (repeat)")
    s.add_argument("--poster", action="append", metavar="KEY", help="channels: a poster's key (repeat)")
    _group_options(s, create=True)
    s = sub.add_parser("group-edit", help="change a group you own: roles, bans and settings")
    s.add_argument("group", help="full group ID, name@fingerprint")
    s.add_argument("--add-poster", action="append", metavar="KEY")
    s.add_argument("--remove-poster", action="append", metavar="KEY")
    s.add_argument("--add-moderator", action="append", metavar="KEY")
    s.add_argument("--remove-moderator", action="append", metavar="KEY")
    s.add_argument("--ban", action="append", metavar="KEY", help="ban a key from posting (UN-RFC 0004 5.1)")
    s.add_argument("--unban", action="append", metavar="KEY")
    s.add_argument("--reason", help="with --ban: shown to the banned and to readers")
    _group_options(s, create=False)
    s = sub.add_parser("group-show", help="show a group's current manifest")
    s.add_argument("group", help="full group ID, name@fingerprint")
    s = sub.add_parser("group-remove", help="remove groups you own from the whole network (final)")
    s.add_argument("group", nargs="+", help="full group ID, name@fingerprint")
    s.add_argument("--reason", help="short reason, shown to nodes and readers")
    s.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    s = sub.add_parser("withdraw", help="withdraw posts: your own, or any in a group you own or moderate")
    s.add_argument("group", help="full group ID, name@fingerprint")
    s.add_argument("message_id", nargs="*", help="Message-IDs")
    s.add_argument("--all", action="store_true", help="every post in a group you own or moderate")
    s.add_argument("--keep", action="append", metavar="MSGID", help="with --all: leave this one")
    s.add_argument("--reason", help="shown to readers (not in closed groups)")
    s.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    s = sub.add_parser("invite", help="give a key access to a closed group you own")
    s.add_argument("group")
    s.add_argument("key", help="the member's ed25519:... key")
    s = sub.add_parser("post", help="post to a group (body from --body or stdin)")
    s.add_argument("group")
    s.add_argument("--subject", "-s", required=True)
    s.add_argument("--body")
    s.add_argument("--publish-outside-tor", action="store_true",
                   help="post even though the group has portals to other networks")
    s.add_argument("--attach", action="append", metavar="FILE",
                   help="for testing nodes: attach a file (UN-RFC 0027), up to 4; "
                        "metadata is NOT removed")
    s = sub.add_parser("read", help="read a group")
    s.add_argument("group")
    s = sub.add_parser("gateways", help="list gateways to other networks (to invite one)")
    s.add_argument("--network", help="only this network, e.g. matrix")
    s.add_argument("--directory", help="another directory group")
    s = sub.add_parser("bridges", help="show or set Tor bridges, for networks that block Tor")
    s.add_argument("mode", nargs="?", choices=["off", "obfs4", "snowflake", "custom"])
    s.add_argument("--line", action="append", help="a bridge line (custom; repeat for more)")
    s = sub.add_parser("tor", help="show or set which Tor to use: our own or one already running")
    s.add_argument("use", nargs="?", metavar="auto|own|HOST:PORT",
                   help="auto: Tails' Tor on Tails, else our own; own: always our own; "
                        "HOST:PORT: the SOCKS port of a running Tor, e.g. 127.0.0.1:9050")

    s = sub.add_parser("ripen", help="ripen a key so it can post, e.g. a gateway's or a bot's "
                                     "(UN-RFC 0025)")
    s.add_argument("--to", type=int, default=0, choices=range(5),
                   help="the level to reach (default 0: enough to post; 3: no surcharge)")
    s.add_argument("--key-file", help="a file with the key's seed in hex, instead of the vault")
    s.add_argument("--public-key", help="ripen from the public key alone (ed25519:...), on any "
                                       "machine; publish later with --key-file")
    s.add_argument("--state", help="where the chain is kept for --key-file (default: next to it)")
    s.add_argument("--node", action="append", help="a node to publish to (with --publish)")
    s.add_argument("--publish", action="store_true", help="post the ripe@ manifest when done")

    s = sub.add_parser("serve", help="offer the local client API (UN-RFC 0046) to a front end "
                                     "or a program on this computer")
    s.add_argument("--key-file", help="run as a service with this key (a bot, a gateway): "
                                      "no vault, no unlock")
    s.add_argument("--state", help="where a service keeps its state (default: next to the key)")
    s.add_argument("--node", action="append", help="a node to use (a service needs one)")
    s.add_argument("--port", type=int, default=0, help="the port on 127.0.0.1 (default: random)")
    s.add_argument("--api-file", help="also write the address and token to this file (mode "
                                      "0600); default for a vault: <vault>.api")

    args = p.parse_args(argv)
    if args.cmd == "ripen":
        asyncio.run(ripen_command(args))
        return
    if args.cmd == "serve":
        asyncio.run(serve_command(args))
        return
    asyncio.run(client_command(args))
