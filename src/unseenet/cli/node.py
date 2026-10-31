"""`unseenet-node`: running a node from the command line (UN-RFC 0005).

Belongs here: reading ``node.toml`` into a ``NodeConfig`` (every section and its
checks: ``[node]``, ``[[peer]]``, ``[limits]``, ``[operator]``, ``[blobs]``, ``[refusals]``), the node
key sealed in the data directory (UN-RFC 0016), starting the node with Tor, its peers,
pulling, blob fetching and expiry (``run_node``), and the ``unseenet-node`` options
that do one thing and exit (``--show-key``, ``--sign``, ``--drop-group``,
``--refuse-blob``).

Not here: the node itself (``unseenet.node.server``).

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # names tests patch on the module, read at call time


def _min_ripe(path, value):
    """node.toml ``min_ripe``: a level 0-4 or "-" for none (UN-RFC 0025 section 5)."""
    from ..core import ripening
    try:
        return ripening.parse_min(str(value))
    except (ValueError, ripening.RipeningError):
        sys.exit(f"{path}: min_ripe must be a level 0-4 or \"-\", not {value!r}")


def load_node_config(path: Path | None):
    """Read ``node.toml`` into a ``NodeConfig``, checking every section - ``[node]``,
    ``[[peer]]``, ``[limits]``, ``[operator]``, ``[blobs]``, ``[refusals]`` - so a mistake stops the node at
    start with a clear message. No file: the defaults."""
    from ..node.server import NodeConfig, PeerConfig

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
                      fetch=bool(node.get("fetch", True)),       # UN-RFC 0060 section 6.4
                      follow_reports=_follow_reports(path, data.get("follow_reports", [])),
                      profiles=str(node.get("profiles", "accept")),
                      avatars=str(node.get("avatars", "refuse")),
                      sites=str(node.get("sites", "refuse")),
                      emoji=str(node.get("emoji", "refuse")),
                      excludes=str(node.get("excludes", "")),
                      carries=_carries(path, node.get("carries", ["*"])),   # UN-RFC 0055
                      announce=bool(node.get("announce", True)),
                      ripen_to=int(node.get("ripen_to", 1)),
                      operator=data.get("operator", {}),
                      max_clients=_max_clients(path, data.get("limits", {}).get("max_clients", "auto")),
                      blobs=_blobs_config(path, data.get("blobs", {})),
                      **_refusals_config(path, data.get("refusals", {})),
                      peers=peers)


def _carries(path: Path, value) -> list[str]:
    """``carries`` in [node] (UN-RFC 0055 section 3.1): the hierarchies this node carries,
    such as ``["alt.*", "dk.*", "!dk.politik.*"]``; ``["*"]`` (the default) is all."""
    from ..core import carrying as ca
    try:
        return ca.check_patterns(value)
    except ca.CarriesProblem as exc:
        sys.exit(f"{path}: {exc}")


def _follow_reports(path: Path, items) -> list[dict]:
    """[[follow_reports]] (UN-RFC 0045 section 6): the report issuers this node follows,
    each with ``posts`` ("hide" or "delete") and ``keys`` ("refuse", "surcharge" or
    "ignore"). Nobody unless the operator names them."""
    from ..core import crypto
    from ..core.reports import NODE_KEYS, NODE_POSTS
    out = []
    for i, f in enumerate(items if isinstance(items, list) else []):
        where = f"{path}: follow_reports #{i + 1}"
        if not isinstance(f, dict):
            sys.exit(f"{where}: a table with issuer, posts and keys")
        try:
            crypto.key_from_text(f.get("issuer"))
        except (crypto.CryptoError, TypeError, ValueError):
            sys.exit(f"{where}: issuer must be a key (ed25519:...)")
        posts, keys = f.get("posts", "hide"), f.get("keys", "ignore")
        if posts not in NODE_POSTS:
            sys.exit(f"{where}: posts must be one of {', '.join(NODE_POSTS)}")
        if keys not in NODE_KEYS:
            sys.exit(f"{where}: keys must be one of {', '.join(NODE_KEYS)}")
        if any(o["issuer"] == f["issuer"] for o in out):
            sys.exit(f"{where}: {f['issuer']} is followed twice")
        out.append({"issuer": f["issuer"], "posts": posts, "keys": keys})
    return out


def _refusals_config(path: Path, r: dict) -> dict:
    """[refusals] (UN-RFC 0027 section 7.3, #717): the keys whose refusal lists this node
    follows (``keys``) and the groups they may come from (``groups``, a wildmat) - for
    every picture it carries, files or not. None by default."""
    if not isinstance(r, dict):
        sys.exit(f"{path}: [refusals] is a table")
    keys = r.get("keys", [])
    if not isinstance(keys, list):
        sys.exit(f"{path}: [refusals] keys is a list of keys")
    for k in keys:
        try:
            crypto.key_from_text(str(k))
        except crypto.CryptoError:
            sys.exit(f"{path}: [refusals] keys: bad key {k!r}")
    return {"refusal_keys": [str(k) for k in keys], "refusal_groups": str(r.get("groups", "*"))}


def _blobs_config(path: Path, b: dict) -> dict | None:
    """[blobs] (UN-RFC 0027 section 8): off unless ``enabled = true``. The
    recommended first setting is 1 MiB, 30 days, encrypted off, for every group."""
    from ..core import blobs as bl
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
    """Run a node: open its store and blobs, unseal its key, start Tor and publish the
    onion service, feed and pull from its peers, fetch blobs, expire, until stopped."""
    from ..node.peering import Feeder
    from ..node.server import Node

    data = Path(args.data)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = load_node_config(Path(args.config) if args.config else None)
    passphrase = _passphrase("Node passphrase: ", "UNSEENET_NODE_PASSPHRASE")
    node_key = load_node_key(data, passphrase)
    print(f"Node key: {node_key.key_text}  (give it to the operators you peer with)")
    node = Node(Store(data / "articles.sqlite"), config, key=node_key)
    logging.getLogger("unseenet").addHandler(node.stats.log)   # the monitor's log lines
    changed = node.policy_changed()      # #543: a new policy forgets what the old refused
    if changed:
        print(f"Policy changed since the last run: forgot {changed['refusals_forgotten']} "
              f"refusal(s), reconciling and pulling again, fetching the files of "
              f"{changed['blob_articles']} stored article(s)")
    host, port = args.listen.rsplit(":", 1)
    server = await node.serve(host, int(port))
    print(f"ONNTP listening on {args.listen}")
    monitor = None
    if args.monitor != "off":
        from ..node.stats import serve as serve_stats
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
        node.socks_port = socks_port           # for fetching shared articles (UN-RFC 0060)
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
    from ..node.pulling import Puller
    feeders += [asyncio.create_task(Puller(node, peer, socks_port).run_forever())
                for peer in config.peers if peer.pull]
    if (config.operator or {}).get("contact"):  # tell the operator of new messages (#135)
        from ..node.stats import contact_watch
        feeders.append(asyncio.create_task(contact_watch(node, data)))
    if tor is not None and config.announce:    # UN-RFC 0055 section 5: say where it is
        from ..node.announcing import Announcer
        feeders.append(asyncio.create_task(
            Announcer(node, data, f"onion:{onion}", ripen_to=config.ripen_to).run_forever()))
    if config.blobs is not None:               # blobs follow their article (UN-RFC 0027, 6.3)
        from ..node.blobfetch import BlobFollower
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
    """The ``unseenet-node`` command line (an entry point): run a node, or do one thing
    and exit (``--show-key``, ``--sign``, ``--drop-group``, ``--refuse-blob``)."""
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
        from ..core import blobs as bl
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
        from ..node.server import Node
        node = Node(Store(Path(args.data) / "articles.sqlite"))
        if args.drop_group:
            if args.drop_group in node.network_groups():
                sys.exit(f"{args.drop_group} is one of the network's own groups, which every "
                         "node carries (UN-RFC 0055 section 4); it cannot be dropped.")
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


__all__ = ['_min_ripe', 'load_node_config', '_blobs_config', '_max_clients', 'load_node_key', 'run_node', 'node_main']
