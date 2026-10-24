"""Sites and their pages in the local client API (UN-RFC 0046 section 4.15, UN-RFC 0035):
a site's pages in force, one page rendered with its links within the site resolved,
and writing, removing and restoring a page. Which version counts is ``Session.site``'s,
worked out with the rules every node uses.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from ....core import addresses as addr
from ....core import pages as pg


class Pages:
    @staticmethod
    def _site_data(s: Session, gid: str) -> dict:
        if gid not in s.data["groups"] and gid not in s.data["subscribed"]:
            raise NotFound("no such group")
        data = s.manifest_data(gid)
        if data.get("view") != "pages":
            raise SessionError("this group is not a site")
        return data

    @staticmethod
    def _may_write(s: Session, data: dict) -> bool:
        me = s.identity().key_text
        return me == data.get("owner") or me in data.get("moderators", []) \
            or me in data.get("posters", [])

    def site(self, gid: str) -> dict:
        """``GET /api/groups/{gid}/site`` (section 4.15): the site's pages in force, the
        home page first (UN-RFC 0035 section 5.2), with who wrote each current version,
        and whether you may write here."""
        s = self._ready()
        data = self._site_data(s, gid)
        site = s.site(gid)
        owner = data.get("owner")
        pages = []
        for p in site["pages"]:
            m = p["current"]
            pages.append({"path": p["path"], "title": p["title"], "home": p["path"] == site["home"],
                          "id": m.message_id if m else None,
                          "who": s.identity_label(m.author_key, m.from_name) if m else None,
                          "who_key": m.author_key if m else None,
                          "date": m.date.isoformat() if m and m.date else None,
                          "previous": p["previous"] is not None})
        return {"id": gid, "label": s.group_label(gid), "title": data.get("title", ""),
                "home": site["home"],
                "owner": {"key": owner, "label": s.label_of(owner)} if owner else None,
                "may_write": self._may_write(s, data),
                "max_pages": data.get("max_pages", pg.MAX_PAGES_DEFAULT),
                "index": data.get("index", "no"), "pages": pages,
                "address": _a_page(gid, site["home"])}

    def page(self, gid: str, path: str | None = None) -> dict:
        """``GET /api/groups/{gid}/page?path=`` (section 4.15): one page in force - the
        home page without ``path`` - as a row (section 4.3) whose tree has the page's
        links within the site resolved to their ``unseenet:`` addresses (UN-RFC 0035
        section 8), with its title, path and previous version. 404 when not in force."""
        s = self._ready()
        self._site_data(s, gid)
        site = s.site(gid)
        path = (path or site["home"]).strip().strip("/")
        p = next((x for x in site["pages"] if x["path"] == path), None)
        if p is None or p["current"] is None:
            raise NotFound("that page is not on this site, or this client has not read it")
        m = p["current"]
        mine, patterns = s.my_message_ids(), s._mention_patterns()
        keys = {s.identity(n).key_text for n in s.data["identities"]}
        row = self._row(s, m, 0, mine, patterns, keys)
        if m.readable:
            text = row["message"]["text"]

            def resolve(href: str) -> str | None:
                target = pg.resolve_link(path, href)
                return _a_page(gid, target) if target else None
            row["tree"] = markup.page_body(text, m.content_type, resolve)
        prev = p["previous"]
        return {"path": path, "title": p["title"], "home": path == site["home"],
                "address": _a_page(gid, path), "row": row,
                "previous": None if prev is None else {
                    "id": prev.message_id, "who": s.identity_label(prev.author_key, prev.from_name),
                    "date": prev.date.isoformat() if prev.date else None}}

    def write_page(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/page`` (section 4.15): write a page - ``{"path",
        "title", "text", "markdown": true, "files"}`` - remove it (``{"path", "remove":
        true}``), or publish its previous version again (``{"path", "restore": true}``,
        UN-RFC 0035 section 10.4). A job, as a post is (section 4.4)."""
        s = self._ready()
        site = self._site_data(s, gid)
        if not self._may_write(s, site):
            raise SessionError("only the site's writers write its pages")
        path = str(data.get("path", "")).strip().strip("/")
        if not pg.valid_path(path):
            raise SessionError("a path is 1-8 parts of a-z 0-9 - _ . separated by /")
        if data.get("remove"):
            async def send() -> str:
                return await s.remove_page(gid, path)
        elif data.get("restore"):
            p = next((x for x in s.site(gid)["pages"] if x["path"] == path), None)
            prev = p and p["previous"]
            if not prev or not prev.readable:
                raise SessionError("this page has no earlier version to go back to")
            text, ctype, title = prev.body, prev.content_type, prev.subject

            async def send() -> str:
                return await s.put_page(gid, path, text, title, content_type=ctype)
        else:
            text = str(data.get("text", ""))
            if not text.strip():
                raise SessionError("a page needs some text")
            ctype = None if data.get("markdown", True) else "text/plain; charset=utf-8"
            files = self._files_to_post(s, gid, data.get("files"))          # section 4.10
            title = str(data.get("title", "")).strip()

            async def send() -> str:
                return await s.put_page(gid, path, text, title, content_type=ctype,
                                        files=files or None)

        async def after(msgid: str) -> None:
            await s.fetch_group(gid)
        # the site as it is now first, so the new version names the current one (9.2)
        return {"job": self._new_job(gid, self._fresh(gid, send), after)}

    def _fresh(self, gid: str, send):
        async def run() -> str:
            with contextlib.suppress(*NETWORK_ERRORS):
                await self.session.fetch_group(gid)
            return await send()
        return run


def _a_page(gid: str, path: str) -> str:
    return addr.page_address(gid, path)
