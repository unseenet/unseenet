"""People and safety (UN-RFC 0046 section 4.6): contacts, ignoring, reporting, blocking.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class People:
    # --- people and safety (section 4.6) --------------------------------------
    def contact(self, data: dict) -> dict:
        s = self._ready()
        key = _key(data.get("key"))
        if data.get("remove"):
            s.remove_contact(key)
        else:
            s.add_contact(key, str(data.get("name", "")).strip())
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    def ignored(self) -> dict:
        s = self._ready()
        return {"ignored": [{"key": k, "label": label or s.label_of(k)}
                            for k, label in s.ignored()]}

    def ignore(self, data: dict) -> dict:
        s = self._ready()
        key = _key(data.get("key"))
        if data.get("on", True):
            s.ignore(key, str(data.get("label", "")))
        else:
            s.unignore(key)
        self._redraw_all(s)
        return {"ok": True}

    @staticmethod
    def _redraw_all(s: Session) -> None:
        s.emit(ev.GroupsChanged())
        for gid in list(s.data["subscribed"]):
            s.emit(ev.GroupUpdated(gid))

    async def report_targets(self, gid: str, message_id: str) -> dict:
        s = self._ready()
        m = self._find(s, gid, message_id)
        return {"targets": [{"i": i, "who": who} for i, (who, _, _) in
                            enumerate(await s.report_targets(m))]}

    async def report(self, gid: str, data: dict) -> dict:
        s = self._ready()
        m = self._find(s, gid, str(data.get("id", "")))
        chosen = {int(i) for i in data.get("targets", [])}
        targets = [t for i, t in enumerate(await s.report_targets(m)) if i in chosen]
        if not targets:
            raise SessionError("report to whom?")
        sent = await s.report(m, targets, str(data.get("note", "")).strip(),
                              anonymous=bool(data.get("anonymous")))
        return {"sent": sent}

    async def block(self, gid: str, data: dict) -> dict:
        s = self._ready()
        where = await naming.block(s, gid, _key(data.get("key")),
                                   str(data.get("reason", "")).strip())
        s.emit(ev.GroupUpdated(gid))
        return {"hierarchy": str(where)}
