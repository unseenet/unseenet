"""`unseenet id-new`, `whoami`, `node-add`: the identities in the vault and its nodes.

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
    print(f"{args.name}: {ident.key_text}")


async def c_whoami(app: App, args) -> None:
    """``unseenet whoami``: the identities in the vault, the default marked with ``*``."""
    for name, entry in app.data["identities"].items():
        ident = crypto.Identity.from_seed(bytes.fromhex(entry["seed"]))
        mark = "*" if name == app.data.get("default_identity") else " "
        print(f"{mark} {name:12} {entry['display']:20} {ident.key_text}")


async def c_node_add(app: App, args) -> None:
    """``unseenet node-add ADDRESS``: add a node (``xyz.onion`` or ``host:port``)."""
    if args.address not in app.data["nodes"]:
        app.data["nodes"].append(args.address)
        app.vault.save()
    print("Nodes:", ", ".join(app.data["nodes"]))


__all__ = ['c_id_new', 'c_whoami', 'c_node_add']
