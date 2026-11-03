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


def operators_parsers(sub) -> None:
    """The parser of ``unseenet operator``: a server's operator channel (UN-RFC 0065)."""
    s = sub.add_parser("operator", help="operator channels: a server tells its operators what "
                                        "happens and takes their commands (UN-RFC 0065)")
    t = s.add_subparsers(dest="what")
    t.add_parser("channels", help="the operator boxes you own or read")
    p = t.add_parser("create", help="owner: a new operator box (a team inbox) for your servers")
    p.add_argument("name", help="the inbox's name, e.g. operator")
    p.add_argument("--server-name", help="what the box answers as, e.g. 'My servers'")
    p = t.add_parser("servers", help="the servers in a box, by name")
    p.add_argument("channel")
    p = t.add_parser("say", help="a message for one server in a box")
    p.add_argument("channel")
    p.add_argument("server", help="its name, as `operator servers` lists it")
    p.add_argument("text", help="the command, e.g. status; - reads it from stdin")
    p = t.add_parser("add-server", help="owner: list the server's channel key as a reader")
    p.add_argument("channel")
    p.add_argument("key", help="the channel key the server showed")
    p = t.add_parser("add", help="owner: add an operator to one or more channels")
    p.add_argument("key", help="the person's own key")
    p.add_argument("--channels", required=True,
                   help="channels, separated by commas, or all (every channel you own)")
    p = t.add_parser("remove", help="owner: remove an operator's team key from channels")
    p.add_argument("key", help="the team key, as `team readers` lists it")
    p.add_argument("--channels", default="all", help="channels, separated by commas, or all")


def _own_channels(s) -> list[str]:
    return sorted(g for g, e in s.data.get("groups", {}).items()
                  if e.get("owner") and (e.get("manifest") or {}).get("operator_channel"))


def _channels(s, text: str) -> list[str]:
    if text.strip() == "all":
        found = _own_channels(s)
        if not found:
            sys.exit("you own no operator channels")
        return found
    return [c.strip() for c in text.split(",") if c.strip()]


async def c_operator(app: App, args) -> None:
    """``unseenet operator ...``: see ``unseenet operator -h``. Each server has a channel
    of its own (UN-RFC 0065 section 3.2); adding or removing an operator works on many
    at once (section 3.4)."""
    from ..client.operator import add_server
    from ..client.session import SessionError
    s = _session(app, args)
    what = getattr(args, "what", None) or "channels"
    try:
        if what == "channels":
            own = _own_channels(s)
            read = [t["group"] for t in s.team_inboxes()
                    if s.manifest_data(t["group"]).get("operator_channel")]
            rows = [{"group": g, "name": s.team_name(g), "owner": g in own}
                    for g in sorted(set(own) | set(read))]
            emit(args, "\n".join(f"{r['group']}  {r['name']}" + ("  (yours)" if r["owner"] else "")
                                 for r in rows) or "No operator channels.", rows)
        elif what == "create":
            gid = await s.create_group(args.name, "inbox")
            await s.update_group(gid, operator_channel=True,
                                 **({"team_name": args.server_name} if args.server_name else {}))
            emit(args, f"Made {gid}.\nOn the server, make its channel key for it and give the "
                       f"key to `unseenet operator add-server {gid} <key>`.", {"group": gid})
        elif what == "servers":
            from ..client.operator import box_servers
            await s.fetch_group(args.channel)
            rows = box_servers(s, args.channel)
            emit(args, "\n".join(f"{r['name'] or '(not heard from yet)'}  {r['key']}" for r in rows)
                 or "No servers in that box yet.", rows)
        elif what == "say":
            from ..client.operator import address
            from ..client.session import KIND_CHAT
            if s.team_key(args.channel) is None:
                sys.exit("you read no such box: accept its invitation first")
            text = sys.stdin.read() if args.text == "-" else args.text
            mid = await s.send_private(args.channel, "", address(args.server, text).rstrip() + "\n",
                                       kind=KIND_CHAT, as_team=args.channel)
            emit(args, f"Sent to {args.server}: {mid}", {"id": mid})
        elif what == "add-server":
            await add_server(s, args.channel, args.key)
            emit(args, f"The server reads {args.channel} now.", {"group": args.channel})
        elif what == "add":
            done = {}
            for gid in _channels(s, args.channels):
                done[gid] = await s.add_team_reader(gid, args.key)
            emit(args, "\n".join(f"{g}: team key {k}" for g, k in done.items())
                 + "\nThe invitations are in their inbox to accept.", {"added": done})
        elif what == "remove":
            done = []
            for gid in _channels(s, args.channels):
                data = await s._own_inbox(gid)
                if args.key in data.get("readers", []):
                    await s.remove_team_reader(gid, args.key)
                    done.append(gid)
            emit(args, ("Removed from " + ", ".join(done)) if done else
                 "That team key reads none of those channels.", {"removed": done})
    except (SessionError, ValueError, crypto.CryptoError) as exc:
        sys.exit(str(exc))


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
            sender = crypto.key_from_text(msg.sender_key)
            mine = sender if target == personal_inbox_id(sender) else None   # or a team inbox
            mid = await s.send_private(target, "Re: " + (msg.subject or ""), text,
                                       owner_key=mine,
                                       references=[msg.message_id], as_team=args.group)
            emit(args, f"Answered as {s.team_name(args.group)}: {mid}", {"id": mid})
    except (SessionError, ValueError, crypto.CryptoError) as exc:
        sys.exit(str(exc))


__all__ = ["c_team", "teams_parsers", "c_operator", "operators_parsers"]
