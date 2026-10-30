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
        card = self._card_to_post(data.get("card"), body)              # UN-RFC 0059
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
        languages = data.get("languages")                   # Content-Language (0052 5a)
        if languages is not None and (not isinstance(languages, list)
                                      or not all(isinstance(c, str) for c in languages)):
            raise SessionError("languages is a list of codes such as da, en")
        days = _comment_days(data)                          # UN-RFC 0030 section 3.1
        if days is not None:
            s._comment_days_header(gid, days, refs)         # refused now, not in the job

        async def send() -> str:
            if kind == KIND_CHAT and not refs and not files and not origin and not tags \
                    and not languages and days is None:
                return await s.send_chat(gid, body, card=card)
            return await s.post(gid, subject, body, references=refs or None, kind=kind,
                                files=files or None, origin=origin, tags=tags or None,
                                languages=languages, comment_days=days, card=card)

        async def after(msgid: str) -> None:
            if keys:            # for a post sent to the moderators, the core waits for approval
                self.spawn(s.send_mention_notices(gid, msgid, subject, kind, keys))
            await s.fetch_group(gid)
        return {"job": self._new_job(gid, send, after)}

    @staticmethod
    def _card_to_post(data, body: str):
        """The ``card`` of ``POST .../post``, ``/api/private`` and ``.../edit`` (UN-RFC
        0059): as ``POST /api/card`` gave it, perhaps changed by the user; absent or null
        for none. Its link must be in ``body`` - refused here, before the job starts."""
        if not data:
            return None
        from ...session import CardDraft
        from ....core import cards as cd
        card = CardDraft.from_dict(data)
        if not any(cd.same_url(card.url, u) for u in cd.urls_in(body, quoted=True)):
            raise SessionError("the card's link is not in the text")
        return card

    async def card(self, data: dict) -> dict:
        """``POST /api/card`` ``{"url"}`` or ``{"text"}`` (UN-RFC 0059 section 7): a link
        card for the URL, or for the first link in a text being written, made over Tor -
        for the composer to show, let the user change, and send with the post as
        ``card``. ``{"card": null}`` when the text has no link a card is made for."""
        s = self._ready()
        url = str(data.get("url") or "").strip() or s.card_url(str(data.get("text") or ""))
        if not url:
            return {"card": None}
        lang = str(data.get("language") or "en")[:8]
        return {"card": (await s.make_card(url, language=lang)).to_dict()}

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
        card = self._card_to_post(data.get("card"), body)              # UN-RFC 0059
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
                return await s.send_chat(CONTACT + key, body, files=files or None, card=card)
            return await s.send_private(inbox, subject, body, owner_key=owner,
                                        references=refs or None, kind=kind, files=files or None,
                                        as_team=as_team, card=card)

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
        # the new version's tags (warnings too) and languages (UN-RFC 0052); left out,
        # the earlier version's are kept (#733)
        tags = data.get("tags")
        if tags is not None and (not isinstance(tags, list)
                                 or not all(isinstance(t, str) for t in tags)):
            raise SessionError("tags is a list of words")
        languages = data.get("languages")
        if languages is not None and (not isinstance(languages, list)
                                      or not all(isinstance(c, str) for c in languages)):
            raise SessionError("languages is a list of codes such as da, en")
        days = _comment_days(data)                          # only shorter (UN-RFC 0030 3.1)
        # the link card (UN-RFC 0059 section 10): left out, the earlier version's is kept;
        # null takes it off
        card = self._card_to_post(data["card"], body) if "card" in data else ...

        async def send() -> str:
            return await s.edit(m, subject, body, tags=tags, languages=languages,
                                comment_days=days, card=card)

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

    async def comments(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/comments`` (section 4.24): close comments on an entry,
        with an optional note, or open them again (UN-RFC 0030 section 3.2) - its author,
        the owner or a moderator. Answers the entry's state now."""
        s = self._ready()
        if gid not in s.data["groups"] and gid not in s.data["subscribed"]:
            raise NotFound("no such group")
        mid = str(data.get("id") or "").strip()
        if not mid:
            raise SessionError("which entry? give its id")
        close = data.get("close", True)
        if not isinstance(close, bool):
            raise SessionError('"close" is true or false')
        marker = await s.close_comments(gid, mid, str(data.get("note") or ""), reopen=not close)
        await self._fetch(gid)
        s.emit(ev.GroupUpdated(gid))
        return {"ok": True, "marker": marker, "comments": comments_dict(s.comments_state(gid, mid))}

    def language(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/language`` ``{"text", "reply_to", "kind"}`` (UN-RFC
        0052 5a, #686): what to suggest the author writes in, from the text as they type -
        ``{"codes", "from"}``, from ``text``, ``answered``, ``conversation``, ``group``,
        ``you``, ``profile`` or ``""``. Local and cheap: ask at every pause in typing."""
        s = self._ready()
        reply_to = None
        if data.get("reply_to"):
            reply_to = next((m for m in self._pool(s, gid) if m.message_id == data["reply_to"]), None)
        kind = "chat" if data.get("kind") == "chat" else "post"
        codes, why = s.suggest_languages(gid, text=str(data.get("text") or "")[:20000],
                                         reply_to=reply_to, kind=kind)
        return {"codes": codes, "from": why}

    def languages(self) -> dict:
        """``GET /api/languages``: the languages to choose from - code, own name, English
        name, and whether a text can be told to be in it (core.languages). No flags."""
        from ....core import languages as langs
        return {"languages": langs.as_list()}

    def choose_language(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/language/choose`` ``{"languages"}``: what you write
        your chat lines and comments in here, winning over suggestions; [] takes it back."""
        s = self._ready()
        langs = data.get("languages") or []
        if not isinstance(langs, list):
            raise SessionError("languages is a list of codes such as da, en")
        s.choose_chat_language(gid, langs)
        codes, why = s.suggest_languages(gid, kind="chat")
        return {"codes": codes, "from": why}

    def mentioned(self, gid: str, subject: str, body: str) -> dict:
        """``POST /api/groups/{gid}/mentioned`` (section 4.5): before posting, whom a
        text mentions by name and whether notices may be sent here (UN-RFC 0032) - for asking
        the writer."""
        s = self._ready()
        if not s.may_notify(gid):
            return {"may": False, "names": [], "max": MAX_MENTION_NOTICES}
        return {"may": True, "names": [n for n, _ in s.mentioned(subject, body)],
                "max": MAX_MENTION_NOTICES}


def _comment_days(data: dict) -> int | None:
    """``comment_days`` of a post or edit: a whole number of days, 0 or more, or None."""
    days = data.get("comment_days")
    if days is None:
        return None
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        raise SessionError("comment_days is a whole number of days, 0 or more")
    return days


def comments_dict(state: dict) -> dict:
    """A thread's comments state (``Session.comments_state``) as JSON (section 4.24)."""
    until = state.get("until")
    return {**state, "until": until.isoformat() if until is not None else None}
