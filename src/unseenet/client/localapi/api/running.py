"""Groups you run (UN-RFC 0046 section 4.7): the owner's and moderators' side.

Belongs here: creating a group, its settings (a new manifest), removing it, inviting
and removing members, roles, bans, and the moderation queue of moderated groups.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


def _file_choice(name) -> dict | None:
    """``files`` as a front end gives it - ``none``, ``pictures`` or ``pictures+pdf``
    (``core.blobs.FILE_CHOICES``, #496) - as a manifest's ``attachments``."""
    from ....core import blobs as bl
    if name not in bl.FILE_CHOICES:
        raise SessionError("files is none, pictures or pictures+pdf")
    return bl.FILE_CHOICES[name]


class Running:
    # --- groups you run (section 4.7) -------------------------------------------
    async def create_group(self, data: dict) -> dict:
        """``POST /api/groups`` (section 4.7): create a group you own - name, type,
        title, description, kinds, view, rules and the channel settings. Answers its Group ID."""
        s = self._ready()
        gtype = str(data.get("type", "open"))
        if gtype not in GROUP_TYPES:
            raise SessionError("type is open, moderated, channel or closed")
        name = str(data.get("name", "")).strip().lower()
        if not name:
            raise SessionError("a group needs a name")
        kinds = str(data.get("kinds", "both"))
        if kinds not in KINDS:
            raise SessionError("kinds is both, post or chat")
        view = data.get("view")
        att = _file_choice(data.get("files", "none"))
        gid = await s.create_group(
            name, gtype, title=str(data.get("title", "")).strip(),
            description=str(data.get("description", "")).strip(),
            view=view if view in ("threads", "chat") else None,
            low_latency=bool(data.get("fast")), kinds=KINDS[kinds],
            extra={"attachments": att} if att else None)
        await self._fetch(gid)
        s.emit(ev.GroupsChanged())
        return {"id": gid}

    async def group_settings(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/settings`` (section 4.7): owner - change a group's
        settings (title, description, rules, view, kinds and the others in ``SETTINGS_FIELDS``).
        A new manifest; type, owner and locality never change."""
        s = self._ready()
        unknown = set(data) - set(SETTINGS_FIELDS)
        if unknown:
            raise SessionError(f"{sorted(unknown)[0]} cannot be changed here")
        changes = dict(data)
        if "files" in changes:                  # what files it takes (#496, UN-RFC 0027 5.1)
            changes["attachments"] = _file_choice(changes.pop("files"))
        if "kinds" in changes:
            if changes["kinds"] not in KINDS:
                raise SessionError("kinds is both, post or chat")
            changes["kinds"] = KINDS[changes["kinds"]] or [KIND_CHAT, KIND_POST]
        await s.update_group(gid, **changes)
        s.emit(ev.GroupUpdated(gid))
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    async def remove_group(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/remove`` (section 4.7): owner - remove a group from
        the whole network (UN-RFC 0013). Final, so it needs ``"confirm": "remove"``."""
        s = self._ready()
        if data.get("confirm") != "remove":
            raise SessionError('give "confirm": "remove"')
        await s.remove_group(gid, str(data.get("reason", "")).strip())
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    async def invite(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/invite`` (section 4.7): owner of a closed group - give a
        key the group's current key."""
        s = self._ready()
        await s.invite(gid, _key(data.get("key")))
        s.emit(ev.GroupUpdated(gid))
        return {"ok": True}

    async def remove_member(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/members/remove`` (section 4.7): owner of a closed
        group - remove a member, which starts a new key epoch. Answers the epoch."""
        s = self._ready()
        epoch = await s.remove_member(gid, _key(data.get("key")))
        s.emit(ev.GroupUpdated(gid))
        return {"epoch": epoch}

    async def role(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/role`` (section 4.7): owner - add or remove a moderator or
        a poster (``role`` moderators or posters, ``on``)."""
        s = self._ready()
        role = str(data.get("role", ""))
        if role not in ("moderators", "posters"):
            raise SessionError("role is moderators or posters")
        await s.set_role(gid, role, _key(data.get("key")), bool(data.get("on", True)))
        s.emit(ev.GroupUpdated(gid))
        return {"ok": True}

    async def ban(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/ban`` (section 4.7): owner - ban a key (``on`` true, with a
        ``reason``) or lift a ban (``on`` false). A new manifest."""
        s = self._ready()
        key = _key(data.get("key"))
        if data.get("on", True):
            await s.ban(gid, key, str(data.get("reason", "")).strip())
        else:
            await s.unban(gid, key)
        s.emit(ev.GroupUpdated(gid))
        return {"ok": True}

    async def moderation(self) -> dict:
        """``GET /api/moderation`` (section 4.7): the submissions waiting for you as a
        moderator, fetched from your inbox, with who sent them and to which group."""
        s = self._ready()
        with contextlib.suppress(*NETWORK_ERRORS):
            await s.fetch_group(s.my_inbox)
        out = []
        for m, art in s.submissions():
            key = art.get("Author-Key", "")
            out.append({"id": m.message_id, "group": art.group,
                        "group_label": s.group_label(art.group),
                        "subject": art.get("Subject", ""),
                        "who": s.identity_label(key, art.get("From", "")), "key": key,
                        "content_type": art.get("Content-Type", ""),
                        "body": "" if art.get("Encrypted") else art.body,
                        "tree": [] if art.get("Encrypted") else markup.body(
                            art.body, art.get("Content-Type", ""), message_kind(art)),
                        "date": m.date.isoformat() if m.date else None})
        return {"waiting": out}

    async def moderate(self, data: dict) -> dict:
        """``POST /api/moderation`` (section 4.7): moderator - approve a submission
        (``approve`` true; it is posted) or reject it with a ``reason`` sent to its author."""
        s = self._ready()
        found = next(((m, a) for m, a in s.submissions() if m.message_id == data.get("id")), None)
        if found is None:
            raise NotFound("that post is not waiting any more")
        m, art = found
        if data.get("approve"):
            await s.approve_submission(m, art)
            await self._fetch(art.group)
        else:
            await s.reject_submission(m, str(data.get("reason", "")).strip())
        s.emit(ev.GroupsChanged())
        return {"ok": True}
