"""`unseenet names`, `name-claim`, `name-give`, `name-revoke`, `name-primary`,
`name-requests`: names for identities (UN-RFC 0019).

Belongs here: your registered and domain names, the names you give under yours
(``sonia@lorensen``), and the requests for them - all through ``client.naming``,
as the TUI, the GUI and the local API (``/api/names``) do (#578).

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from datetime import timedelta

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # names tests patch on the module, read at call time


async def _named(app: App, args):
    """The session, with the names read from the network first."""
    from ..client import naming
    s = _session(app, args)
    await s.ensure_inbox()                 # answers and certificates come there
    await s.fetch_group(s.my_inbox)
    await naming.refresh(s)
    return s


def _row(c) -> dict:
    from .. import names as nm
    return {"name": c.name, "kind": c.kind, "key": c.key, "expires": nm.rfc3339(c.expires)}


async def c_names(app: App, args) -> None:
    """``unseenet names``: your names, the one your posts show, the names you gave
    under yours, and claims on their way."""
    from ..client import naming
    s = await _named(app, args)
    mine = naming.my_names(s)
    shown = naming.preferred(s, s.identity().key_text, mine).name if mine else None
    given = naming.names_given(s)
    pending = naming.pending(s)
    lines = [f"{'*' if c.name == shown else ' '} {naming.name_text(c.name):32} {c.kind:10} "
             f"until {c.expires:%Y-%m-%d}" for c in mine] or ["  (no names)"]
    if given:
        lines += ["", "Given by you:"] + [f"  {c.name:32} {c.key}  until {c.expires:%Y-%m-%d}"
                                          for c in given]
    if pending:
        lines += ["", "On their way:"] + [f"  {a} {n} (sent {w})" for n, a, w in pending]
    public = naming.commits(s)
    if public:
        lines += ["", "Public claims:"] + [f"  {c['action']} {c['name']}: {_state_text(c)}"
                                           for c in public]
    emit(args, "\n".join(lines), {"names": [_row(c) for c in mine], "shown": shown,
                                  "given": [_row(c) for c in given],
                                  "pending": [{"name": n, "action": a, "sent": w}
                                              for n, a, w in pending],
                                  "public_claims": public})


def _state_text(c: dict) -> str:
    """A public claim's state in plain words (UN-RFC 0054 section 8)."""
    state = c["state"]
    if state == "waiting":
        return "committed; the claim goes out when it is an hour old"
    if state == "revealed":
        return "sent; the registrar decides once earlier claims are settled"
    if state == "lapsed":
        return "lapsed - it was not sent within seven days; claim again"
    a = c.get("answer") or {}
    return f"{a.get('outcome', 'answered')}" + (f": {a['text']}" if a.get("outcome") == "refused" else "")


async def c_name_claim(app: App, args) -> None:
    """``unseenet name-claim NAME``: claim, renew, release or transfer a registered or
    domain name. The registrar answers in your inbox; see it with ``unseenet names``."""
    from ..client import naming
    from ..client.session import SessionError
    name = args.name.lstrip("@")
    s = await _named(app, args)
    public = naming.claims_are_public(s)
    if public and not getattr(args, "json", False):
        print(naming.PUBLIC_NOTICE)
        if not getattr(args, "yes", False) and sys.stdin.isatty():
            if input("Send it? [y/N] ").strip().lower() not in ("y", "yes", "j", "ja"):
                sys.exit("Not sent.")
    try:
        await naming.claim(s, name, args.action, args.to)
    except (SessionError, ValueError) as exc:
        sys.exit(f"Not sent: {exc}")
    if public:
        text = (f"{args.action} {naming.name_text(name)}: the first step is posted. The claim "
                "itself goes out by itself when it is an hour old - whenever you use Unseenet "
                "in the next seven days (or run: unseenet names). The answer comes to your inbox.")
    else:
        text = (f"{args.action} {naming.name_text(name)} sent to the registrar; "
                "the answer comes to your inbox within a few hours.")
    emit(args, text, {"name": name, "action": args.action, "sent": True, "public": public})


async def c_name_give(app: App, args) -> None:
    """``unseenet name-give NAME KEY``: as the holder of ``@lorensen``, give
    ``sonia@lorensen`` to a key (UN-RFC 0019 section 5.4)."""
    from ..client import naming
    from ..client.session import SessionError
    s = await _named(app, args)
    try:
        delivered = await naming.has_inbox(s, args.key)
        cert = await naming.give_subname(s, args.name, args.key, timedelta(days=365 * args.years))
    except (SessionError, ValueError) as exc:
        sys.exit(f"Not given: {exc}")
    note = "" if delivered else (" It could not be sent yet: the key has no inbox. It gets "
                                 "it when you give it again after the key has been used.")
    emit(args, f"Gave {cert.name} to {cert.key} until {cert.expires:%Y-%m-%d}.{note}",
         {**_row(cert), "delivered": delivered})


async def c_name_revoke(app: App, args) -> None:
    """``unseenet name-revoke NAME``: take back a name you gave under yours."""
    from ..client import naming
    from ..client.session import SessionError
    s = await _named(app, args)
    try:
        await naming.revoke_subname(s, args.name)
    except (SessionError, ValueError) as exc:
        sys.exit(f"Not revoked: {exc}")
    emit(args, f"Revoked {args.name}", {"name": args.name, "revoked": True})


async def c_name_primary(app: App, args) -> None:
    """``unseenet name-primary NAME``: choose which of your names your posts show."""
    from ..client import naming
    from ..client.session import SessionError
    s = await _named(app, args)
    try:
        naming.set_primary(s, args.name.lstrip("@"))
    except SessionError as exc:
        sys.exit(str(exc))
    emit(args, f"Your posts now show {naming.name_text(args.name.lstrip('@'))}",
         {"shown": args.name.lstrip("@")})


async def c_name_requests(app: App, args) -> None:
    """``unseenet name-requests``: who asks for a name under yours; ``--approve NAME`` or
    ``--refuse NAME`` answers one."""
    from ..client import naming
    s = await _named(app, args)
    reqs = naming.name_requests(s)
    pick = args.approve or args.refuse
    if pick:
        found = [(m, d) for m, d in reqs if d["name"] == pick]
        if not found:
            sys.exit(f"No request for {pick}")
        await naming.answer_request(s, *found[0], approve=bool(args.approve))
        emit(args, f"{'Gave' if args.approve else 'Refused'} {pick}",
             {"name": pick, "approved": bool(args.approve)})
        return
    emit(args, "\n".join(f"  {d['name']:32} {d['key']}" for _, d in reqs) or "  (no requests)",
         {"requests": [{"name": d["name"], "key": d["key"]} for _, d in reqs]})


def names_parsers(sub) -> None:
    """Add the parsers of the name commands to ``unseenet``'s subcommands."""
    s = sub.add_parser("names", help="your names, and the names you gave under yours")
    s = sub.add_parser("name-claim", help="claim, renew, release or transfer a name (@name, @domain)")
    s.add_argument("name", help="e.g. lorensen or lorensen.dk")
    s.add_argument("--action", choices=["claim", "renew", "release", "transfer"], default="claim")
    s.add_argument("--to", help="for transfer: the new key")
    s.add_argument("--yes", action="store_true",
                   help="do not ask, also where claims are public (UN-RFC 0054 section 8)")
    s = sub.add_parser("name-give", help="give a name under yours to a key (sonia@lorensen)")
    s.add_argument("name", help="e.g. sonia@lorensen")
    s.add_argument("key", help="the key it goes to (ed25519:...)")
    s.add_argument("--years", type=int, choices=range(1, 6), default=1, metavar="1-5",
                   help="how long it lasts (default 1; at most 5)")
    s = sub.add_parser("name-revoke", help="take back a name you gave under yours")
    s.add_argument("name")
    s = sub.add_parser("name-primary", help="choose which of your names your posts show")
    s.add_argument("name")
    s = sub.add_parser("name-requests", help="requests for names under yours; approve or refuse")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--approve", metavar="NAME")
    g.add_argument("--refuse", metavar="NAME")


__all__ = [n for n in dir() if n.startswith(("c_name", "names_parsers"))]
