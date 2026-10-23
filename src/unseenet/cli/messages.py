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
    from ..core import portals
    author = app.identity(args.identity)
    entry = app.data["groups"].get(args.group, {})
    found = portals.portals(entry.get("manifest") or {})
    if found and not args.publish_outside_tor:      # UN-RFC 0023 section 3.5
        sys.exit(portals.warning(args.group.rpartition("@")[0], found)
                 + "\n\nAdd --publish-outside-tor to post anyway.")
    body = sys.stdin.read() if args.body is None else args.body
    if getattr(args, "attach", None):
        await _post_with_files(app, args, author, body)
        return
    if entry.get("type") == "closed":
        epoch = max(int(e) for e in entry["keys"])
        keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))
        art = encrypted_article(args.group, epoch, keys, author, from_name=app.display_name(args.identity),
                                subject=args.subject, body=body,
                                pow_bits=await app.bits(args.group, author))
    else:
        art = new_article(args.group, args.subject, body, from_name=app.display_name(args.identity))
        art.finalize(author, await app.bits(args.group, author))
    await app.post(art)


async def _post_with_files(app: App, args, author, body: str) -> None:
    """For testing nodes only (#148): upload files with BLOBPOST and post an article
    that references them (UN-RFC 0027). Plain groups only; the clients' real
    attachments are #149 and unseenet-gui#63, with metadata removed first."""
    import mimetypes
    from ..core import blobs as bl
    if app.data["groups"].get(args.group, {}).get("type") in ("closed", "inbox"):
        sys.exit("--attach is a test tool for open groups; encrypted files come with the clients")
    if len(args.attach) > bl.MAX_PER_ARTICLE:
        sys.exit(f"at most {bl.MAX_PER_ARTICLE} files")
    files = [(Path(f).name, Path(f).read_bytes()) for f in args.attach]
    headers = [("Blobs", " ".join(f"{bl.blob_id(d)}={len(d)}" for _, d in files))]
    for i, (name, data) in enumerate(files, 1):
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        headers.append((f"Attachment-{i}", f"{bl.blob_id(data)}; type={mime}; size={len(data)}; "
                                           f"name={crypto.b64(name.encode()[:128])}"))
    art = new_article(args.group, args.subject, body, from_name=app.display_name(args.identity),
                      extra=headers)
    art.finalize(author, await app.bits(args.group, author) + bl.extra_bits(art))
    header = app.session.ripening_header()
    if header:
        art.set("Key-Ripening", header)
    async with app.connect() as c:
        for _, data in files:
            bid = bl.blob_id(data)
            code, text = await c.command(f"BLOBPOST {bid} {len(data)}")
            if code == 345:
                c.writer.write(data)
                await c.writer.drain()
                code, text = await c._response()
            if code != 245:
                sys.exit(f"The node did not take {bid}: {code} {text}")
        code, text = await c.post(art.to_bytes())
    if code != 240:
        sys.exit(f"Rejected: {code} {text}")
    print(f"Posted {art.message_id} with {len(files)} file(s)")


async def c_read(app: App, args) -> None:
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


__all__ = ['c_withdraw', 'c_post', '_post_with_files', 'c_read']
