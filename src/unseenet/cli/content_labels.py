"""`unseenet labels`: content labels (UN-RFC 0053) from the command line.

Belongs here: following labellers (and for topics), what to do with each warning,
and being a labeller - starting your ``labels@`` channel and publishing labels - all
through ``Session`` (``client/session/content_labels.py``).

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # noqa: F401  names tests patch on the module, read at call time


def labels_parsers(sub) -> None:
    """The parser of ``unseenet labels``."""
    from ..core.tags import WARNINGS
    s = sub.add_parser("labels", help="content labels: labellers you follow, what to do with "
                                      "warnings, labelling (UN-RFC 0053)")
    r = s.add_subparsers(dest="what")
    r.add_parser("list", help="the labellers that count, and your choice per warning")
    p = r.add_parser("follow", help="follow a labeller in every group")
    p.add_argument("key")
    p.add_argument("--label", default="")
    p.add_argument("--topics", action="store_true", help="its topics too, for your rules")
    p = r.add_parser("unfollow", help="stop following a labeller (also one a group names)")
    p.add_argument("key")
    p = r.add_parser("warning", help="show, blur or hide a warning")
    p.add_argument("warning", choices=WARNINGS)
    p.add_argument("choice", choices=["show", "blur", "hide"])
    p = r.add_parser("start", help="start or change your labels@ channel")
    p.add_argument("--policy", default="")
    p.add_argument("--contact", default="")
    p.add_argument("--automatic", action="store_true")
    p.add_argument("--topics", action="store_true", help="you also label topics")
    p = r.add_parser("publish", help="label a post: GROUP MESSAGE-ID LABEL...")
    p.add_argument("group")
    p.add_argument("message_id")
    p.add_argument("labels", nargs="*", help="none: take your labels of it back")
    p.add_argument("--note", default="")


async def c_labels(app: App, args) -> None:
    from ..client.session import SessionError
    s = _session(app, args)
    what = getattr(args, "what", None) or "list"
    try:
        if what == "list":
            await s.refresh_labels()
            ls = s.labellers()
            lines = [f"{'on ' if x['on'] else 'off'} {x['label']}  {x['key']}"
                     + (f"  named for {', '.join(h + '.*' for h in x['hierarchies'])}" if x["hierarchies"] else "")
                     + (f"  named for {', '.join(x['groups'])}" if x["groups"] else "")
                     + ("  topics" if x["topics"] else "") for x in ls] or ["No labellers."]
            lines += [f"{w}: {c}" for w, c in s.warning_choices().items()]
            emit(args, "\n".join(lines), {"labellers": ls, "warnings": s.warning_choices()})
        elif what == "follow":
            s.follow_labeller(args.key, args.label, args.topics)
            emit(args, f"Following {args.key}" + (" with topics" if args.topics else ""), {"ok": True})
        elif what == "unfollow":
            s.unfollow_labeller(args.key)
            emit(args, f"Not following {args.key}", {"ok": True})
        elif what == "warning":
            s.set_warning_choice(args.warning, args.choice)
            emit(args, f"{args.warning}: {args.choice}", {"ok": True})
        elif what == "start":
            gid = await s.start_labels(args.policy, args.contact, args.automatic, args.topics)
            emit(args, f"Your labels channel: {gid}", {"group": gid})
        elif what == "publish":
            mid = await s.publish_labels([(args.message_id, args.group, args.labels)], args.note)
            emit(args, f"Published {mid}", {"id": mid})
    except SessionError as exc:
        sys.exit(f"Not done: {exc}")
