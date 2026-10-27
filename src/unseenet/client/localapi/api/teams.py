"""Team inboxes (UN-RFC 0047, #341) for front ends: the team inboxes you read, accepting
an invitation, who reads an inbox you own, adding and removing readers.

Belongs here: ``GET /api/teams``, ``POST /api/teams/accept``, ``POST /api/teams/forget``,
``GET``/``POST /api/teams/readers``. Writing on an inbox's behalf is ``POST /api/private``
with ``as_team`` (writing.py); a message written so has ``team`` in its row.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class Teams:
    def teams(self) -> dict:
        """``GET /api/teams``: ``{"teams": [{"group", "name", "reader"}]}`` - the team
        inboxes you read; ``reader`` false once you were removed (offer to forget it)."""
        return {"teams": self._ready().team_inboxes()}

    async def accept_team(self, body: dict) -> dict:
        """``POST /api/teams/accept`` ``{"id"}``: accept the invitation in that private
        post - checked against the inbox's owner and readers first. ``{"group"}``."""
        s = self._ready()
        mid = str(body.get("id", ""))
        msg = next((m for m in s.private_messages() if m.message_id == mid), None)
        if msg is None:
            raise SessionError("no such private post")
        gid = await s.accept_team_invitation(msg)
        s.emit(ev.GroupsChanged())
        return {"group": gid}

    def forget_team(self, body: dict) -> dict:
        """``POST /api/teams/forget`` ``{"group"}``: remove its team key from the vault."""
        s = self._ready()
        s.forget_team_key(str(body.get("group", "")))
        s.emit(ev.GroupsChanged())
        return self.teams()

    async def team_readers(self, gid: str) -> dict:
        """``GET /api/teams/readers?group=``: as its owner, the team keys that read an
        inbox and its ``team_name``."""
        s = self._ready()
        data = await s._own_inbox(gid)
        return {"group": gid, "readers": list(data.get("readers", [])),
                "team_name": data.get("team_name", "")}

    async def change_team_readers(self, body: dict) -> dict:
        """``POST /api/teams/readers`` ``{"group", "add": key, "team_name"}`` - a new team
        key for that person, sent to their inbox - or ``{"group", "remove": team key}``.
        Answers as ``GET``."""
        s = self._ready()
        gid = str(body.get("group", ""))
        if body.get("add"):
            name = body.get("team_name")
            await s.add_team_reader(gid, _key(body["add"]), str(name) if name is not None else None)
        elif body.get("remove"):
            await s.remove_team_reader(gid, _key(body["remove"]))
        else:
            raise SessionError("add or remove a reader")
        return await self.team_readers(gid)
