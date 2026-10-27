"""`unseenet reports`: spam reports (UN-RFC 0045) from the command line.

Belongs here: following and leaving report issuers, reading their reports, showing
what they hide in a group, being an issuer (starting your ``reports@`` group,
publishing and withdrawing reports, publishing a report someone sent you) and, for a
hierarchy maintainer, naming the issuers its readers follow by default - all through
``Session`` (``client/session/reports.py``) and ``client/naming.py``.

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # noqa: F401  names tests patch on the module, read at call time


def reports_parsers(sub) -> None:
    """The parser of ``unseenet reports``."""
    from ..core.reports import REASONS
    s = sub.add_parser("reports", help="spam reports: issuers you follow, and issuing them "
                                       "(UN-RFC 0045)")
    r = s.add_subparsers(dest="what")
    r.add_parser("issuers", help="the issuers you follow, and those your hierarchies name")
    p = r.add_parser("follow", help="follow an issuer's reports in every group")
    p.add_argument("key")
    p.add_argument("--label", default="", help="what to call it")
    p = r.add_parser("unfollow", help="stop following an issuer (also one a hierarchy names)")
    p.add_argument("key")
    r.add_parser("refresh", help="read the reports of the issuers you follow")
    p = r.add_parser("hidden", help="what reports hide in a group, and why")
    p.add_argument("group")
    p = r.add_parser("show", help="show a post hidden by a report anyway (on this device)")
    p.add_argument("msgid")
    p = r.add_parser("start", help="start (or change) your own reports group")
    p.add_argument("--policy", default="", help="what you report and how")
    p.add_argument("--contact", default="", help="where to object: an inbox or a URL")
    p.add_argument("--automatic", action="store_true", help="a program makes the reports")
    p = r.add_parser("publish", help="publish a report in your reports group")
    p.add_argument("--post", nargs=2, action="append", default=[], metavar=("GROUP", "MSGID"),
                   help="a post to report (repeat for more)")
    p.add_argument("--key", action="append", default=[], metavar="KEY", help="a key to report")
    p.add_argument("--reason", default="spam", choices=REASONS)
    p.add_argument("--days", type=int, default=365, help="a key: for how many days (at most 365)")
    p.add_argument("--note", default="")
    p = r.add_parser("received", help="reports others sent you; --publish N to publish one")
    p.add_argument("--publish", type=int, metavar="N", help="publish report N of the list")
    p.add_argument("--reason", choices=REASONS, help="instead of the reporter's reason")
    p.add_argument("--key", action="store_true", help="report the author's key too")
    r.add_parser("mine", help="the reports you have published")
    p = r.add_parser("withdraw", help="withdraw one of your reports")
    p.add_argument("msgid")
    p = r.add_parser("hierarchy", help="as a maintainer: the issuers your hierarchy's "
                                       "readers follow by default")
    p.add_argument("hierarchy", help="e.g. dk")
    p.add_argument("keys", nargs="*", help="the whole list; none clears it")


def _mid(text: str) -> str:
    return text if text.startswith("<") else f"<{text}>"


async def c_reports(app: App, args) -> None:
    """``unseenet reports ...``: see ``unseenet reports -h``. Hidden posts are never
    removed from anything: the issuers you follow only mark them, and you decide."""
    from ..client import naming
    from ..client.session import SessionError
    s = _session(app, args)
    what = getattr(args, "what", None) or "issuers"
    try:
        if what == "issuers":
            rows = s.report_issuers()
            lines = [f"{'on ' if r['on'] else 'off'} {r['label']}  {r['key']}"
                     + (f"  (named by {', '.join(h + '.*' for h in r['hierarchies'])})"
                        if r["hierarchies"] else "") + ("  (yours)" if r["yours"] else "")
                     for r in rows]
            emit(args, "\n".join(lines) or "You follow no report issuers.", rows)
        elif what == "follow":
            s.follow_issuer(args.key, args.label)
            n = await s.refresh_reports()
            emit(args, f"Following {s.identity_label(args.key)}'s reports.",
                 {"key": args.key, "read": n})
        elif what == "unfollow":
            s.unfollow_issuer(args.key)
            emit(args, f"No longer following {s.identity_label(args.key)}'s reports.",
                 {"key": args.key})
        elif what == "refresh":
            await s.refresh_naming()
            n = await s.refresh_reports()
            emit(args, f"Read the reports of {n} issuer(s); {len(s.report_book().reports)} report(s).",
                 {"issuers": n, "reports": len(s.report_book().reports)})
        elif what == "hidden":
            await s.fetch_group(args.group)
            rows = [{"id": m.message_id, "subject": m.subject, **m.reported}
                    for m in s.visible(list(s.cache.get(args.group, {}).values())) if m.reported]
            lines = [f"{r['id']}  {r['subject']!r}: hidden by {r['label']}: {r['reason']}"
                     + (" (automatic)" if r["automatic"] else "") for r in rows]
            emit(args, "\n".join(lines) or "Nothing hidden by reports.", rows)
        elif what == "show":
            s.show_reported(_mid(args.msgid))
            emit(args, f"{_mid(args.msgid)} is shown again on this device.", {"id": _mid(args.msgid)})
        elif what == "start":
            gid = await s.start_reports(args.policy, args.contact, args.automatic)
            emit(args, f"Your reports group: {gid}", {"group": gid})
        elif what == "publish":
            until = datetime.now(timezone.utc) + timedelta(days=min(max(args.days, 1), 365))
            posts = [(_mid(m), g, args.reason) for g, m in args.post]
            keys = [(k, args.reason, None if args.days >= 365 else until) for k in args.key]
            mid = await s.publish_report(posts, keys, args.note)
            emit(args, f"Published {mid}", {"id": mid})
        elif what == "received":
            await s.fetch_group(s.my_inbox)
            got = [m for m in s.private_messages() if s.received_report(m)]
            if args.publish is None:
                lines = [f"{i + 1}. {s.received_report(m)[0]} in {s.received_report(m)[1]}: "
                         f"{m.subject}" for i, m in enumerate(got)]
                emit(args, "\n".join(lines) or "No reports sent to you.",
                     [dict(zip(("id", "group", "author_key", "reason"), s.received_report(m))) for m in got])
                return
            if not 1 <= args.publish <= len(got):
                sys.exit(f"there is no report {args.publish}")
            mid, gid, author, why = s.received_report(got[args.publish - 1])
            why = args.reason or why                   # the reporter's reason, unless you say
            keys = [(author, why, None)] if args.key and author else []
            published = await s.publish_report([(mid, gid, why)], keys)
            emit(args, f"Published {published}", {"id": published})
        elif what == "mine":
            rows = [{"id": r.message_id, "date": r.date.isoformat(), "posts": len(r.posts),
                     "keys": len(r.keys), "note": r.note} for r in await s.my_reports()]
            lines = [f"{r['id']}  {r['date']}  {r['posts']} post(s), {r['keys']} key(s)  {r['note']}"
                     for r in rows]
            emit(args, "\n".join(lines) or "You have published no reports.", rows)
        elif what == "withdraw":
            await s.withdraw_report(_mid(args.msgid))
            emit(args, f"Withdrawn {_mid(args.msgid)}", {"id": _mid(args.msgid)})
        elif what == "hierarchy":
            await s.refresh_naming()
            h = await naming.set_report_issuers(s, args.hierarchy, args.keys)
            emit(args, f"{h}.* names {len(args.keys)} report issuer(s).",
                 {"hierarchy": h, "keys": args.keys})
    except (SessionError, ValueError) as exc:
        sys.exit(str(exc))


__all__ = ["c_reports", "reports_parsers"]
