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


def _duration(seconds: float) -> str:
    """About how long, in words: days, hours or minutes."""
    for unit, size in (("days", 86400), ("hours", 3600), ("minutes", 60)):
        if seconds >= size:
            n = seconds / size
            return f"about {n:.0f} {unit if round(n) != 1 else unit[:-1]}"
    return "less than a minute"


async def c_ripening(app: App, args) -> None:
    """``unseenet ripening [--to 3|4]``: the key's level, the level it is ripened to on
    this device and about how long that takes here (#740, UN-RFC 0025 section 7); with
    ``--to``, choose 3 (the default) or 4 - a client or ``unseenet serve`` then ripens to
    it while it runs. (``unseenet ripen --to N`` ripens a key file at once.)"""
    from ..client.runtime import RIPEN_TO
    from ..client.session import SessionError
    from ..core import ripening as rp
    s = _c._session(app, args)
    if getattr(args, "to", None) is not None:
        try:
            s.set_ripening_target(args.to)
        except SessionError as exc:
            sys.exit(f"Not done: {exc}")
    chain = s.ripening()
    level, chosen = chain.level, s.ripening_target()
    target = chosen if chosen is not None else RIPEN_TO
    left = s.ripening_seconds_left(target)
    speed = s.ripening_speed()
    if left is None and speed is None:                 # nothing proved here yet: the table's
        th = next(t for lv, t, _ in rp.LEVELS if lv == target)
        left, guessed = max(0, th - chain.t) / 100_000, True
    else:
        guessed = False
    lines = [f"Level {'-' if level is None else level} ({chain.t:,} iterations)",
             f"Ripened to level {target} on this device" + ("" if chosen is not None else " (the default)")]
    if left:
        lines.append(f"Left: {_duration(left)} of one core while a client runs"
                     + (" (a guess: nothing proved on this device yet)" if guessed else ""))
    elif left == 0:
        lines.append("There: nothing left to do")
    if target == 4 and (level is None or level < 4):
        lines.append("Level 4 pays 2 bits less postage than 3 - about a quarter of the work a post.")
    emit(args, "\n".join(lines), {"level": level, "t": chain.t, "target": target, "chosen": chosen,
                                  "seconds_left": round(left) if left is not None else None,
                                  "estimated": guessed, "speed": speed})


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


async def c_id_words(app: App, args) -> None:
    """``unseenet id-words [NAME]``: show an identity's 24 recovery words (UN-RFC 0050
    section 4), to write down. Asks for the vault passphrase again on the terminal, even
    when ``UNSEENET_PASSPHRASE`` opened the vault (section 4.2); ``--yes`` takes the
    passphrase the vault was opened with, for tests and scripts that know what they do.
    Prints them only: it never saves them anywhere (section 4.3)."""
    from ..core import recovery as rc
    from ..client.session.recovery import NOT_RESTORED
    from ..client.session import SessionError
    s = _session(app, args)
    name = args.name or s.default_identity_name()
    passphrase = app.passphrase if args.yes else getpass.getpass("Vault passphrase again: ")
    try:
        words = s.recovery_words(passphrase or "", name)
    except SessionError as exc:
        sys.exit(str(exc))
    ident = s.identity(name)
    if args.written:
        s.note_words_written(name)
    text = (rc.text_page(s.display_name(name), ident.fingerprint, words)
            + ("" if args.written else "\nWhen written down: unseenet id-words --written\n"))
    emit(args, text, {"identity": name, "fingerprint": ident.fingerprint, "words": words,
                      "note": NOT_RESTORED, "not_a_wallet": rc.NOT_A_WALLET,
                      "written": s.words_written(name)})


async def c_id_restore(app: App, args) -> None:
    """``unseenet id-restore [NAME]``: bring an identity back from its 24 recovery words,
    read from stdin - never from the command line, where others could see them - then
    read its state, name and profile from the network (UN-RFC 0050 section 4.4) and list
    the closed groups that do not come back (4.5). ``--offline``: only into the vault."""
    from ..client.session import SessionError
    from ..client.session.recovery import NOT_RESTORED
    if sys.stdin.isatty():
        print("Type the 24 recovery words, then Enter on an empty line:", file=sys.stderr)
    lines = []
    for line in sys.stdin:
        if not line.strip() and lines:
            break
        lines.append(line)
    s = _session(app, args)
    try:
        name, ident, new = s.restore_identity(" ".join(lines), args.name, args.display)
    except SessionError as exc:
        sys.exit(str(exc))
    data = {"identity": name, "key": ident.key_text, "fingerprint": ident.fingerprint, "new": new,
            "note": NOT_RESTORED}
    text = [f"{name}: {ident.key_text}" + ("" if new else " (already in this vault)")]
    if not args.offline and s.nodes:
        found = await s.restore_from_network(name)
        data.update(found)
        text.append({"read": "Your state came back from the network.",
                     "none": "No state was found in the network: you start with the default groups.",
                     "unreachable": "The network could not be reached: run it again later."}[found["state"]])
        if found["closed_groups"]:
            text.append("Closed groups that do not come back - ask their owners to invite you again:")
            text += [f"  {g['label']}  ({g['group']})" for g in found["closed_groups"]]
    text.append(NOT_RESTORED)
    emit(args, "\n".join(text), data)


async def c_copy_to(app: App, args) -> None:
    """``unseenet copy-to [--names A,B] [--no-group-secrets]``: offer this vault's
    identities to another device (UN-RFC 0050 section 3). Shows the code and the QR text,
    waits for the other device, shows the check words and asks whether they match; only
    then is anything sent. ``--yes`` answers yes (scripts that compare words otherwise)."""
    from ..client.session import SessionError
    s = _session(app, args)
    names = [n.strip() for n in args.names.split(",")] if args.names else None
    try:
        offer = await s.start_copy(names, not args.no_group_secrets)
    except SessionError as exc:
        sys.exit(str(exc))
    print(f"On the other device choose 'Get identity from another device' and type:\n\n"
          f"    {offer.code}\n\nor scan the QR code of: {offer.qr}\n\n"
          f"The code works once, for 10 minutes. Waiting ...", file=sys.stderr)
    words = await offer.wait_for_check()
    if words is None:
        sys.exit(offer.error or f"The copy {offer.state}.")
    print(f"\nCheck words: {words[0]} {words[1]}", file=sys.stderr)
    match = args.yes or (await asyncio.to_thread(
        input, "Does the other device show the same two words? [y/N] ")).strip().lower() in (
        "y", "yes", "j", "ja")                  # off the loop: the connection stays answered
    result = await offer.confirm(match)
    if result["state"] != "done":
        sys.exit(result["error"] or f"The copy {result['state']}.")
    emit(args, "Copied: " + (", ".join(result["added"]) or "nothing new on the other device"), result)


async def c_copy_from(app: App, args) -> None:
    """``unseenet copy-from CODE``: get identities from another device (UN-RFC 0050 section
    3) with the code it shows (or the QR text). Shows the check words to compare there,
    then waits for the copy and adds it to this vault."""
    from ..client.session import SessionError
    s = _session(app, args)
    try:
        got = await s.receive_copy(args.code)
    except SessionError as exc:
        sys.exit(str(exc))
    print(f"Check words: {got.check_words[0]} {got.check_words[1]}\n"
          "Confirm on the other device that it shows the same two words. Waiting ...",
          file=sys.stderr)
    try:
        added = await got.finish()
    except SessionError as exc:
        sys.exit(str(exc))
    if s.node:
        await s.adopt_published_ripenings(added)            # the keys' levels, at once
        await s.adopt_published_personal_groups(added)      # their feeds and sites (#771)
    emit(args, "Added: " + (", ".join(added) or "nothing new"), {"added": added})


__all__ = ['c_ripening', 'c_id_new', 'c_id_import', 'c_whoami', 'c_node_add', 'c_passphrase', 'COPIES_NOTE',
           'c_id_words', 'c_id_restore', 'c_copy_to', 'c_copy_from', 'c_export']


async def c_export(app: App, args) -> None:
    """``unseenet export [FILE] [--private]``: your data as a file (UN-RFC 0049 section
    7) - your own articles exactly as signed, their files, your sites, profile and
    state; never keys. ``--private`` adds private posts and chats and encrypts the whole
    file with a passphrase (asked, or ``UNSEENET_EXPORT_PASSPHRASE``)."""
    import getpass
    from ..client.session import SessionError
    s = _session(app, args)
    passphrase = None
    if args.private:
        passphrase = os.environ.get("UNSEENET_EXPORT_PASSPHRASE")
        if not passphrase:
            passphrase = getpass.getpass("A passphrase for the export: ")
            if passphrase != getpass.getpass("Again: "):
                sys.exit("The passphrases differ.")
    dest = args.file or f"unseenet-export-{s.identity().fingerprint[:8]}.zip"
    try:
        for gid in list(s.data.get("subscribed", [])):      # your articles, as the nodes have them
            try:
                await s.fetch_group(gid)
            except (SessionError, OSError, ConnectionError):
                pass
        out = await s.export(dest, private=args.private, passphrase=passphrase)
    except SessionError as exc:
        sys.exit(f"Not exported: {exc}")
    emit(args, f"Wrote {out['path']}: {out['articles']} articles, {out['files']} files, "
               f"{out['sites']} sites" + (f", {out['private']} private messages, encrypted"
                                          if out["encrypted"] else "")
         + (f"; {out['missing']} could not be had" if out["missing"] else "")
         + f".\n{out['note']}", out)
