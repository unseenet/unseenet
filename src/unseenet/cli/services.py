"""`unseenet ripen` and `unseenet serve`: for services, bots and gateways.

Belongs here: ripening a key ahead of time (UN-RFC 0025), also from a public key alone
on the maintainer's machine (``_ripen_public``), and serving the local client API for
a program (``serve``, UN-RFC 0046 section 3.2).

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # names tests patch on the module, read at call time


async def ripen_command(args) -> None:
    """unseenet ripen: ripen a key (UN-RFC 0025) up to a level, e.g. when setting up
    a gateway or a bot. Needs only the key's public half to compute; ``--publish``
    signs and posts its ripe@ manifest. A stopped run goes on where it was."""
    import time
    from ..client.session import Session, SessionError
    from ..core import ripening as rp
    if not rp.available():
        sys.exit("key ripening needs chiavdf (pip install chiavdf)")
    if getattr(args, "public_key", None):
        return _ripen_public(args)
    if args.key_file:
        from ..core.poster import PosterError, load_key
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
        from ..client.localapi import server
    except ImportError:
        sys.exit("the local API needs aiohttp (pip install unseenet[api])")
    from ..client.localapi import LocalAPI
    from ..client.session import Session
    api_file = Path(args.api_file) if args.api_file else None
    if args.key_file:
        from ..core.poster import PosterError, load_key
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
    from ..client.headless import STATE_VERSION
    from ..core import ripening as rp
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


__all__ = ['ripen_command', 'serve_command', '_ripen_public', '_lv']
