"""`unseenet id-new`, `id-import`, `whoami`, `node-add`, `passphrase`: the identities in the
vault, its nodes and its passphrase.

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


COPIES_NOTE = ("Only this vault file changes. Copies of it on other devices, sticks or "
               "backups still open with the old passphrase: replace or delete them.")


async def c_passphrase(app: App, args) -> None:
    """``unseenet passphrase``: give the vault a new passphrase (#579), as **Change
    passphrase** in the clients and ``POST /api/passphrase`` do.

    The current passphrase is the one the vault was just opened with. The new one is
    asked for twice on the terminal, or taken from ``UNSEENET_NEW_PASSPHRASE`` for
    scripts. Same checks as the local API: at least 4 characters, not the same as now.
    Only this file changes - copies elsewhere keep the old passphrase."""
    old = app.passphrase
    if old is None:                       # called without client_command (tests, scripts)
        old = _c._passphrase("Current passphrase: ", "UNSEENET_PASSPHRASE")
    new = os.environ.get("UNSEENET_NEW_PASSPHRASE")
    if new is None:
        new = getpass.getpass("New passphrase: ")
        if getpass.getpass("New passphrase again: ") != new:
            sys.exit("The two new passphrases are not the same. Nothing changed.")
    if len(new) < 4:
        sys.exit("The new passphrase is too short. Nothing changed.")
    if new == old:
        sys.exit("The new passphrase is the same as the current one. Nothing changed.")
    try:
        app.vault.change_passphrase(old, new)
    except VaultError as exc:
        sys.exit("The current passphrase is not right." if "wrong passphrase" in str(exc)
                 else f"Could not change it: {exc}")
    except OSError as exc:
        sys.exit(f"Could not write the vault, the old passphrase still works: {exc}")
    app.passphrase = new
    emit(args, f"Passphrase changed. {COPIES_NOTE}",
         {"ok": True, "vault": str(app.vault.path), "note": COPIES_NOTE})


__all__ = ['c_id_new', 'c_id_import', 'c_whoami', 'c_node_add', 'c_passphrase', 'COPIES_NOTE']
