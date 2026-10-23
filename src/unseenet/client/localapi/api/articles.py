"""Articles from a program (UN-RFC 0046 section 4.9): a service posting what it built itself.

Belongs here: ``article`` (a signed article with the headers a program may add) and
``manifest`` (a group's manifest written by a program).

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class Articles:
    # --- articles from a program (section 4.9) ----------------------------------
    def article(self, data: dict) -> dict:
        s = self._ready()
        gid = str(data.get("group", ""))
        kind = _kind(data)
        body = str(data.get("body", ""))
        subject = "" if kind == KIND_CHAT else str(data.get("subject", "")).strip()
        if not body.strip():
            raise SessionError("nothing to send")
        if kind == KIND_POST and not subject:
            raise SessionError("a post needs a subject")
        extra = []
        for pair in data.get("headers", []) or []:
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                raise SessionError("headers are [name, value] pairs")
            name, value = str(pair[0]), str(pair[1])
            if (not name.lower().startswith(PROGRAM_HEADERS) or "\n" in value or "\r" in value
                    or not name.replace("-", "").isalnum()):
                raise SessionError(f"a program may not set {name}")
            extra.append((name, value))
        refs = [str(r) for r in data.get("references", []) or []][:MAX_REFERENCES]
        self._portals(s, gid, bool(data.get("publish_outside_tor")))
        content_type = str(data["content_type"]) if data.get("content_type") else None
        from_name = str(data["from"]) if data.get("from") else None

        async def send() -> str:
            return await s.post(gid, subject, body, references=refs or None, kind=kind,
                                content_type=content_type, extra=extra, from_name=from_name)

        async def after(msgid: str) -> None:
            await s.fetch_group(gid)
        return {"job": self._new_job(gid, send, after)}

    async def manifest(self, gid: str, data: dict) -> dict:
        """A whole new manifest for a group this key owns (a gateway's, a bot's channel)."""
        s = self._ready()
        entry = s.data["groups"].get(gid, {})
        if not entry.get("owner"):
            raise SessionError("only the owner can change a group")
        old = s.manifest_data(gid)
        if not old:
            raise SessionError("the group's manifest has not been fetched yet")
        for fixed in FIXED_FIELDS:
            if fixed in data and data[fixed] != old.get(fixed):
                raise SessionError(f"{fixed} can never change (UN-RFC 0004, 4)")
        new = {**data, **{k: old[k] for k in FIXED_FIELDS if k in old}}
        new["serial"] = int(old.get("serial", 1)) + 1
        art = manifest_article(s.identity(), gid, new, await s.required_pow(None))
        await s.post_article(art)
        entry.update({"manifest": new, "title": new.get("title", "")})
        s.save()
        s.emit(ev.GroupUpdated(gid))
        return {"ok": True, "serial": new["serial"]}
