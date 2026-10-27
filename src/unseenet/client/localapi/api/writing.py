"""Writing (UN-RFC 0046 sections 4.4, 4.5): posts and private posts as jobs, and your own posts.

Belongs here: posting, private posts, editing, reacting (UN-RFC 0048) and withdrawing, each a job whose
progress (postage, ripening) arrives as events; and mentions of you.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class Writing:
    # --- writing: jobs (sections 4.4, 4.5) --------------------------------------
    def _new_job(self, group: str, send, after=None) -> str:
        self._jobs += 1
        job = f"job{self._jobs}"
        self.spawn(self._run_job(job, group, send, after))
        return job

    async def _run_job(self, job: str, group: str, send, after) -> None:
        async with self._send:
            self._job = (job, group)
            self._job_event(job, group, "pow", fraction=0.0)
            try:
                msgid = await send()
            except (*NETWORK_ERRORS, ValueError, SessionError) as exc:
                self._job_event(job, group, "failed", error=str(exc) or type(exc).__name__)
                return
            finally:
                self._job = None
        self._job_event(job, group, "sent", message_id=msgid)
        if after is not None:
            with contextlib.suppress(*NETWORK_ERRORS):
                await after(msgid)
        self._job_event(job, group, "reached", message_id=msgid)

    @staticmethod
    def _portals(s: Session, gid: str, accepted: bool) -> None:
        warning = s.portal_warning(gid)
        if warning and not accepted:
            raise SessionError(warning)
        if warning:
            s.accept_portals(gid)

    def post(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/post`` (section 4.4): a post or a chat line, as a job whose
        progress (ripening, postage) comes as events. To a contact's pseudo-group it is a
        private post."""
        s = self._ready()
        kind = _kind(data)
        if gid.startswith(CONTACT):
            return self.private({**data, "key": gid[len(CONTACT):]})
        if gid == FOR_YOU or gid == s.my_inbox:
            raise SessionError("write to a person or a group")
        body = str(data.get("body", "")).strip("\n")
        subject = "" if kind == KIND_CHAT else str(data.get("subject", "")).strip()
        refs = [str(r) for r in data.get("references", []) or []][:MAX_REFERENCES]
        files = self._files_to_post(s, gid, data.get("files"))         # section 4.10
        if not body.strip() and not files:
            raise SessionError("nothing to send")
        if kind not in s.group_kinds(gid):
            raise SessionError("this group takes " + ("posts with a subject only"
                                                       if kind == KIND_CHAT else "chat lines only"))
        if kind == KIND_POST and not subject:
            raise SessionError("a post needs a subject")
        self._portals(s, gid, bool(data.get("publish_outside_tor")))
        if kind == KIND_POST and data.get("signature", True):
            sig = s.signature()
            body = body.rstrip("\n") + ("\n-- \n" + sig if sig else "")
        notify = data.get("notify")
        keys: list[str] = []
        if (s.notice_settings()["send"] if notify is None else bool(notify)) and s.may_notify(gid):
            keys = [k for _, k in s.mentioned(subject, body)][:MAX_MENTION_NOTICES]

        origin = data.get("origin") or None                 # UN-RFC 0049: your own import
        if origin is not None and not isinstance(origin, dict):
            raise SessionError("origin is {network, date, id, from}")
        if origin:
            from ....core import origins
            try:
                origins.origin_headers(str(origin.get("network", "")), origin.get("date"),
                                       str(origin.get("id") or ""), str(origin.get("from") or ""))
            except origins.OriginError as exc:
                raise SessionError(str(exc)) from exc

        tags = data.get("tags") or []                       # the author's own (UN-RFC 0052)
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise SessionError("tags is a list of words")
        from ....core import tags as _tg
        tags = _tg.normalize(list(tags) + _tg.in_text(f"{subject}\n{body}"))   # chips and #words

        async def send() -> str:
            if kind == KIND_CHAT and not refs and not files and not origin and not tags:
                return await s.send_chat(gid, body)
            return await s.post(gid, subject, body, references=refs or None, kind=kind,
                                files=files or None, origin=origin, tags=tags or None)

        async def after(msgid: str) -> None:
            if keys:            # for a post sent to the moderators, the core waits for approval
                self.spawn(s.send_mention_notices(gid, msgid, subject, kind, keys))
            await s.fetch_group(gid)
        return {"job": self._new_job(gid, send, after)}

    def private(self, data: dict) -> dict:
        """``POST /api/private`` (section 4.4): a private post or chat line to a key's
        inbox (UN-RFC 0009), as a job."""
        s = self._ready()
        key = _key(data.get("key"))
        if key == s.identity().key_text:
            raise SessionError("that is your own key")
        kind = _kind(data)
        body = str(data.get("body", "")).strip("\n")
        subject = "" if kind == KIND_CHAT else str(data.get("subject", "")).strip()
        if kind == KIND_POST and not subject:
            raise SessionError("a post needs a subject")
        owner = crypto.key_from_text(key)
        # encrypted with it (UN-RFC 0027 3.3, #497); checked against their inbox when sent
        files = self._files_to_post(s, personal_inbox_id(owner), data.get("files"), check=False)
        if not body.strip() and not files:
            raise SessionError("nothing to send")
        inbox, refs = personal_inbox_id(owner), []
        reply_to = data.get("reply_to")
        if reply_to:
            msg = next((m for m in s.private_messages() if m.message_id == reply_to), None)
            if msg is None:                                 # a message in a team inbox (0047)
                msg = next((m for gid in s.data.get("team_keys", {})
                            for m in s.cache.get(gid, {}).values() if m.message_id == reply_to), None)
            if msg is not None:
                inbox = s.reply_target(msg) or inbox
                refs = msg.references + [msg.message_id]
        group = CONTACT + key if kind == KIND_CHAT else s.my_inbox

        as_team = str(data.get("as_team") or "") or None     # on a team inbox's behalf (0047)
        if as_team and s.team_key(as_team) is None:
            raise SessionError("you hold no team key for that inbox")

        async def send() -> str:
            if kind == KIND_CHAT and not refs and inbox == personal_inbox_id(owner) and not as_team:
                return await s.send_chat(CONTACT + key, body, files=files or None)
            return await s.send_private(inbox, subject, body, owner_key=owner,
                                        references=refs or None, kind=kind, files=files or None,
                                        as_team=as_team)

        async def after(msgid: str) -> None:
            s.emit(ev.GroupUpdated(group))
        return {"job": self._new_job(group, send, after)}

    def edit(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/edit`` (section 4.5): a new version of one of your posts
        (UN-RFC 0042), as a job; its progress comes as events."""
        s = self._ready()
        m = self._find(s, gid, str(data.get("id", "")))
        if not s.may_edit(m):
            raise SessionError("you can only edit your own posts")
        body = str(data.get("body", "")).strip("\n")
        if not body.strip():
            raise SessionError("nothing to send")
        subject = str(data.get("subject", m.subject)).strip()

        async def send() -> str:
            return await s.edit(m, subject, body)

        async def after(msgid: str) -> None:
            await s.fetch_group(m.group)
        return {"job": self._new_job(gid, send, after)}

    def react(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/react`` (section 4.5, UN-RFC 0048): react to a post,
        comment or chat line with ``emoji``, as a job. The emoji you already gave takes
        it back, another changes it. ``who: true`` instead answers who gave ``emoji``."""
        s = self._ready()
        m = self._find(s, gid, str(data.get("id", "")))
        emoji = str(data.get("emoji", "")).strip()
        if data.get("who"):
            return {"who": s.who_reacted(m, emoji)}
        allowed = s.react_permission(m.group, m)
        if not allowed:
            raise SessionError(allowed.reason)
        if not s.reaction_set(m.group).takes(emoji):
            raise SessionError("this group does not take that reaction")

        async def send() -> str:
            return await s.react(m, emoji) or ""

        async def after(msgid: str) -> None:
            s.emit(ev.GroupUpdated(m.group))
        return {"job": self._new_job(gid, send, after)}

    async def withdraw(self, gid: str, message_id: str) -> dict:
        """``POST /api/groups/{gid}/withdraw`` (section 4.5): withdraw a post - your own,
        or any in a group you own or moderate (UN-RFC 0004 section 7)."""
        s = self._ready()
        m = self._find(s, gid, message_id)
        if not s.may_cancel(m):
            raise SessionError("you may not withdraw that post")
        await s.cancel(m)
        await self._fetch(m.group)
        s.emit(ev.GroupUpdated(m.group))
        return {"ok": True}

    async def pin(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/pin`` (section 4.12): the owner or a moderator pins a
        post at the top of the group, kept beyond its window, with an optional note -
        or unpins it with ``"unpin": true`` (UN-RFC 0033). Answers the pins now."""
        s = self._ready()
        if gid not in s.data["groups"] and gid not in s.data["subscribed"]:
            raise NotFound("no such group")
        mid = str(data.get("id") or "").strip()
        if not mid:
            raise SessionError("which post? give its id")
        marker = await s.pin(gid, mid, str(data.get("note") or ""), unpin=bool(data.get("unpin")))
        await self._fetch(gid)
        s.emit(ev.GroupUpdated(gid))
        return {"ok": True, "marker": marker, "pins": self._pins(s, gid)}

    def mentioned(self, gid: str, subject: str, body: str) -> dict:
        """``POST /api/groups/{gid}/mentioned`` (section 4.5): before posting, whom a
        text mentions by name and whether notices may be sent here (UN-RFC 0032) - for asking
        the writer."""
        s = self._ready()
        if not s.may_notify(gid):
            return {"may": False, "names": [], "max": MAX_MENTION_NOTICES}
        return {"may": True, "names": [n for n, _ in s.mentioned(subject, body)],
                "max": MAX_MENTION_NOTICES}
