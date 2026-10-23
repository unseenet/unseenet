"""`unseenet id-new`, `id-import`, `whoami`, `node-add`: the identities in the vault and its nodes.

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # names tests patch on the module, read at call time


async def c_id_new(app: App, args) -> None:
    """``unseenet id-new NAME [--display ...]``: make a new identity in the vault and
    print its key."""
    ident = crypto.Identity.generate()
    app.data["identities"][args.name] = {"seed": ident.seed.hex(), "display": args.display or args.name}
    app.data.setdefault("default_identity", args.name)
    app.vault.save()
    emit(args, f"{args.name}: {ident.key_text}", {"name": args.name, "key": ident.key_text,
                                                  "fingerprint": ident.fingerprint})


async def c_id_import(app: App, args) -> None:
    """``unseenet id-import NAME [--display ...]``: add an identity from its seed, 64 hex
    characters read from stdin - never from the command line, where other users of
    the machine could see it. For a key kept elsewhere: a service's, or one derived
    from a secret (unseenet-demo). The same seed again changes nothing."""
    line = sys.stdin.readline().strip()
    try:
        seed = bytes.fromhex(line)
        if len(seed) != 32:
            raise ValueError
        ident = crypto.Identity.from_seed(seed)
    except ValueError:
        sys.exit("give the seed on stdin: 64 hex characters")
    have = app.data["identities"].get(args.name)
    if have is not None and have["seed"] != seed.hex():
        sys.exit(f"there is already an identity {args.name} with another key")
    display = args.display or (have or {}).get("display") or args.name
    app.data["identities"][args.name] = {**(have or {}), "seed": seed.hex(), "display": display}
    app.data.setdefault("default_identity", args.name)
    app.vault.save()
    emit(args, f"{args.name}: {ident.key_text}", {"name": args.name, "key": ident.key_text,
                                                  "fingerprint": ident.fingerprint,
                                                  "new": have is None})


async def c_whoami(app: App, args) -> None:
    """``unseenet whoami``: the identities in the vault, the default marked with ``*``."""
    rows = []
    for name, entry in app.data["identities"].items():
        ident = crypto.Identity.from_seed(bytes.fromhex(entry["seed"]))
        rows.append({"name": name, "display": entry["display"], "key": ident.key_text,
                     "fingerprint": ident.fingerprint,
                     "default": name == app.data.get("default_identity")})
    emit(args, "\n".join(f"{'*' if r['default'] else ' '} {r['name']:12} {r['display']:20} {r['key']}"
                         for r in rows), {"identities": rows})


async def c_node_add(app: App, args) -> None:
    """``unseenet node-add ADDRESS``: add a node (``xyz.onion`` or ``host:port``)."""
    if args.address not in app.data["nodes"]:
        app.data["nodes"].append(args.address)
        app.vault.save()
    print("Nodes:", ", ".join(app.data["nodes"]))


__all__ = ['c_id_new', 'c_id_import', 'c_whoami', 'c_node_add']
