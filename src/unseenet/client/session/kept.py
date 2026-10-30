"""Kept articles in a client (UN-RFC 0017 section 2.1): pinned posts and the pages of sites.

Belongs here: which posts are pinned in a group (``pins``, UN-RFC 0033) and pinning
or unpinning one (``pin``); the pages of a site - each path's current and previous
version and the pages in force (``site``, UN-RFC 0035) - and writing or removing a
page (``put_page``, ``remove_page``). They are worked out from what the client has
read with the same rules every node uses (``core.pins``, ``core.pages``), so a
client shows what the nodes keep.

Not here: the markers and page articles as they are read (reading.py), personal
sites (personal.py).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from ...core import blobs as bl
from .. import session as _s   # names tests patch on the module, read at call time


class KeptMixin:
    # --- pins (UN-RFC 0033) ---
    def _markers(self, group_id: str):
        from ...core import pins as pn
        return [pn.Marker(mid, m["target"], m["action"], m["by"], int(m["date"]),
                          tuple(m.get("supersedes") or ()))
                for mid, m in self.group_entry(group_id).get("markers", {}).items()]

    def pins(self, group_id: str) -> list[dict]:
        """The pinned posts of a group, newest pin first: ``{"id", "note", "by",
        "pinned"}`` with the pinned post's Message-ID. Only pins by the owner and
        moderators of the current manifest count, at most its ``max_pins``, and not
        of withdrawn posts (UN-RFC 0033 section 4.2)."""
        from ...core import pins as pn
        data = self.manifest_data(group_id)
        if not data.get("owner"):
            return []
        try:
            limit = pn.max_pins(data)
        except ValueError:
            limit = pn.MAX_PINS_DEFAULT
        entry = self.group_entry(group_id)
        withdrawn = set(entry.get("cancels", {}))
        notes = entry.get("markers", {})
        return [{"id": m.target, "note": notes.get(m.message_id, {}).get("note", ""),
                 "by": m.author_key, "pinned": datetime.fromtimestamp(m.date, timezone.utc)}
                for m in pn.in_force(self._markers(group_id), owner=data["owner"],
                                     moderators=data.get("moderators", []), limit=limit,
                                     withdrawn=withdrawn)]

    async def pin(self, group_id: str, message_id: str, note: str = "", *,
                  unpin: bool = False) -> str:
        """Owner or moderator: pin a post at the top of the group, kept beyond its
        window, with an optional ``note`` (or unpin it, ``unpin=True``). The marker
        names the one it replaces (UN-RFC 0033 section 3.1). Returns its Message-ID."""
        from ...core import pins as pn
        if not self.moderates_or_owns(group_id):
            raise SessionError("only the owner or a moderator can pin posts")
        target = message_id if message_id.startswith("<") else f"<{message_id}>"
        data = self.manifest_data(group_id)
        if not unpin and pn.max_pins(data) == 0:
            raise SessionError("this group takes no pins (its max_pins is 0)")
        allowed = {data.get("owner"), *data.get("moderators", [])}
        now = pn.current(self._markers(group_id), allowed).get(target)
        if unpin and (now is None or now.action != pn.PIN):
            raise SessionError("that post is not pinned")
        me = self.identity()
        art = pn.pin_article(me, group_id, target, unpin=unpin, note=note,
                             replaces=[now.message_id] if now else (),
                             pow_bits=await self.required_pow(group_id))
        mid = await self.post_article(art, sign_with=me)
        self.group_entry(group_id).setdefault("markers", {})[mid] = {
            "target": target, "action": pn.UNPIN if unpin else pn.PIN, "by": me.key_text,
            "date": int(parse_date(art["Date"]).timestamp()),
            "supersedes": [now.message_id] if now else [], "note": note.strip()}
        self.save()
        return mid

    # --- comments on one entry (UN-RFC 0030 sections 3.1-3.3) ---
    def _comment_markers(self, group_id: str):
        from ...core import pins as pn
        return [pn.Marker(mid, m["target"], m["action"], m["by"], int(m["date"]),
                          tuple(m.get("supersedes") or ()))
                for mid, m in self.group_entry(group_id).get("comment_markers", {}).items()]

    def _thread_versions(self, group_id: str, root_id: str) -> list:
        """The thread root ``root_id`` (its first version) and its edits, as read."""
        return [m for m in self.cache.get(group_id, {}).values()
                if m.message_id == root_id or root_id in (m.supersedes or ())]

    def comment_root(self, group_id: str, message_id: str) -> str:
        """The Message-ID comments name for a thread root shown as ``message_id`` (an
        edit names its first version last, UN-RFC 0042). SessionError for a reply."""
        mid = message_id if message_id.startswith("<") else f"<{message_id}>"
        msg = self.find_message(group_id, mid)
        if msg is None:
            return mid
        if msg.references:
            raise SessionError("comments are closed and opened on a thread's first post")
        return msg.supersedes[-1] if msg.supersedes else msg.message_id

    def comments_state(self, group_id: str, message_id: str,
                       now: datetime | None = None) -> dict:
        """Whether a thread takes comments now (UN-RFC 0030): ``{"open", "reason",
        "until", "note", "by", "own_days", "group_days"}`` - ``reason`` ``"deadline"`` or
        ``"closed"`` when not open, ``until`` when comments close (None: no deadline),
        ``note`` and ``by`` of a close, ``own_days`` the entry's own Comment-Days."""
        from ...core import comments as cm
        from ...core.groups import COMMENT_DAYS_TYPES
        data = self.manifest_data(group_id)
        out = {"open": True, "reason": None, "until": None, "note": "", "by": None,
               "own_days": None, "group_days": None}
        gtype = data.get("type") or self.group_entry(group_id).get("type")
        if gtype not in COMMENT_DAYS_TYPES or data.get("local"):
            return out
        root_id = self.comment_root(group_id, message_id)
        versions = self._thread_versions(group_id, root_id)
        root = next((m for m in versions if m.message_id == root_id), None)
        dates = [m.date for m in versions if m.date is not None]
        group_days = data.get("comment_days") if isinstance(data.get("comment_days"), int) else None
        own = cm.shorter(*(m.comment_days for m in versions))
        if gtype == "channel" and data.get("comments") != "open":
            own = None                                   # ignored there (section 3.1)
        out.update(own_days=own, group_days=group_days)
        if dates:
            out["until"] = cm.deadline(min(dates), group_days, own)
            if cm.closed_by_time(now or datetime.now(timezone.utc), min(dates), group_days, own):
                out.update(open=False, reason="deadline")
                return out
        elif own == 0:
            out.update(open=False, reason="deadline")
            return out
        author = (root or (versions[0] if versions else None))
        if author is None or not data.get("owner"):
            return out
        close = cm.deciding_close(self._comment_markers(group_id), root_id, author.author_key,
                                  {data["owner"], *data.get("moderators", [])})
        if close is not None:
            note = self.group_entry(group_id).get("comment_markers", {}) \
                .get(close.message_id, {}).get("note", "")
            out.update(open=False, reason="closed", note=note, by=close.author_key)
        return out

    def may_close_comments(self, group_id: str, message_id: str) -> bool:
        """Whether you may close or open comments on this entry: its author, the owner or
        a moderator, in a group that has comments to close."""
        from ...core.groups import COMMENT_DAYS_TYPES
        data = self.manifest_data(group_id)
        if (data.get("type") or self.group_entry(group_id).get("type")) not in COMMENT_DAYS_TYPES \
                or data.get("local"):
            return False
        try:
            root_id = self.comment_root(group_id, message_id)
        except SessionError:
            return False
        root = next((m for m in self._thread_versions(group_id, root_id)
                     if m.message_id == root_id), None)
        me = self.identity().key_text
        if root is None:                     # not read back yet: one you just posted
            return self.moderates_or_owns(group_id) or root_id in self.data.get("mine", [])
        return self.moderates_or_owns(group_id) or root.author_key == me

    async def close_comments(self, group_id: str, message_id: str, note: str = "", *,
                             reopen: bool = False) -> str:
        """Close comments on an entry (or open them again, ``reopen=True``) with an
        optional note for readers (UN-RFC 0030 section 3.2): its author, the owner or a
        moderator. The marker names the one it replaces in its chain - the author's own,
        or the owner's and moderators'. Returns its Message-ID."""
        from ...core import comments as cm
        from ...core import pins as pn
        if not self.may_close_comments(group_id, message_id):
            raise SessionError("only the entry's author, the owner or a moderator can close "
                               "or open its comments")
        data = self.manifest_data(group_id)
        if data.get("type") == "closed" and note.strip():
            raise SessionError("in a closed group a close has no note: nodes can read it")
        root_id = self.comment_root(group_id, message_id)
        me = self.identity()
        privileged = {data.get("owner"), *data.get("moderators", [])}
        chain = privileged if me.key_text in privileged else {me.key_text}
        markers = self._comment_markers(group_id)
        now = pn.current([m for m in markers if m.target == root_id], chain).get(root_id)
        if reopen and me.key_text not in privileged:
            held = cm.deciding_close(markers, root_id, me.key_text, privileged)
            if held is not None and held.author_key in privileged:
                raise SessionError("the owner or a moderator closed it: only they can open it")
        try:
            art = cm.marker_article(me, group_id, root_id, close=not reopen, note=note,
                                    replaces=[now.message_id] if now else (),
                                    pow_bits=await self.required_pow(group_id))
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        mid = await self.post_article(art, sign_with=me)
        self.group_entry(group_id).setdefault("comment_markers", {})[mid] = {
            "target": root_id, "action": cm.OPEN if reopen else cm.CLOSE, "by": me.key_text,
            "date": int(parse_date(art["Date"]).timestamp()),
            "supersedes": [now.message_id] if now else [], "note": note.strip()}
        self.save()
        return mid

    # --- sites (UN-RFC 0035) ---
    def _page_versions(self, group_id: str):
        from ...core import pages as pg
        gone = set(self.group_entry(group_id).get("cancels", {}))
        out = []
        for m in self.cache.get(group_id, {}).values():
            if m.page and m.date is not None and m.message_id not in gone:
                out.append(pg.Version(m.message_id, m.page, m.author_key, int(m.date.timestamp()),
                                      m.page_removed, tuple(m.supersedes)))
        return out

    def site(self, group_id: str) -> dict:
        """A site's pages as every client shows them: ``{"home", "pages"}``, ``pages``
        the paths in force (UN-RFC 0035 section 5.2, the home page first), each
        ``{"path", "title", "current", "previous"}`` with Messages. Only versions by
        the site's writers now count, so a removed writer's edits fall back."""
        from ...core import pages as pg
        data = self.manifest_data(group_id)
        home = data.get("home", pg.HOME_DEFAULT)
        if data.get("view") != "pages":
            return {"home": home, "pages": []}
        allowed = {data.get("owner"), *data.get("moderators", []), *data.get("posters", [])}
        currents = pg.current_versions(self._page_versions(group_id), allowed)
        by_id = {m.message_id: m for m in self.cache.get(group_id, {}).values()}
        out = []
        for path in pg.in_force(currents, max_pages=data.get("max_pages", pg.MAX_PAGES_DEFAULT),
                                home=home):
            cur, prev = currents[path]
            msg = by_id.get(cur.message_id)
            out.append({"path": path, "title": msg.subject if msg else path, "current": msg,
                        "previous": by_id.get(prev.message_id) if prev else None})
        return {"home": home, "pages": out}

    def _writes_pages(self, group_id: str) -> None:
        data = self.manifest_data(group_id)
        if data.get("view") != "pages":
            raise SessionError("this group is not a site")
        me = self.identity().key_text
        if me != data.get("owner") and me not in data.get("moderators", []) \
                and me not in data.get("posters", []):
            raise SessionError("only the site's writers write its pages")

    def _versions_of(self, group_id: str, path: str) -> list[str]:
        """The versions of a path this client knows, newest first, at most 32 - what a
        new version or a removal names in Supersedes (UN-RFC 0035 section 4.4)."""
        vs = sorted((v for v in self._page_versions(group_id) if v.path == path),
                    key=lambda v: v.newest_first)
        return [v.message_id for v in vs][:32]

    async def put_page(self, group_id: str, path: str, text: str, title: str = "", *,
                       content_type: str | None = None, files=None) -> str:
        """Write a page of a site you write in: its first version, or a new one naming
        the versions it replaces. ``title`` defaults to the path; ``files`` are prepared
        files (``prepare_files``) its images point at by blob ID (UN-RFC 0031 section
        3.5). Read the site first (``fetch_group``) so the current version is named.
        Returns its Message-ID."""
        from ...core import pages as pg
        self._writes_pages(group_id)
        if not pg.valid_path(path):
            raise SessionError("a path is 1-8 parts of a-z 0-9 - _ . separated by /")
        if len(text.encode()) > pg.MAX_BODY:
            raise SessionError(f"a page is at most {pg.MAX_BODY // 1024} KiB")
        title = (title or path).strip()[:pg.MAX_TITLE]
        return await self.post(group_id, title, text, content_type=content_type,
                               supersedes=self._versions_of(group_id, path) or None,
                               extra=[("Page", path)], files=files)

    async def publish_site(self, group_id: str, folder, *, dry_run: bool = False,
                           prune: bool = False, progress=None) -> dict:
        """Publish a folder of Markdown (and HTML) as the pages of a site you write in
        (#538, ``client.siteimport``): unchanged pages are left as they are, changed ones
        get a new version naming the old (UN-RFC 0042), new ones are put; with
        ``prune`` pages no longer in the folder are removed. ``dry_run`` does all but
        send. Answers ``{"plan", "changes": [{"path", "title", "action", "source",
        "files"}], "notes", "problems", "sent"}``; nothing is sent when there are
        problems. ``progress(done, total, path)`` is called as pages go."""
        from .. import siteimport
        # the manifest first: a writer whose vault has never seen the site (a CI poster's
        # throwaway vault) has nothing to check yet (unseenet-docs#7)
        await self.fetch_group(group_id)                 # the manifest, the versions in force
        self._writes_pages(group_id)
        plan = siteimport.plan(folder, self.manifest_data(group_id))
        current = {p["path"]: p["current"] for p in self.site(group_id)["pages"]}
        changes = []
        for page in plan.pages:
            cur = current.get(page.path)
            want = sorted(bl.blob_id(f.octets) for f in page.files)
            if cur is None:
                action = "new"
            elif (cur.subject == page.title and (cur.body or "").rstrip() == page.text.rstrip()
                  and sorted(a.get("blob", "") for a in cur.attachments) == want):
                action = "unchanged"
            else:
                action = "changed"
            changes.append({"path": page.path, "title": page.title, "action": action,
                            "source": page.source, "files": [f.name for f in page.files]})
        planned = {p.path for p in plan.pages}
        for path, cur in current.items():
            if path not in planned:
                changes.append({"path": path, "title": cur.subject,
                                "action": "remove" if prune else "kept", "source": None,
                                "files": []})
        out = {"changes": changes, "notes": [str(n) for n in plan.notes],
               "problems": list(plan.problems), "sent": 0}
        if dry_run or plan.problems:
            return out
        todo = [c for c in changes if c["action"] in ("new", "changed", "remove")]
        for i, c in enumerate(todo, 1):
            if progress is not None:
                progress(i - 1, len(todo), c["path"])
            if c["action"] == "remove":
                await self.remove_page(group_id, c["path"])
            else:
                page = plan.page(c["path"])
                await self.put_page(group_id, page.path, page.text, page.title,
                                    files=page.files or None)
            out["sent"] += 1
        if progress is not None and todo:
            progress(len(todo), len(todo), "")
        if todo:
            await self.fetch_group(group_id)             # the site as it now is
        return out

    async def remove_page(self, group_id: str, path: str) -> str:
        """Remove a page from a site (``Page-Removed``): its versions stop counting, and
        the removal is kept while inside the window. Returns its Message-ID."""
        self._writes_pages(group_id)
        versions = self._versions_of(group_id, path)
        if not versions:
            raise SessionError(f"there is no page {path} (read the site first)")
        return await self.post(group_id, path, "", content_type="text/plain; charset=utf-8",
                               supersedes=versions,
                               extra=[("Page", path), ("Page-Removed", "yes")])
