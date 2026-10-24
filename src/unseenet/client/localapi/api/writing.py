"""Writing (UN-RFC 0046 sections 4.4, 4.5): posts and private posts as jobs, and your own posts.

Belongs here: posting, private posts, editing and withdrawing, each a job whose
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
            except (*NETWORK_ERRORS, ValueError) as exc:
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

        async def send() -> str:
            if kind == KIND_CHAT and not refs and not files:
                return await s.send_chat(gid, body)
            return await s.post(gid, subject, body, references=refs or None, kind=kind,
                                files=files or None)

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
        if not body.strip():
            raise SessionError("nothing to send")
        subject = "" if kind == KIND_CHAT else str(data.get("subject", "")).strip()
        if kind == KIND_POST and not subject:
            raise SessionError("a post needs a subject")
        owner = crypto.key_from_text(key)
        inbox, refs = personal_inbox_id(owner), []
        reply_to = data.get("reply_to")
        if reply_to:
            msg = next((m for m in s.private_messages() if m.message_id == reply_to), None)
            if msg is not None:
                inbox = s.reply_target(msg) or inbox
                refs = msg.references + [msg.message_id]
        group = CONTACT + key if kind == KIND_CHAT else s.my_inbox

        async def send() -> str:
            if kind == KIND_CHAT and not refs and inbox == personal_inbox_id(owner):
                return await s.send_chat(CONTACT + key, body)
            return await s.send_private(inbox, subject, body, owner_key=owner,
                                        references=refs or None, kind=kind)

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

    def mentioned(self, gid: str, subject: str, body: str) -> dict:
        """``POST /api/groups/{gid}/mentioned`` (section 4.5): before posting, whom a
        text mentions by name and whether notices may be sent here (UN-RFC 0032) - for asking
        the writer."""
        s = self._ready()
        if not s.may_notify(gid):
            return {"may": False, "names": [], "max": MAX_MENTION_NOTICES}
        return {"may": True, "names": [n for n, _ in s.mentioned(subject, body)],
                "max": MAX_MENTION_NOTICES}
