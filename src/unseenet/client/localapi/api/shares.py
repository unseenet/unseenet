"""Sharing (UN-RFC 0060, in the local API of UN-RFC 0046): share, undo, and the original.

Belongs here: ``POST .../share`` (into your feed, a group, or to one person - a job),
``POST .../unshare``, ``GET /api/share-target`` (the article a share refers to,
``503 later`` while a node fetches it), and where a post can be shared.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts

TARGET_WAIT = 8.0          # seconds a request waits for a node that is fetching


class Shares:
    def share(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/share``: share the post ``id`` - into your feed, or
        ``into`` a group, plainly or with ``comment`` (and ``subject`` for a post); or
        ``to`` one person's key (section 7.4). A job; the author gets a notice unless
        ``notify`` is false (section 8)."""
        s = self._ready()
        m = self._find(s, gid, str(data.get("id", "")))
        allowed = s.share_permission(m)
        if not allowed:
            raise SessionError(allowed.reason)
        comment = str(data.get("comment", "") or "").strip()
        to = str(data.get("to", "") or "").strip()
        if to:
            async def send() -> str:
                return await s.send_share(m, to, comment)
            return {"job": self._new_job(s.my_inbox or gid, send)}
        into = str(data.get("into", "") or "").strip() or None
        dest = into or s.personal_group("feed")
        ok = s.share_into_permission(dest, plain=not comment)
        if not ok:
            raise SessionError(ok.reason)
        subject = str(data.get("subject", "") or "").strip()
        notify = data.get("notify", True) is not False

        async def send() -> str:
            return await s.share(m, comment, into=into, subject=subject)

        async def after(msgid: str) -> None:
            if notify:
                self.spawn(s.send_share_notice(msgid))
            else:
                s.data.get("share_notices_to_send", {}).pop(msgid, None)
            await s.fetch_group(dest)
        return {"job": self._new_job(dest, send, after)}

    async def unshare(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/unshare``: take back your shares of the post ``id``
        (its original, for a plain share) - in ``group`` only, or everywhere."""
        s = self._ready()
        m = self._find(s, gid, str(data.get("id", "")))
        target, _ = s.share_target(m)
        groups = await s.unshare(target, str(data.get("group") or "") or None)
        for g in groups:
            await self._fetch(g)
        return {"groups": groups}

    def share_options(self, gid: str, message_id: str) -> dict:
        """``GET /api/groups/{gid}/share?id=``: whether the post can be shared, where
        to (your feed first), and where you have shared it (section 5.5)."""
        s = self._ready()
        m = self._find(s, gid, message_id)
        target, group = s.share_target(m)
        return {"share": _perm(s.share_permission(m)), "target": target, "target_group": group,
                "destinations": s.share_destinations(m), "shared": s.my_shares(target)}

    async def share_target(self, of: str, group: str, share_date: str | None = None) -> dict:
        """``GET /api/share-target?of=&group=``: the article a share refers to, fetched
        and checked (section 6.3): ``{"state": "ok", "message": {...}}``, or
        ``withdrawn``, ``gone``, ``unavailable``. ``503`` with ``later: true`` while a
        node still fetches it - ask again in a few seconds."""
        s = self._ready()
        if not of.startswith("<"):
            raise SessionError("of is a Message-ID")
        got = await s.fetch_share_target(of, group, patience=TARGET_WAIT)
        if got["state"] == "fetching":
            raise Status("still fetching", 503, later=True)
        out = {"state": got["state"], "message": None}
        msg = got.get("message")
        if msg is not None:
            out["message"] = msg.to_dict()
            out["who"] = s.identity_label(msg.author_key, msg.from_name)
            out["label"] = s.group_label(group)
            out["edited"] = msg.message_id != of
        return out
