"""Publishers (UN-RFC 0062 section 6, #822) for front ends: who the stick takes updates
from, what a releases channel shows before it is added, and adding, following and
removing publishers. The same as ``unseenet publishers``.

Belongs here: ``GET /api/publishers`` and ``POST /api/publishers``. The rules are the
session's (``Session.publisher_preview`` and the rest) and ``publishers.py``.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file

ACTIONS = ("preview", "add", "follow", "remove")


def preview_fields(p) -> dict:
    return {"group": p.group, "fingerprint": p.fingerprint, "fork": p.fork,
            "keys": list(p.keys.keys), "threshold": p.keys.threshold, "seq": p.keys.seq,
            "releases": dict(p.releases)}


class Publishers:
    async def publishers(self) -> dict:
        """``GET /api/publishers``: ``{"stick", "follow", "publishers": [{"group", "name",
        "project", "fingerprint", "followed"}]}``."""
        return self._ready().publishers()

    async def publishers_post(self, body: dict) -> dict:
        """``POST /api/publishers`` ``{"action", "group", ...}``:

        - ``preview``: what the channel shows - its first key list's ``fingerprint``,
          the keys now, and its newest releases - before it is added;
        - ``add`` with ``fingerprint`` (the one the person compared with what the
          publisher says elsewhere), and optionally ``name`` and ``follow``;
        - ``follow`` and ``remove``.

        Answers the preview, or the publishers as ``GET`` does."""
        s = self._ready()
        action = str(body.get("action", ""))
        group = str(body.get("group", "")).strip()
        if action not in ACTIONS:
            raise SessionError(f"action is one of {', '.join(ACTIONS)}")
        if action == "preview":
            return preview_fields(await s.publisher_preview(group))
        if action == "add":
            return await s.add_publisher(group, str(body.get("fingerprint", "")),
                                         str(body.get("name", "")), bool(body.get("follow")))
        return s.change_publisher(action, group)
