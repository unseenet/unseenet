"""`unseenet pin`, `pins`, `page-put`, `page-remove`, `pages`, `feed-start`, `site-start`.

Belongs here: pinning posts (UN-RFC 0033), writing and listing the pages of a site
(UN-RFC 0035), and starting a personal feed or site (UN-RFC 0029 section 2.1) - all
through ``Session`` (``client/session/kept.py`` and ``personal.py``).

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # names tests patch on the module, read at call time


async def _read(s, group: str) -> None:
    try:
        split_group_id(group)
    except ValueError:
        sys.exit(f"{group!r} is not a group ID: give name@fingerprint")
    await s.fetch_group(group)


async def c_pin(app: App, args) -> None:
    """``unseenet pin GROUP MSGID [--note TEXT] [--unpin]``: owner or moderator - pin a
    post at the top of the group, kept beyond its window (or unpin it)."""
    from ..client.session import SessionError
    s = _session(app, args)
    try:
        await _read(s, args.group)
        mid = await s.pin(args.group, args.message_id, getattr(args, "note", None) or "",
                          unpin=bool(getattr(args, "unpin", False)))
    except (SessionError, ValueError) as exc:
        sys.exit(f"Not done: {exc}")
    what = "Unpinned" if getattr(args, "unpin", False) else "Pinned"
    emit(args, f"{what} {args.message_id} ({mid})", {"marker": mid, "unpin": bool(getattr(args, "unpin", False))})


async def c_pins(app: App, args) -> None:
    """``unseenet pins GROUP``: the posts pinned in a group, newest pin first."""
    s = _session(app, args)
    await _read(s, args.group)
    pins = s.pins(args.group)
    rows = []
    for p in pins:
        m = s.find_message(args.group, p["id"])
        rows.append({"id": p["id"], "subject": m.subject if m else "", "note": p["note"],
                     "by": s.label_of(p["by"]), "pinned": p["pinned"].isoformat(timespec="minutes")})
    text = "\n".join(f"{r['id']}  {r['subject'] or '(not read)'}" + (f"  - {r['note']}" if r["note"] else "")
                     for r in rows) or "Nothing is pinned."
    emit(args, text, {"pins": rows})


async def c_page_put(app: App, args) -> None:
    """``unseenet page-put SITE PATH FILE [--title TEXT]``: write a page of a site you
    write in, from a Markdown or text file (``-`` for stdin); a new version names
    the ones it replaces."""
    from ..client.session import SessionError
    s = _session(app, args)
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    ctype = "text/plain; charset=utf-8" if str(args.file).endswith(".txt") else None
    try:
        await _read(s, args.group)
        mid = await s.put_page(args.group, args.path, text, getattr(args, "title", None) or "",
                               content_type=ctype)
    except SessionError as exc:
        sys.exit(f"Not written: {exc}")
    emit(args, f"Wrote {args.path} ({mid})", {"path": args.path, "message_id": mid})


async def c_page_remove(app: App, args) -> None:
    """``unseenet page-remove SITE PATH``: remove a page from a site you write in."""
    from ..client.session import SessionError
    s = _session(app, args)
    try:
        await _read(s, args.group)
        mid = await s.remove_page(args.group, args.path)
    except SessionError as exc:
        sys.exit(f"Not removed: {exc}")
    emit(args, f"Removed {args.path} ({mid})", {"path": args.path, "message_id": mid})


async def c_pages(app: App, args) -> None:
    """``unseenet pages SITE``: a site's pages in force, the home page first, with the
    Message-ID of each one's current version."""
    s = _session(app, args)
    await _read(s, args.group)
    site = s.site(args.group)
    rows = [{"path": p["path"], "title": p["title"],
             "current": p["current"].message_id if p["current"] else None,
             "previous": p["previous"].message_id if p["previous"] else None}
            for p in site["pages"]]
    text = "\n".join(f"{r['path']:30} {r['title']}" + ("   (home)" if r["path"] == site["home"] else "")
                     for r in rows) or "The site has no pages yet."
    emit(args, text, {"home": site["home"], "pages": rows})


async def _start(app: App, args, kind: str) -> None:
    from ..client.session import SessionError
    s = _session(app, args)
    if not getattr(args, "json", False) or not getattr(args, "yes", False):
        print(s.personal_group_warning(kind) + "\n", file=sys.stderr)
    if not getattr(args, "yes", False):
        if not sys.stdin.isatty():
            sys.exit("Not started. Add --yes to confirm when not running interactively.")
        if input(f"Start your personal {kind}? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Not started.")
    try:
        gid = await s.start_personal_group(kind, comments=getattr(args, "comments", None) or "open",
                                           title=getattr(args, "title", None) or "")
    except SessionError as exc:
        sys.exit(f"Not started: {exc}")
    emit(args, f"Your {kind}: {gid}", {"group": gid})


async def c_feed_start(app: App, args) -> None:
    """``unseenet feed-start [--comments open|none] [--yes]``: start this identity's
    personal feed (``feed@<fp>``), after the warning that it is public."""
    await _start(app, args, "feed")


async def c_site_start(app: App, args) -> None:
    """``unseenet site-start [--yes]``: start this identity's personal site
    (``site@<fp>``), after the warning that it is public."""
    await _start(app, args, "site")


__all__ = ['c_pin', 'c_pins', 'c_page_put', 'c_page_remove', 'c_pages', 'c_feed_start',
           'c_site_start', '_read', '_start']
