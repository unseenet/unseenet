"""`unseenet post`, `withdraw`, `read`: writing, taking back and reading posts.

Belongs here: posting (also with files, ``--attach``), withdrawing your own posts or
any in a group you own or moderate (``--all`` for a demo's reset), and reading a group
on the command line. Everything goes through ``Session``.

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # names tests patch on the module, read at call time


async def c_withdraw(app: App, args) -> None:
    """UN-RFC 0004 section 7: withdraw posts - your own, or any in a group you own or
    moderate; ``--all`` every post in such a group (a demo's reset)."""
    from ..client.session import SessionError
    ids = [args.message_id] if isinstance(args.message_id, str) else list(args.message_id or [])
    every = getattr(args, "all", False)
    if not ids and not every:
        sys.exit("Give Message-IDs, or --all.")
    if not getattr(args, "json", False):
        print("Withdrawing is best effort: nodes delete the post and clients stop showing")
        print("it, but people who read it may have kept a copy.")
    if not args.yes:
        if not sys.stdin.isatty():
            sys.exit("Not withdrawn. Add --yes to confirm when not running interactively.")
        what = "every post" if every else ", ".join(ids)
        if input(f"Withdraw {what} from {args.group}? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Not withdrawn.")
    s = _session(app, args)
    reason = getattr(args, "reason", None) or ""
    try:
        if every:
            done = await s.withdraw_all(args.group, keep=set(getattr(args, "keep", None) or []),
                                        reason=reason,
                                        keep_authors=getattr(args, "keep_author", None) or [])
        else:
            done = []
            for mid in ids:
                await s.withdraw(args.group, mid, reason)
                done.append(mid if mid.startswith("<") else f"<{mid}>")
    except SessionError as exc:
        sys.exit(f"Not withdrawn: {exc}")
    emit(args, f"Withdrawn {len(done)}: " + " ".join(done), {"withdrawn": done})


async def c_post(app: App, args) -> None:
    """``unseenet post GROUP [-s SUBJECT] [--body ... | stdin]``: post to a group through
    ``Session`` - a post or a chat line (``--kind``), a reply or comment
    (``--reply-to``), a new version of your own post (``--edit``), with files
    (``--attach``: pictures cleaned of their metadata first). Warns first when the
    group has portals to other networks (UN-RFC 0023)."""
    from ..client.session import KIND_CHAT, KIND_POST, SessionError
    s = _session(app, args)
    group = args.group
    try:
        split_group_id(group)
    except ValueError:
        sys.exit(f"{group!r} is not a group ID: give name@fingerprint, see 'unseenet groups'")
    kind = getattr(args, "kind", None) or KIND_POST
    body = sys.stdin.read() if args.body is None else args.body
    ctype = {"markdown": "text/markdown; charset=utf-8; variant=unseenet",
             "plain": "text/plain; charset=utf-8"}.get(getattr(args, "format", None) or "")
    try:
        warning = s.portal_warning(group)
        if warning:                                    # UN-RFC 0023 section 3.5
            if not getattr(args, "publish_outside_tor", False):
                sys.exit(warning + "\n\nAdd --publish-outside-tor to post anyway.")
            s.accept_portals(group)
        parent = target = None
        wanted = getattr(args, "reply_to", None) or getattr(args, "edit", None)
        if wanted:
            mid = wanted if wanted.startswith("<") else f"<{wanted}>"
            await s.fetch_group(group)
            found = s.find_message(group, mid)
            if found is None:
                sys.exit(f"{mid} is not in {group} (or not on this node any more)")
            if getattr(args, "edit", None):
                target = found
            else:
                parent = found
        files = s.prepare_files(getattr(args, "attach", None) or [])
        for f in files:
            if f.note:
                print(f"Note: {f.note}", file=sys.stderr)
        if target is not None:
            if not s.may_edit(target):
                sys.exit("You can only edit your own posts (and not past their number of versions).")
            if files:
                sys.exit("An edit keeps the files of the post it replaces; --attach is for new posts.")
            msgid = await s.edit(target, args.subject or target.subject, body, ctype)
        else:
            perm = s.write_permission(group, reply_to=parent, kind=kind)
            if not perm:
                sys.exit(f"Not posted: {perm.reason}")
            subject = args.subject or ""
            if parent is not None and not subject and kind == KIND_POST:
                subject = parent.subject if parent.subject.lower().startswith("re:") \
                    else f"Re: {parent.subject}"
            if kind == KIND_POST and not subject.strip():
                sys.exit("A post needs a subject (-s); a chat line is --kind chat.")
            msgid = await s.post(group, "" if kind == KIND_CHAT else subject, body,
                                 references=[*parent.references, parent.message_id] if parent else None,
                                 kind=kind, content_type=ctype, files=files)
    except SessionError as exc:
        sys.exit(f"Not posted: {exc}")
    what = "Edited" if target is not None else "Posted"
    text = f"{what} {msgid}" + (f" with {len(files)} file(s)" if files else "")
    emit(args, text, {"message_id": msgid, "edited": target is not None,
                      "files": [{"name": f.name, "type": f.media_type, "size": len(f.octets),
                                 "note": f.note} for f in files]})


async def c_read(app: App, args) -> None:
    """``unseenet read GROUP``: the group's posts through ``Session`` - checked, and
    decrypted for closed groups you are in - in thread order, with their Message-IDs;
    ``--json`` gives each post's author, date, references, kind, page and blobs, for
    scripts such as unseenet-demo."""
    from ..client.session import SessionError
    s = _session(app, args)
    try:
        split_group_id(args.group)
    except ValueError:
        sys.exit(f"{args.group!r} is not a group ID")
    try:
        await s.fetch_group(args.group)
    except SessionError as exc:
        sys.exit(f"Not read: {exc}")
    rows = []
    reactions = s.all_reactions(args.group)                 # UN-RFC 0048
    for msg, depth in s.threads(args.group):
        c = reactions.get(msg.message_id)
        rows.append({"reactions": {e: len(k) for e, k in c.by_emoji.items()} if c else {},
                     "message_id": msg.message_id, "depth": depth, "author_key": msg.author_key,
                     "author": s.label_of(msg.author_key), "from": msg.from_name,
                     "subject": msg.subject, "date": msg.date.isoformat() if msg.date else None,
                     "references": list(msg.references), "kind": msg.kind,
                     "page": msg.page, "blobs": list(msg.blobs), "readable": msg.readable,
                     "body": msg.body})
    text = "\n".join(f"\n{'  ' * r['depth']}{r['subject'] or r['body'].strip()[:60]}\n"
                     f"    From: {r['from']} ({r['author']})\n    Date: {r['date']}\n"
                     f"    Message-ID: {r['message_id']}"
                     + ("\n    " + "  ".join(f"{e} {n}" for e, n in r["reactions"].items())
                        if r["reactions"] else "") for r in rows) or "No posts."
    emit(args, text, {"group": args.group, "posts": rows})


async def c_react(app: App, args) -> None:
    """``unseenet react GROUP MSGID EMOJI``: react to a post, comment or chat line
    (UN-RFC 0048). The emoji you already gave takes it back, another changes it;
    ``--who`` lists who gave the emoji instead."""
    from ..client.session import SessionError
    s = _session(app, args)
    try:
        split_group_id(args.group)
    except ValueError:
        sys.exit(f"{args.group!r} is not a group ID")
    try:
        await s.fetch_group(args.group)
        msg = s.find_message(args.group, args.message_id)
        if msg is None:
            sys.exit(f"{args.message_id} is not in {args.group}")
        if getattr(args, "who", False):
            who = s.who_reacted(msg, args.emoji)
            emit(args, "\n".join(who) or "Nobody.", {"who": who})
            return
        mid = await s.react(msg, args.emoji)
    except SessionError as exc:
        sys.exit(f"Not done: {exc}")
    if mid is None:
        emit(args, f"Took back {args.emoji} on {args.message_id}", {"taken_back": True})
    else:
        emit(args, f"Reacted {args.emoji} to {args.message_id} ({mid})",
             {"message_id": mid, "taken_back": False})


__all__ = ['c_withdraw', 'c_post', 'c_read', 'c_react']
