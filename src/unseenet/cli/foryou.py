"""`unseenet foryou`: replies to you and posts that name you, from all your groups.

Belongs here: the For you list as the clients show it - your ``[foryou]`` rules,
``quiet`` entries marked, ``--all`` to look without the rules (Show all, never saved),
``--why`` for what the rules did (UN-RFC 0051 section 5.5, #629).

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file


def foryou_parsers(sub) -> None:
    """The parser of ``unseenet foryou``."""
    s = sub.add_parser("foryou", help="replies to you and posts that name you, from all your groups")
    s.add_argument("--all", action="store_true", help="without your [foryou] rules (Show all; nothing saved)")
    s.add_argument("--why", action="store_true", help="say what your rules did to each")
    s.add_argument("--unread", action="store_true", help="only what you have not read")


async def c_foryou(app: App, args) -> None:
    s = _session(app, args)
    for gid in list(s.data.get("subscribed", [])):
        if gid == s.my_inbox:
            continue
        try:
            await s.fetch_group(gid)
        except Exception as exc:  # noqa: BLE001  one group not read: the rest still are
            s.say(f"{gid}: not read ({exc})")
    rows = s.scored_for_you(unread_only=args.unread, rules=not args.all)
    mine, patterns = s.my_message_ids(), s._mention_patterns()
    out, lines = [], []
    for m, r in rows:
        why = "mention" if (m.private or s.for_me(m, mine, patterns) == "mention") else "reply"
        quiet = "quiet" in r.actions
        item = {"id": m.message_id, "group": m.group, "subject": m.subject, "why": why,
                "read": s.is_read(m), "quiet": quiet,
                "date": m.date.isoformat() if m.date else None}
        if args.why:
            item["rules"] = r.explain()
        out.append(item)
        mark = ("◄" if why == "reply" else "♦") + (" " if s.is_read(m) else "*")
        when = m.date.astimezone().strftime("%d %b %H:%M") if m.date else ""
        lines.append(f"{mark} {when}  {s.group_label(m.group)}  {m.subject}" + ("  (quiet)" if quiet else "")
                     + (f"\n      {r.explain()}" if args.why and r.explain() else ""))
    head = "For you" + (" - all, without your rules" if args.all else "")
    emit(args, "\n".join([head] + (lines or ["Nothing for you."])), {"for_you": out, "show_all": bool(args.all)})
