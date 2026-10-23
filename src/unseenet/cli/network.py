"""`unseenet tor`, `bridges`, `gateways`: Tor, bridges for networks that block it, and the
gateway directory (UN-RFC 0038).

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # names tests patch on the module, read at call time


async def c_bridges(app: App, args) -> None:
    """``unseenet bridges [--mode off|builtin|custom] [--line ...]``: show or set the
    Tor bridges, for networks that block Tor."""
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
    from ..core.tor import Socks, TorError, existing_tor, parse_socks
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
    from ..core.gateways import DIRECTORY_GROUP, current
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


__all__ = ['c_bridges', 'c_tor', 'c_gateways']
