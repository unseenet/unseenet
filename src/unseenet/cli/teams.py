"""`unseenet team`: team inboxes (UN-RFC 0047, #341) from the command line.

Belongs here: the team inboxes you read, accepting an invitation, forgetting a team key,
and for an inbox's owner who reads it - adding and removing readers - all through
``Session`` (``client/session/teams.py``). Writing on an inbox's behalf is ``unseenet
post`` to a private inbox with ``--as-team`` where offered; here: ``team reply``.

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # noqa: F401  names tests patch on the module, read at call time


def teams_parsers(sub) -> None:
    """The parser of ``unseenet team``."""
    s = sub.add_parser("team", help="team inboxes: read an inbox with others, answer on its "
                                    "behalf (UN-RFC 0047)")
    t = s.add_subparsers(dest="what")
    t.add_parser("list", help="the team inboxes you read")
    t.add_parser("invitations", help="team keys handed to you, to accept")
    p = t.add_parser("accept", help="accept the invitation in a private post")
    p.add_argument("msgid")
    p = t.add_parser("forget", help="remove a team key from your vault")
    p.add_argument("group")
    p = t.add_parser("readers", help="owner: who reads an inbox you own")
    p.add_argument("group")
    p = t.add_parser("add", help="owner: a new reader - a team key sent to their inbox")
    p.add_argument("group")
    p.add_argument("key", help="the person's own key")
    p.add_argument("--name", help="the name the inbox answers as, e.g. 'Unseenet (operator)'")
    p = t.add_parser("remove", help="owner: remove a reader (its team key)")
    p.add_argument("group")
    p.add_argument("key", help="the team key, as `team readers` lists it")
    p = t.add_parser("reply", help="answer a message in a team inbox, on the inbox's behalf")
    p.add_argument("group")
    p.add_argument("msgid")
    p.add_argument("text", help="the answer; - reads it from stdin")


def _mid(text: str) -> str:
    return text if text.startswith("<") else f"<{text}>"


async def c_team(app: App, args) -> None:
    """``unseenet team ...``: see ``unseenet team -h``. The owner key is needed only to
    change who reads; reading and answering need a team key."""
    from ..client.session import SessionError
    s = _session(app, args)
    what = getattr(args, "what", None) or "list"
    try:
        if what == "list":
            rows = s.team_inboxes()
            emit(args, "\n".join(f"{r['group']}  {r['name']}" + ("" if r["reader"] else "  (removed)")
                                 for r in rows) or "You read no team inboxes.", rows)
        elif what == "invitations":
            await s.fetch_group(s.my_inbox)
            rows = [{"id": m.message_id, "group": s.team_invitation(m)["group"], "from": m.sender_key}
                    for m in s.private_messages() if s.team_invitation(m)]
            emit(args, "\n".join(f"{r['id']}  {r['group']}" for r in rows) or "No invitations.", rows)
        elif what == "accept":
            await s.fetch_group(s.my_inbox)
            msg = next((m for m in s.private_messages() if m.message_id == _mid(args.msgid)), None)
            if msg is None:
                sys.exit("no such private post")
            gid = await s.accept_team_invitation(msg)
            emit(args, f"You read {gid} now ({s.team_name(gid)}).", {"group": gid})
        elif what == "forget":
            s.forget_team_key(args.group)
            emit(args, f"Forgot your team key for {args.group}.", {"group": args.group})
        elif what == "readers":
            data = await s._own_inbox(args.group)
            rows = list(data.get("readers", []))
            emit(args, "\n".join(rows) or "Nobody reads it with a team key.",
                 {"readers": rows, "team_name": data.get("team_name", "")})
        elif what == "add":
            key = await s.add_team_reader(args.group, args.key, args.name)
            emit(args, f"Added a reader; their team key is {key}. It is in their inbox to accept.",
                 {"team_key": key})
        elif what == "remove":
            await s.remove_team_reader(args.group, args.key)
            emit(args, f"Removed {args.key}.", {"removed": args.key})
        elif what == "reply":
            await s.fetch_group(args.group)
            msg = next((m for m in s.cache.get(args.group, {}).values()
                        if m.message_id == _mid(args.msgid)), None)
            if msg is None or not msg.readable:
                sys.exit("no such message you can read in that inbox")
            target = s.reply_target(msg)
            if target is None:
                sys.exit("it was sent anonymously: there is nobody to answer")
            text = sys.stdin.read() if args.text == "-" else args.text + "\n"
            mid = await s.send_private(target, "Re: " + (msg.subject or ""), text,
                                       owner_key=crypto.key_from_text(msg.sender_key),
                                       references=[msg.message_id], as_team=args.group)
            emit(args, f"Answered as {s.team_name(args.group)}: {mid}", {"id": mid})
    except (SessionError, ValueError, crypto.CryptoError) as exc:
        sys.exit(str(exc))


__all__ = ["c_team", "teams_parsers"]
