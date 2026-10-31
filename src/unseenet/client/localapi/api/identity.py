"""Who you are (UN-RFC 0046 section 4.8): profiles, names, the passphrase, your settings.

Belongs here: reading and publishing profiles (``profile``, ``publish_profile``, with
``label``, ``mine``, ``link_kinds`` and the public-profile warning), hiding someone's
profile, changing the vault's passphrase, your names (UN-RFC 0019) and settings.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

import re

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class Identity:
    # --- who you are (section 4.8) ---------------------------------------------
    async def profile(self, key: str | None = None, context: str | None = None) -> dict:
        """A profile with what a front end shows around it (#320): its label, whether
        you hid it, and for yours whether one is published and the warning before
        the first (UN-RFC 0022 sections 9.1, 9.2). With ``context`` - where it is
        opened: a closed group's ID, or ``me`` (your private posts or a chat with
        them) - a profile they shared there only (section 6, UN-RFC 0046 4.16)."""
        s = self._ready()
        me = s.identity().key_text
        key = (key or "").strip() or me
        from .addresses import identity_address
        base = {"label": s.label_of(key), "link_kinds": list(prof.LINK_KINDS),
                "address": identity_address(_key(key))}       # to share (section 4.13)
        if key == me:
            from .pictures import _shown
            return {**self._profile(me, s.my_profile()), **base, "mine": True, "hidden": False,
                    "published": s.has_published_profile(), "warning": prof.PROFILE_WARNING,
                    # your picture (UN-RFC 0022 section 8.5): what is published, and what
                    # to tell before the first (section 4.11)
                    "picture": _shown(s.my_picture()), "picture_warning": prof.PICTURE_WARNING}
        key = _key(key)
        fp = crypto.fingerprint(crypto.key_from_text(key))
        # their personal feed, and whether you follow them (UN-RFC 0034, section 4.14)
        base.update(feed=f"feed@{fp}", following=fp in s.data.get("following", {}).get("people", {}))
        # a profile they shared with you or this closed group, shown only there (0022, 6)
        ctx = self._context(s, context)
        shared = s.private_profile(key, ctx) if ctx else None
        base["shared"] = None if shared is None else {
            **self._profile(key, shared), "context": ctx,
            "context_label": "you" if ctx == "me" else s.group_label(ctx)}
        if s.profile_hidden(key):                         # hidden: not even asked for
            return {**self._profile(key, None), **base, "mine": False, "hidden": True}
        # all the authors you have, read together, so a node cannot tell whose you open
        # (UN-RFC 0022 section 13, UN-RFC 0041 section 3.2)
        authors = [m.author_key for g in s.cache.values() for m in g.values()
                   if m.readable and m.author_key][:255]
        with contextlib.suppress(*NETWORK_ERRORS):        # profile_of below tries again
            await s.prefetch_profiles([key, *authors])
        p = await s.profile_of(key)
        # their feed and site, if they have them: to look at without following (#506)
        theirs = {"feed": None, "site": None}
        with contextlib.suppress(*NETWORK_ERRORS):
            theirs = await s.personal_groups_of(key, keep=True)   # so they open at once
        return {**self._profile(key, None if p is None else (p.raw or {"about": p.about})),
                **base, "mine": False, "hidden": False, "theirs": theirs}

    @staticmethod
    def _context(s: Session, context: str | None) -> str | None:
        """Where a profile is opened, as the core keeps shared ones: ``me`` for your private
        posts and chats, or a closed group's ID."""
        context = (context or "").strip()
        if not context:
            return None
        if context == "me" or context == s.my_inbox or context.startswith(CONTACT):
            return "me"
        return context if s.group_entry(context).get("type") == "closed" else None

    async def share_profile(self, data: dict) -> dict:
        """``POST /api/profile/share`` (section 4.16, UN-RFC 0022 section 6): share a
        profile with one person (``"to"``: their key) or a closed group (its ID), where
        only they can read it - your public profile, or ``"profile"`` (an object, or
        ``{"edit": fields}`` as for ``POST /api/profile``) made for them; with
        ``"withdraw": true`` take back the one you shared there. Nothing is published."""
        s = self._ready()
        to = str(data.get("to", "")).strip()
        if to.startswith(CONTACT):
            to = to[len(CONTACT):]
        if to.startswith("ed25519:"):
            to = personal_inbox_id(crypto.key_from_text(_key(to)))
        elif not to:
            raise SessionError("share with whom? a key or a closed group")
        if data.get("withdraw"):
            mid = await s.withdraw_shared_profile(to)
        else:
            profile = data.get("profile")
            if isinstance(profile, dict) and isinstance(profile.get("edit"), dict):
                profile = self._from_fields(s, profile["edit"])
            if profile is not None and not isinstance(profile, dict):
                raise SessionError("a profile is an object or null")
            mid = await s.share_profile(to, profile)
        return {"ok": True, "id": mid}

    def hide_profile(self, key: str, hidden: bool = True) -> dict:
        """Hide or show someone's profile, for you alone (UN-RFC 0022 section 9.2)."""
        s = self._ready()
        key = _key(key)
        if key == s.identity().key_text:
            raise SessionError("You cannot hide your own profile")
        s.hide_profile(key, bool(hidden))
        return {"key": key, "hidden": s.profile_hidden(key)}

    async def change_passphrase(self, old: str, new: str) -> dict:
        """A new passphrase for this vault file (#281). Slow, so off the event loop.
        Copies of the vault elsewhere keep the old one."""
        s = self._ready()
        if self.service:
            raise SessionError("a service has no vault passphrase")
        if len(new) < 4:
            raise SessionError("The new passphrase is too short.")
        try:
            await asyncio.to_thread(s.change_passphrase, old, new)
        except VaultError as exc:
            raise SessionError("The current passphrase is not right." if "wrong passphrase" in str(exc)
                               else f"Could not change it: {exc}") from exc
        return {"ok": True}

    @staticmethod
    def _profile(key: str, obj: dict | None) -> dict:
        tree = markup.manifest_text(obj.get("about", ""), obj.get("about_type")) \
            if obj and obj.get("about") else []
        return {"key": key, "profile": obj, "about_tree": tree}

    async def publish_profile(self, profile) -> dict:
        """``POST /api/profile`` (section 4.8): publish your profile - an object, or
        ``{"edit": fields}`` from the profile form, or null to withdraw it. A program's profile
        says it is a bot. Answers the profile as ``GET`` shows it."""
        s = self._ready()
        if isinstance(profile, dict) and isinstance(profile.get("edit"), dict):
            profile = self._from_fields(s, profile["edit"])
        if profile is not None and not isinstance(profile, dict):
            raise SessionError("a profile is an object or null")
        if self.service and isinstance(profile, dict):
            profile = {**profile, "bot": True}             # a program says so (UN-RFC 0030, 6)
        await s.publish_profile(profile)
        return {**self._profile(s.identity().key_text, s.my_profile()),
                "published": s.has_published_profile()}

    @staticmethod
    def _from_fields(s: Session, f: dict) -> dict:
        """A profile from a form's fields (#320): ``about``, ``links`` as
        ``[{"kind", "value", "label"}]``, ``lang`` as a list or "da, en", and
        ``markdown``. The bot mark you have stays."""
        links = []
        for link in f.get("links") or []:
            if isinstance(link, dict) and str(link.get("value", "")).strip():
                item = {"kind": str(link.get("kind", "")).strip().lower(),
                        "value": str(link["value"]).strip()}
                if str(link.get("label", "")).strip():
                    item["label"] = str(link["label"]).strip()
                links.append(item)
        lang = f.get("lang") or []
        if isinstance(lang, str):
            lang = lang.split(",")
        lang = [str(t).strip() for t in lang if str(t).strip()]
        try:
            return prof.make_profile(str(f.get("about", "")), links, lang,
                                     bot=(s.my_profile() or {}).get("bot") is True,
                                     markdown=bool(f.get("markdown")))
        except prof.ProfileError as exc:
            raise SessionError(str(exc)) from exc

    async def names(self) -> dict:
        """``GET /api/names`` (section 4.8): your names (UN-RFC 0019) - the ones you hold,
        which is shown first, pending claims, and the DNS value to prove a domain."""
        s = self._ready()
        with contextlib.suppress(*NETWORK_ERRORS, asyncio.TimeoutError):
            await asyncio.wait_for(s.refresh_naming(), 60)
        me = s.identity().key_text
        mine = naming.my_names(s)
        primary = naming.preferred(s, me, mine).name if mine else None
        held = {c.name for c in mine}
        return {
            "key": me, "dns_value": nm.dns_record_value(me),
            "mine": [{"name": c.name, "text": naming.name_text(c.name), "kind": c.kind,
                      "expires": c.expires.isoformat(), "primary": c.name == primary}
                     for c in mine],
            "pending": [{"name": n, "action": a, "sent": when}
                        for n, a, when in naming.pending(s) if n not in held],
            # a council registrar takes claims in the open (UN-RFC 0054 section 8): say so
            # before a claim is sent, and show each claim's state
            "public_claims": naming.claims_are_public(s),
            "public_notice": naming.PUBLIC_NOTICE if naming.claims_are_public(s) else "",
            "commits": naming.commits(s),
            "parents": naming.parents_i_hold(s),
            "given": [{"name": c.name, "key": c.key, "who": s.label_of(c.key),
                       "expires": c.expires.isoformat()} for c in naming.names_given(s)],
            "requests": [{"id": m.message_id, "name": d.get("name", ""), "key": d.get("key", ""),
                          "who": s.identity_label(d.get("key", ""), m.from_name)}
                         for m, d in naming.name_requests(s)],
        }

    async def name_action(self, data: dict) -> dict:
        """claim, renew, release, transfer, primary, ask, give, revoke, approve, refuse."""
        s, action = self._ready(), str(data.get("action", ""))
        name = str(data.get("name", "")).strip().lower().lstrip("@")
        if action in ("claim", "renew", "release", "transfer"):
            nm.check_name(name)
            to = None
            if action == "transfer":
                to = _key(data.get("to"))
                if to == s.identity().key_text:
                    raise SessionError("that is your own key")
            await naming.claim(s, name, action, to)
            if naming.claims_are_public(s):
                text = (f"Your {action} of @{name} is committed. The claim goes out by itself "
                        "when it is an hour old, while Unseenet is open. "
                        + naming.PUBLIC_NOTICE)
            else:
                text = f"Sent your {action} of @{name} to the registrar. It decides after about an hour."
        elif action == "primary":
            naming.set_primary(s, name)
            text = f"Your posts show {naming.name_text(name)}"
        elif action == "ask":
            await naming.request_subname(s, name)
            text = f"Asked for {name}. The answer comes to your private posts."
        elif action == "give":
            key = _key(data.get("key"))
            years = max(1, min(int(data.get("years", 1) or 1), 10))
            await naming.give_subname(s, name, key, timedelta(days=365 * years))
            text = f"{name} given to {s.label_of(key)}"
        elif action == "revoke":
            await naming.revoke_subname(s, name)
            text = f"{name} taken back"
        elif action in ("approve", "refuse"):
            await s.fetch_group(s.my_inbox)
            found = next(((m, d) for m, d in naming.name_requests(s)
                          if m.message_id == data.get("id")), None)
            if found is None:
                raise NotFound("that request is not waiting any more")
            await naming.answer_request(s, found[0], found[1], approve=action == "approve")
            text = "Given." if action == "approve" else "Said no."
        else:
            raise SessionError(f"unknown action {action!r}")
        return {"text": text}

    async def export(self, data: dict) -> dict:
        """``POST /api/export`` (UN-RFC 0049 section 7, #577): write an export of your
        data - ``{"path", "private": false, "passphrase"}``; ``path`` defaults to
        Downloads (else your home folder). With ``private`` the file is encrypted with
        the passphrase. Answers what ``Session.export`` does: path, counts and the note
        that it holds only what the nodes still carry."""
        from datetime import datetime, timezone
        from pathlib import Path
        s = self._ready()
        path = str(data.get("path") or "").strip()
        if not path:
            folder = Path.home() / "Downloads"
            folder = folder if folder.is_dir() else Path.home()
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            path = str(folder / f"unseenet-export-{s.identity().fingerprint[:8]}-{day}.zip")
        return await s.export(path, private=bool(data.get("private")),
                              passphrase=data.get("passphrase"))

    def notifications(self) -> dict:
        """``GET /api/notifications``: what new has landed in For you since the last
        time any client asked - for the front end to tell the reader, as the reader
        chose (``settings``). Asking marks them as told."""
        return self._ready().notifications()

    def settings(self) -> dict:
        """``GET /api/settings`` (section 4.8): your settings, with a preview of your
        signature as it will be signed, and whether you issue spam reports (section 4.21)."""
        s = self._ready()
        return {"signature": s.signature_template(), "signature_preview": s.signature(),
                "markdown": markup.is_markdown(s.text_type()), "notices": s.notice_settings(),
                "private_min_ripe": s.private_min_ripe(),
                "show_blocked": bool(s.data.get("show_blocked")), "hide_bots": s.hide_bots(),
                "pictures": s.show_pictures(), "state_local": s.state_kept_local(),
                "notifications": s.notification_settings(),
                "link_cards": s.link_cards(),               # UN-RFC 0059 section 7.5
                "share_notices": s.share_notices_on(),      # UN-RFC 0060 section 8
                "hide_shares": s.hidden_shares(),          # ... section 5.4
                "report_issuer": bool(s.issuer_names())}    # UN-RFC 0045: offer publishing

    async def change_settings(self, data: dict) -> dict:
        """``POST /api/settings``: as ``set_settings``, and ``state_local`` - keep your
        state on this device only, or in the network again (UN-RFC 0044 section 7.4)."""
        data = dict(data)
        local = data.pop("state_local", None)
        if local is not None and not isinstance(local, bool):
            raise SessionError("state_local is true or false")
        out = self.set_settings(data)              # checks the rest before anything changes
        s = self._ready()
        if local is not None and local != s.state_kept_local():
            await s.set_state_kept_local(local)
            out = self.settings()
        return out

    # a client's own settings (UN-RFC 0044 section 4.2): small values under short keys
    _CLIENT = re.compile(r"[a-z][a-z0-9-]{0,31}")

    def client_settings(self, client: str) -> dict:
        """``GET /api/settings/clients/<client>`` (section 4.8): the settings one kind of
        client keeps with your state, so they follow you from device to device."""
        s = self._ready()
        if not self._CLIENT.fullmatch(client or ""):
            raise SessionError("a client is named in lowercase letters, digits and -")
        return {"client": client, "settings": dict(s.data.get("clients", {}).get(client, {}))}

    def set_client_settings(self, client: str, data: dict) -> dict:
        """``POST /api/settings/clients/<client>`` ``{"key": value, ...}``: change them;
        null removes one. Values are strings, numbers, true or false."""
        s = self._ready()
        self.client_settings(client)
        for key, value in data.items():
            if not self._CLIENT.fullmatch(key):
                raise SessionError(f"a setting is named in lowercase letters, digits and -: {key!r}")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise SessionError(f"{key} is a string, a number, true, false or null")
            if isinstance(value, str) and len(value) > 256:
                raise SessionError(f"{key} is at most 256 characters")
        for key, value in data.items():
            s.set_client_setting(client, key, value)
        return self.client_settings(client)

    def set_settings(self, data: dict) -> dict:
        """``POST /api/settings`` (section 4.8): change your settings - signature,
        Markdown, notices, the ripening level private senders need, blocked posts, bots,
        share notices and hidden shares (UN-RFC 0060 sections 8, 5.4)."""
        s = self._ready()
        unknown = set(data) - {"signature", "markdown", "notices", "private_min_ripe",
                               "show_blocked", "hide_bots", "pictures", "notifications",
                               "link_cards", "share_notices", "hide_shares"}
        if unknown:
            raise SessionError(f"unknown setting {sorted(unknown)[0]}")
        level = data.get("private_min_ripe")
        if level is not None and (isinstance(level, bool) or not isinstance(level, int)
                                  or not 0 <= level <= 4):
            raise SessionError("private_min_ripe is a level 0-4 or null")
        if "signature" in data:
            s.set_signature(str(data["signature"]))
        if "markdown" in data:
            s.set_markdown(bool(data["markdown"]))
        if "notices" in data:
            n = data["notices"] or {}
            s.set_notice_settings(send=None if "send" not in n else bool(n["send"]),
                                  receive=None if "receive" not in n else bool(n["receive"]))
        if "private_min_ripe" in data:
            s.set_private_min_ripe(level)
        if "show_blocked" in data:
            s.set_show_blocked(bool(data["show_blocked"]))
        if "hide_bots" in data:
            s.set_hide_bots(bool(data["hide_bots"]))
        if "pictures" in data:
            s.set_show_pictures(bool(data["pictures"]))
        if "share_notices" in data:                          # UN-RFC 0060 section 8
            s.set_share_notices(bool(data["share_notices"]))
        if "hide_shares" in data:                            # ... section 5.4
            h = data["hide_shares"] or {}
            if not isinstance(h, dict):
                raise SessionError('hide_shares is {"all": true|false, "groups": [...]}')
            if "all" in h:
                s.set_hide_shares(None, bool(h["all"]))
            for g in h.get("groups", []) or []:
                s.set_hide_shares(str(g), True)
            for g in h.get("show", []) or []:
                s.set_hide_shares(str(g), False)
        if "link_cards" in data:
            s.set_link_cards(bool(data["link_cards"]))
        if "notifications" in data:
            n = data["notifications"] or {}
            if not isinstance(n, dict):
                raise SessionError("notifications is {on, content}")
            s.set_notification_settings(on=n["on"] if "on" in n else ...,
                                        content=n["content"] if "content" in n else ...)
        self._redraw_all(s)
        return self.settings()
