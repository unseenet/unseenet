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
                                        reason=reason)
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
    """``unseenet read GROUP``: print the group's posts - checked, decrypted for closed
    groups you are in - with their Message-IDs."""
    split_group_id(args.group)
    me = app.identity(args.identity)
    entry = app.data["groups"].setdefault(args.group, {"type": None, "owner": False, "keys": {}})
    async with app.connect() as c:
        try:
            count, low, high = await c.group(args.group)
        except NNTPError:
            sys.exit("Group not carried by this node.")
        for n in range(low, high + 1):
            raw = await c.article(str(n))
            if raw is None:
                continue
            raw = _strip_reader_headers(raw)
            try:
                art = Article.from_bytes(raw)
                validate_structure(art, raw_size=len(raw))
            except ArticleError as err:
                print(f"[{n}] INVALID: {err}")
                continue
            ctl = art.control
            if ctl and ctl[0] == "manifest":
                data = json.loads(art.body)
                entry["type"] = entry["type"] or data["type"]
                if int(data.get("serial", 0)) >= int((entry.get("manifest") or {}).get("serial", 0)):
                    entry["manifest"] = data           # the newest: for its portals (c_post)
                continue
            if ctl and ctl[0] in ("key-update", "key-grant"):
                opened = open_envelope(art, me)
                if opened:
                    epoch, keys = opened
                    entry["keys"][str(epoch)] = keys.secret.hex()
                continue
            if ctl:
                continue
            author = art["Author-Key"]
            short = crypto.fingerprint(art.author_key)[:4]
            if "Encrypted" in art:
                key_hex = entry["keys"].get(str(encryption_epoch(art)))
                if not key_hex:
                    print(f"[{n}] (encrypted, you are not a member of this epoch)")
                    continue
                inner = decrypt_article(art, crypto.GroupKeys(bytes.fromhex(key_hex)))
                frm, subj, body = inner["From"], inner["Subject"], inner.body
            else:
                frm, subj, body = art["From"], art["Subject"], art.body
            print(f"\n[{n}] {subj}\n    From: {frm} ({short}) {author[:20]}...\n    Date: {art['Date']}"
                  f"\n    Message-ID: {art.message_id}\n")
            print("    " + body.rstrip("\n").replace("\n", "\n    "))
    from ..core import portals
    found = portals.portals(entry.get("manifest") or {})
    if found:
        print("\nAlso published outside Tor, through portals:\n  "
              + portals.describe(found).replace("\n", "\n  "))
    app.vault.save()


__all__ = ['c_withdraw', 'c_post', 'c_read']
