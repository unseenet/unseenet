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
        self._writes_pages(group_id)
        await self.fetch_group(group_id)                 # the versions in force
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
