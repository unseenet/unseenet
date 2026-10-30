"""`unseenet profile`, `follow`, `unfollow`, `following`, `timeline`, `address`, `open`.

Belongs here: your profile and picture (UN-RFC 0022), following feeds and people and
the timeline (UN-RFC 0034 sections 6, 7), and ``unseenet:`` addresses (UN-RFC 0031
section 3.4.1) - all through ``Session`` (``profiles.py``, ``following.py``) and
``core.addresses``.

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from ..core import markup
from .. import cli as _c   # names tests patch on the module, read at call time


def _is_group(text: str) -> bool:
    from ..core import addresses as addr
    if text.lower().startswith(addr.SCHEME):
        try:
            return addr.parse(text).kind != "identity"
        except addr.AddressError:
            return False
    try:
        split_group_id(text)
        return True
    except ValueError:
        return False


def _group_of(text: str) -> str:
    from ..core import addresses as addr
    return addr.parse(text).group_id if text.lower().startswith(addr.SCHEME) else text


def _confirm(args, warning: str, question: str) -> None:
    print(warning + "\n", file=sys.stderr)
    if getattr(args, "yes", False):
        return
    if not sys.stdin.isatty():
        sys.exit("Not done. Add --yes to confirm when not running interactively.")
    if input(question + " [y/N] ").strip().lower() not in ("y", "yes"):
        sys.exit("Not done.")


async def c_profile(app: App, args) -> None:
    """``unseenet profile [--about ...] [--link KIND=VALUE] [--lang ..] [--feed GID]
    [--picture FILE] [--bot | --no-bot]``: show your profile, or publish it - after the
    warning that a public profile is public (UN-RFC 0022 section 5.3). ``--of`` shows
    someone's. ``--bot`` sets the bot mark, ``--no-bot`` takes it away; without either
    the mark the profile has is kept (#801)."""
    from ..client.session import SessionError
    from ..core import profiles as prof
    s = _session(app, args)
    try:
        if getattr(args, "of", None):
            fp, key, _ = await s._resolve_person(args.of)
            m = await s.fetch_manifest(f"profile@{fp}")
            p = prof.profile_from_manifest(m) if m is not None else None
            data = (p.raw if p else None) or {}
            emit(args, json.dumps(data, indent=2, ensure_ascii=False) if data else "No public profile.",
                 {"fingerprint": fp, "profile": data or None})
            return
        bot = getattr(args, "bot", None)
        changes = any(getattr(args, k, None) for k in ("about", "link", "lang", "feed")) \
            or getattr(args, "empty", False) or bot is not None
        picture = getattr(args, "picture", None)
        if changes or picture or getattr(args, "remove_picture", False):
            _confirm(args, prof.PROFILE_WARNING, "Publish it?")
        if changes:
            if getattr(args, "empty", False):
                await s.publish_profile(None)
            else:
                old = s.my_profile() or {}
                links = old.get("links", [])
                if args.link:
                    links = [{"kind": k, "value": v} for k, _, v in (x.partition("=") for x in args.link)]
                obj = prof.make_profile(
                    about=args.about if args.about is not None else old.get("about", ""),
                    links=links, lang=args.lang or old.get("lang"),
                    feeds=args.feed or old.get("feeds"),
                    markdown=bool(getattr(args, "markdown", False)),
                    bot=bool(old.get("bot")) if bot is None else bot)
                await s.publish_profile(obj)
        if picture:
            await s.publish_picture_file(picture, getattr(args, "alt", None) or "")
        elif getattr(args, "remove_picture", False):
            await s.publish_picture(None)
    except (SessionError, prof.ProfileError, ValueError) as exc:
        sys.exit(f"Not published: {exc}")
    mine = s.my_profile()
    emit(args, json.dumps(mine, indent=2, ensure_ascii=False) if mine else "No public profile.",
         {"fingerprint": s.identity().fingerprint, "profile": mine})


async def c_follow(app: App, args) -> None:
    """``unseenet follow TARGET``: follow a feed (a Group ID or its address), or a
    person (a key, a fingerprint, ``unseenet:<fp>`` or a name). Nobody is told."""
    from ..client.session import SessionError
    s = _session(app, args)
    try:
        if _is_group(args.target):
            gid = _group_of(args.target)
            s.follow_feed(gid)
            emit(args, f"Following {gid}", {"group": gid})
            return
        r = await s.follow_person(args.target)
    except (SessionError, ValueError) as exc:
        sys.exit(f"Not followed: {exc}")
    who = r["name"] or (s.label_of(r["key"]) if r["key"] else r["fingerprint"])
    text = f"Following {who}: " + (", ".join(r["feeds"]) if r["feeds"] else "no feeds yet")
    emit(args, text, r)


async def c_unfollow(app: App, args) -> None:
    """``unseenet unfollow TARGET``: stop following a feed or a person (the feeds
    followed only because of them go too)."""
    from ..client.session import SessionError
    s = _session(app, args)
    try:
        if _is_group(args.target):
            gid = _group_of(args.target)
            s.follow_feed(gid, on=False)
            emit(args, f"No longer following {gid}", {"group": gid})
            return
        gone = await s.unfollow_person(args.target)
    except (SessionError, ValueError) as exc:
        sys.exit(f"Not done: {exc}")
    emit(args, "No longer following" + (": " + ", ".join(gone) if gone else ""), {"unsubscribed": gone})


async def c_following(app: App, args) -> None:
    """``unseenet following [--refresh]``: the people and feeds you follow; with
    ``--refresh``, read their profiles again first and follow their new feeds."""
    s = _session(app, args)
    new = await s.refresh_following() if getattr(args, "refresh", False) else []
    people, feeds = s.following(), s.feeds_followed()
    lines = [f"{p['label']}  ({p['fingerprint']})" + "".join(f"\n    {g}" for g in p["feeds"]) for p in people]
    own = [g for g in feeds if not any(g in p["feeds"] for p in people)]
    lines += [f"{g}" for g in own]
    emit(args, "\n".join(lines) or "You follow nobody yet.",
         {"people": people, "feeds": feeds, "new": new})


async def c_timeline(app: App, args) -> None:
    """``unseenet timeline [--limit N]``: the entries of every group in your timeline,
    newest first, as written (UN-RFC 0034 section 7). ``timeline groups`` lists which
    groups are in it; ``timeline add|remove|default GROUP`` chooses (section 6.2)."""
    from ..client.session import SessionError
    s = _session(app, args)
    what = getattr(args, "what", None) or "show"
    await s.fetch_unknown_manifests()          # a feed followed but not read yet
    if what == "groups":
        rows = [{"group": g, "label": s.group_label(g), "in": s.in_timeline(g),
                 "default": s.timeline_default(g)}
                for g in s.data["subscribed"] if s.timeline_possible(g)]
        lines = [f"{'in ' if r['in'] else 'out'}  {r['label']}"
                 + ("" if r["in"] == r["default"] else "  (your choice)") for r in rows]
        emit(args, "\n".join(lines) or "You follow no group that can be in the timeline.",
             {"groups": rows})
        return
    if what in ("add", "remove", "default"):
        if not getattr(args, "group", None):
            sys.exit(f"Which group? unseenet timeline {what} GROUP")
        gid = _group_of(args.group)
        try:
            on = s.set_in_timeline(gid, {"add": True, "remove": False, "default": None}[what])
        except SessionError as exc:
            sys.exit(str(exc))
        emit(args, f"{s.group_label(gid)} is {'in' if on else 'not in'} your timeline.",
             {"group": gid, "in": on})
        return
    for gid in s.timeline_groups():
        try:
            await s.fetch_group(gid)
        except Exception as exc:  # noqa: BLE001 - one feed that cannot be read is skipped
            print(f"{gid}: {exc}", file=sys.stderr)
    limit = getattr(args, "limit", None) or 50
    scored = s.scored_timeline(limit)            # your own rules, if any (UN-RFC 0051)
    rules = bool(s.rule_set())
    out = []
    for m, res in scored:
        row = {"id": m.message_id, "feed": m.group, "feed_label": s.group_label(m.group),
               "author": s.label_of(m.author_key), "date": m.date.isoformat() if m.date else None,
               "subject": m.subject, "text": m.body.strip().splitlines()[0][:120] if m.body.strip() else ""}
        if m.readable and m.body.strip():         # the shared cut, as the clients show it (#781)
            p = markup.preview(m.body.strip(), m.content_type, "post", lines=10, width=72)
            row.update(preview=p["text"], cut=p["cut"])
        if rules:
            row.update(score=res.score, why=res.explain())
        out.append(row)
    lines = []
    for r in out:
        score = f"{r['score']:+5d}  " if rules else ""
        lines.append(f"{score}{r['date'][:16] if r['date'] else '?':16}  {r['feed_label']:24}  "
                     f"{r['author']}: {r['subject'] or r['text']}")
        if rules and getattr(args, "why", False):
            lines += ["        " + ln for ln in r["why"].splitlines()]
    emit(args, "\n".join(lines) or "The timeline is empty.", {"entries": out, "rules": rules})


async def c_rules(app: App, args) -> None:
    """``unseenet rules [show | help | set [FILE] | check [FILE] | on | off | clear]``: your own
    rules for your feed and groups (UN-RFC 0051) - they run only here and go with your
    identity. ``set`` and ``check`` read FILE, or stdin when it is ``-`` or missing;
    ``off`` keeps the text to turn on again; ``clear`` removes them."""
    s = _session(app, args)
    what = getattr(args, "what", None) or "show"
    if what == "help":                        # the language in short (UN-RFC 0051)
        from ..client.scoring import HELP
        emit(args, HELP.rstrip("\n"), {"help": HELP})
        return
    if what in ("set", "check"):
        src = getattr(args, "file", None) or "-"
        text = sys.stdin.read() if src == "-" else Path(src).read_text()
        rs = s.check_feed_rules(text) if what == "check" else s.set_feed_rules(text)
    elif what in ("on", "off"):
        s.set_rules_on(what == "on")
        rs = s.check_feed_rules(s.feed_rules())
    elif what == "clear":
        rs = s.set_feed_rules("")
    else:
        rs = s.check_feed_rules(s.feed_rules())
    problems = [{"line": p.line, "message": p.message} for p in rs.problems]
    state = "on" if s.rules_on() else "off (kept)"
    if what == "show":
        text = (s.feed_rules().rstrip("\n") + "\n\n" if s.feed_rules() else "No rules: the feed is "
                "newest first and threads are as they are.\n")
        text += f"{len(rs.rules)} rule(s) used, {state}."
    else:
        verb = {"set": "Kept", "check": "Checked", "on": "Turned on", "off": "Turned off",
                "clear": "Removed"}[what]
        text = f"{verb}: {len(rs.rules)} rule(s) used" + ("" if what == "clear" else f", {state}") + "."
    if problems:
        text += "\n" + "\n".join(f"line {p['line']}: {p['message']}" for p in problems)
    emit(args, text, {"text": s.feed_rules(), "on": s.rules_on(), "rules": len(rs.rules),
                      "problems": problems})
    if what == "check" and problems:
        sys.exit(1)


async def c_thread(app: App, args) -> None:
    """``unseenet thread watch|ignore|clear MSGID``: watch a thread (its replies land in
    For you), ignore it, or neither - kept in your state (UN-RFC 0044 section 4.5)."""
    s = _session(app, args)
    mid = args.msgid if args.msgid.startswith("<") else f"<{args.msgid}>"
    s.set_thread_mark(mid, "" if args.what == "clear" else
                      {"watch": "watched", "ignore": "ignored"}[args.what])
    mark = s.thread_mark(mid)
    emit(args, f"{mid}: {mark or 'neither watched nor ignored'}", {"id": mid, "mark": mark})


async def c_address(app: App, args) -> None:
    """``unseenet address [GROUP [--message MSGID | --page PATH]] [--node ONION]``: the
    ``unseenet:`` address of a group, a post or a page - or, without GROUP, yours."""
    from ..core import addresses as addr
    s = _session(app, args)
    nodes = [args.node] if getattr(args, "node", None) else []
    if not getattr(args, "group", None):
        text = addr.identity_address(s.identity().fingerprint, nodes)
    else:
        try:
            split_group_id(args.group)
        except ValueError:
            sys.exit(f"{args.group!r} is not a group ID")
        if getattr(args, "message", None):
            mid = args.message if args.message.startswith("<") else f"<{args.message}>"
            text = addr.post_address(args.group, mid, nodes)
        elif getattr(args, "page", None):
            text = addr.page_address(args.group, args.page, nodes)
        else:
            text = addr.group_address(args.group, nodes)
    emit(args, text, {"address": text})


async def c_open(app: App, args) -> None:
    """``unseenet open ADDRESS [--follow]``: say what an ``unseenet:`` address names -
    an identity, a group, a post or a page - fetching it; ``--follow`` follows it."""
    from ..client.session import SessionError
    from ..core import addresses as addr
    s = _session(app, args)
    try:
        a = addr.parse(args.address)
    except addr.AddressError as exc:
        sys.exit(f"Not an address: {exc}")
    out: dict = {"kind": a.kind, "address": str(a), "nodes": list(a.nodes)}
    try:
        if a.kind == "identity":
            out["fingerprint"] = a.fingerprint
            if getattr(args, "follow", False):
                out["following"] = await s.follow_person(a.fingerprint)
            text = f"An identity: {a.fingerprint}"
        else:
            m = await s.fetch_manifest(a.group_id)
            if m is None:
                emit(args, f"{a.group_id} is not available on your nodes.", {**out, "available": False})
                return
            out.update({"group": a.group_id, "title": m.raw.get("title", ""), "type": m.type,
                        "view": m.view, "available": True})
            text = f"{a.group_id}: {m.raw.get('title') or m.name} ({m.type}{', ' + m.view if m.view else ''})"
            if a.kind in ("post", "page"):
                await s.fetch_group(a.group_id)
            if a.kind == "post":
                msg = s.find_message(a.group_id, a.message_id)
                out["subject"] = msg.subject if msg else None
                text += f"\n  post: {msg.subject if msg else a.message_id + ' (not available)'}"
            elif a.kind == "page":
                page = next((p for p in s.site(a.group_id)["pages"] if p["path"] == a.path), None)
                out["title_of_page"] = page["title"] if page else None
                text += f"\n  page {a.path}: {page['title'] if page else '(not available)'}"
            if getattr(args, "follow", False):
                s.follow_feed(a.group_id)
                out["following"] = True
                text += "\n  now followed"
    except SessionError as exc:
        sys.exit(f"Not opened: {exc}")
    emit(args, text, out)


__all__ = ['c_profile', 'c_follow', 'c_unfollow', 'c_following', 'c_timeline', 'c_rules', 'c_thread', 'c_address',
           'c_open', '_is_group', '_group_of', '_confirm']
