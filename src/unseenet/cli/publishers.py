"""`unseenet publishers`: whom the stick takes updates from (UN-RFC 0062 section 6, #822).

Belongs here: listing the stick's publishers, showing what a releases channel holds
before it is added (``show``), adding one by the fingerprint of its first key list,
following one, removing one. All through ``Session`` (``client/session/nodes.py``) and
``publishers.py``.

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # noqa: F401  names tests patch on the module, read at call time


def publishers_parsers(sub) -> None:
    s = sub.add_parser("publishers", help="whom this stick takes updates from (UN-RFC 0062 6)")
    t = s.add_subparsers(dest="what")
    t.add_parser("list", help="the stick's publishers (the default)")
    p = t.add_parser("show", help="what a releases channel holds: its key list's fingerprint, "
                                  "its keys and its newest releases")
    p.add_argument("group", help="the publisher's releases channel (Group ID)")
    p = t.add_parser("add", help="add a publisher, by the fingerprint 'show' printed and the "
                                 "publisher confirmed elsewhere")
    p.add_argument("group")
    p.add_argument("--fingerprint", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--follow", action="store_true", help="and take updates from it from now on")
    for name, what in (("follow", "take updates from this publisher from now on"),
                       ("remove", "take a publisher off the list (the project too)")):
        p = t.add_parser(name, help=what)
        p.add_argument("group")


def _plain(got: dict) -> str:
    if not got["stick"]:
        head = "Not on a stick: updates are the project's (publishers are chosen on a stick)."
    elif not got["follow"] or not any(p["followed"] for p in got["publishers"]):
        head = "This stick follows no publisher: it takes no updates until you add one."
    else:
        head = "Publishers (* is the one this stick takes updates from):"
    rows = [f"{'*' if p['followed'] else ' '} {p['name'] or p['group']}  {p['group']}  "
            f"[{p['fingerprint']}]" for p in got["publishers"]]
    return "\n".join([head, *rows])


async def c_publishers(app: App, args) -> None:
    """``unseenet publishers list|show|add|follow|remove``."""
    from ..client.localapi.api.publishers import preview_fields
    from ..client.session import SessionError
    s = _session(app, args)
    what = getattr(args, "what", None) or "list"
    try:
        if what == "list":
            got = s.publishers()
            emit(args, _plain(got), got)
        elif what == "show":
            p = await s.publisher_preview(args.group)
            got = preview_fields(p)
            lines = [f"Releases channel: {p.group}",
                     f"Fingerprint of its first key list: {p.fingerprint}",
                     "  compare it with what the publisher says elsewhere - its site, a "
                     "person you trust - before you add it",
                     f"Keys now (list {p.keys.seq}, {p.keys.threshold} must sign):",
                     *[f"  {k}" for k in p.keys.keys]]
            if p.fork:
                lines.append("Its key list has FORKED: two lists with one number. Do not add it.")
            lines += [f"Newest {c}: {v}" for c, v in sorted(p.releases.items())] \
                or ["No signed releases yet."]
            emit(args, "\n".join(lines), got)
        elif what == "add":
            got = await s.add_publisher(args.group, args.fingerprint, args.name, args.follow)
            emit(args, "Added.\n" + _plain(got), got)
        else:
            got = s.change_publisher(what, args.group)
            emit(args, _plain(got), got)
    except SessionError as exc:
        sys.exit(str(exc))


__all__ = ["c_publishers", "publishers_parsers"]
