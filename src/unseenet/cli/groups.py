"""`unseenet groups`, `group-create`, `group-edit`, `group-show`, `group-remove`, `invite`.

Belongs here: listing groups, creating and changing them through ``Session``
(``create_group``, ``update_group``: roles, bans, settings and the 0.5.0 fields, one
new manifest per change), showing a manifest, removing a group for good (UN-RFC 0013),
inviting to a closed group, and the options ``group-create`` and ``group-edit`` share
(``_group_options``).

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

import re

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # names tests patch on the module, read at call time
from ..core.addresses import group_address


async def c_groups(app: App, args) -> None:
    """``unseenet groups [PATTERN] [--mine]``: the groups the node carries; ``--mine``
    only those an identity in this vault owns."""
    async with app.connect() as c:
        lines = await c.multiline(f"LIST NEWSGROUPS {args.pattern}", 215)
    for line in lines:
        gid, _, desc = line.partition("\t")
        if args.mine:
            owner = _owner_of(app, gid)
            if owner is None:
                continue
            desc = f"{desc}   [owned by {owner[0]}]"
        print(f"{short_group_id(gid):32} {desc}   ({gid})")


async def c_group_remove(app: App, args) -> None:
    """UN-RFC 0013: remove groups you own from the whole network. Final."""
    plan = []
    for gid in args.group:
        try:
            split_group_id(gid)
        except ValueError:
            sys.exit(f"{gid}: give the full group ID (name@fingerprint), "
                     "see 'unseenet groups --mine'")
        owner = _owner_of(app, gid)
        if owner is None:
            sys.exit(f"{gid}: none of the identities in this vault owns it")
        if gid == personal_inbox_id(owner[1].public_key):
            sys.exit(f"{gid}: a personal inbox cannot be removed")
        plan.append((gid, *owner))

    print("Removing a group is final: every node deletes it and its posts, and the")
    print("group ID can never be used again, not even by you. Saved copies remain.")
    for gid, name, _ in plan:
        print(f"  {gid}   (owner: {name})")
    if not args.yes:
        if not sys.stdin.isatty():
            sys.exit("Not removed. Add --yes to confirm when not running interactively.")
        if input("Type 'remove' to go ahead: ").strip() != "remove":
            sys.exit("Not removed.")

    reason = (args.reason or "Removed by its owner.").rstrip("\n") + "\n"
    for gid, _, ident in plan:
        art = new_article(gid, None, reason, extra=[("Control", "rmgroup")])
        art.finalize(ident, await app.bits(None, ident))
        await app.post(art)
        if gid in app.data.get("subscribed", []):
            app.data["subscribed"].remove(gid)
        app.data["groups"].pop(gid, None)
        app.vault.save()
        print(f"Removed {gid}")


def _group_fields(args) -> tuple[dict, dict]:
    """(Session.update_group/create_group fields, extra manifest fields) from options."""
    fields, extra = {}, {}
    for opt, key in (("title", "title"), ("description", "description"), ("min_pow", "min_pow"),
                     ("retention_days", "retention_days"), ("view", "view"),
                     ("comments", "comments"), ("comment_days", "comment_days")):
        value = getattr(args, opt, None)
        if value is not None:
            fields[key] = value
    if getattr(args, "kinds", None):
        fields["kinds"] = [k.strip() for k in args.kinds.split(",") if k.strip()]
    if getattr(args, "charter", None):                       # UN-RFC 0014
        text = sys.stdin.read() if args.charter == "-" else Path(args.charter).read_text()
        fields["charter"] = text
        fields["charter_type"] = ("text/markdown; charset=utf-8; variant=unseenet"
                                  if args.charter.endswith(".md") else None)
    if getattr(args, "attachments", None) is not None:
        extra["attachments"] = None if args.attachments == 0 else (
            {"max_size": args.attachments} | ({"types": args.types.split(",")} if args.types else {}))
    for opt in ("max_pins", "max_pages", "home", "index"):
        if getattr(args, opt, None) is not None:
            extra[opt] = getattr(args, opt)
    r = getattr(args, "reactions", None)                     # UN-RFC 0048 section 4
    if r is not None:
        extra["reactions"] = {"default": None, "none": [], "any": "any"}.get(
            r, [e.strip() for e in r.split(",") if e.strip()])
    return fields, extra


async def c_group_show(app: App, args) -> None:
    """The group's current manifest: who owns it, who may post, and its settings."""
    from ..client.session import SessionError
    try:
        m = await _session(app, args).fetch_manifest(args.group)
    except SessionError as exc:
        sys.exit(f"Could not read the manifest: {exc}")
    if m is None:
        sys.exit("The node does not carry that group.")
    emit(args, json.dumps(m.raw, indent=2, ensure_ascii=False), m.raw)


async def c_group_edit(app: App, args) -> None:
    """A new manifest for a group you own (UN-RFC 0004 section 4): roles, bans and
    settings, all in one."""
    from ..client.session import SessionError
    s = _session(app, args)
    try:
        await s.fetch_manifest(args.group)
        data = s.manifest_data(args.group)
        if not data:
            sys.exit("The node does not carry that group.")
        fields, extra = _group_fields(args)
        fields |= extra
        for role, add, remove in (("posters", args.add_poster, args.remove_poster),
                                  ("moderators", args.add_moderator, args.remove_moderator)):
            if add or remove:
                keys = [k for k in data.get(role, []) if k not in (remove or [])]
                fields[role] = keys + [k for k in (add or []) if k not in keys]
        add, remove = getattr(args, "add_report_issuer", None), getattr(args, "remove_report_issuer", None)
        if add or remove:                         # UN-RFC 0045 section 7.5
            keys = [k for k in data.get("report_issuers", []) if k not in (remove or [])]
            keys += [crypto.key_to_text(crypto.key_from_text(k)) for k in (add or []) if k not in keys]
            fields["report_issuers"] = keys or None
        if getattr(args, "languages", None) is not None:          # UN-RFC 0052 section 5a
            from ..core import tags as tg2
            fields["languages"] = tg2.normalize_languages(args.languages.split(",")) or None
        if getattr(args, "tags", None) is not None:               # UN-RFC 0052 section 5
            from ..core import tags as tg
            fields["tags"] = tg.normalize(args.tags.split(",")) or None
        if getattr(args, "team_name", None) is not None:          # UN-RFC 0047 section 3
            fields["team_name"] = args.team_name.strip() or None
        if args.ban or args.unban:
            banned = [b for b in data.get("banned", []) if isinstance(b, dict)
                      and b.get("key") not in (args.unban or []) and b.get("key") not in (args.ban or [])]
            for key in args.ban or []:
                crypto.key_from_text(key)
                entry = {"key": key}
                if args.reason:
                    entry["reason"] = args.reason[:200]
                banned.append(entry)
            fields["banned"] = banned
        if not fields:
            sys.exit("Nothing to change.")
        new = await s.update_group(args.group, **fields)
    except (SessionError, ValueError, crypto.CryptoError) as exc:
        sys.exit(f"Not changed: {exc}")
    emit(args, f"Changed {args.group} (serial {new['serial']})", new)


async def c_group_create(app: App, args) -> None:
    """``unseenet group-create NAME --type ...``: create a group you own, with the
    settings of ``_group_options``, through ``Session.create_group``. Prints its Group ID."""
    from ..client.session import SessionError
    fields, extra = _group_fields(args)
    s = _session(app, args)
    try:
        gid = await s.create_group(
            args.name, args.type, title=fields.get("title", ""),
            description=fields.get("description", ""), min_pow=fields.get("min_pow", 20),
            local=getattr(args, "local", False), retention_days=fields.get("retention_days"),
            charter=fields.get("charter", ""), charter_type=fields.get("charter_type"),
            view=fields.get("view"), kinds=fields.get("kinds"),
            comments=fields.get("comments") if args.type == "channel" else None,
            comment_days=fields.get("comment_days") if args.type == "channel" else None,
            moderators=getattr(args, "moderator", None) or [],
            posters=getattr(args, "poster", None) or [], extra=extra or None)
    except (SessionError, ValueError) as exc:
        sys.exit(f"Not created: {exc}")
    emit(args, f"Created {gid}", {"group": gid})


async def c_invite(app: App, args) -> None:
    """``unseenet invite GROUP KEY``: owner of a closed group - give a key access, and
    print the invitation to share."""
    owner = app.identity(args.identity)
    entry = app.data["groups"].get(args.group)
    if not entry or not entry.get("owner") or entry["type"] != "closed":
        sys.exit("You can only invite to closed groups you own.")
    epoch = max(int(e) for e in entry["keys"])
    keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))
    member = crypto.key_from_text(args.key)
    await app.post(make_key_update(owner, args.group, epoch, keys, [member], grant_only=True,
                                   pow_bits=await app.bits(args.group, owner)))
    node = app.data["nodes"][0] if app.data["nodes"] else None
    hints = [node] if node and re.match(r"^[a-z2-7]{56}\.onion(:\d{1,5})?$", node.lower()) else []
    print(f"Invite sent. Share this with the new member:\n  {group_address(args.group, hints)}")


def _group_options(s, *, create: bool) -> None:
    """The settings group-create and group-edit share (UN-RFC 0004, 0008, 0027-0035, 0048)."""
    s.add_argument("--title")
    s.add_argument("--description")
    s.add_argument("--min-pow", type=int, help="postage in bits (create: default 20)")
    s.add_argument("--retention-days", type=int, help="how long posts circulate (UN-RFC 0012)")
    s.add_argument("--view", choices=["threads", "chat", "feed", "pages"],
                   help="how the group is shown (pages: channels only)")
    s.add_argument("--kinds", help="chat, post or chat,post (UN-RFC 0028)")
    s.add_argument("--charter", metavar="FILE",
                   help="the group's charter - what it is for and asks of those who write "
                        "(UN-RFC 0014) - from a file (.md: Markdown), - for stdin")
    s.add_argument("--comments", choices=["none", "open"],
                   help="channels: whether readers may comment on posts (UN-RFC 0030)")
    s.add_argument("--comment-days", type=int,
                   help="channels: days after a post during which it takes comments")
    s.add_argument("--attachments", type=int, metavar="MAX_SIZE",
                   help="allow files up to this many octets (UN-RFC 0027); 0 to stop")
    s.add_argument("--types", help="with --attachments: allowed media types, e.g. image/*,application/pdf")
    s.add_argument("--max-pins", type=int, help="pins in force, 0-25 (UN-RFC 0033)")
    s.add_argument("--reactions", metavar="SET",
                   help="reactions the group takes (UN-RFC 0048): default (feeds and chat "
                        "👍 👎 ❤️ 😂 😮 😢, discussions none), none, any, or emoji like 🎉,❤️")
    s.add_argument("--max-pages", type=int, help="sites: pages in force, 1-100 (UN-RFC 0035)")
    s.add_argument("--home", help="sites: the path of the home page")
    s.add_argument("--index", choices=("yes", "no"),
                   help="sites: may search engines index the site when an entrance shows it on "
                        "the web (UN-RFC 0035; default no - copies outlive expiry)")


__all__ = ['c_groups', 'c_group_remove', '_group_fields', 'c_group_show', 'c_group_edit', 'c_group_create', 'c_invite', '_group_options']
