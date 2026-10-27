"""People and safety (UN-RFC 0046 section 4.6): contacts, ignoring, reporting, blocking.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class People:
    # --- people and safety (section 4.6) --------------------------------------
    def contact(self, data: dict) -> dict:
        """``POST /api/contacts`` (section 4.6): add a key to your contacts with a name, or
        remove it (``remove`` true)."""
        s = self._ready()
        key = _key(data.get("key"))
        if data.get("remove"):
            s.remove_contact(key)
        else:
            s.add_contact(key, str(data.get("name", "")).strip())
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    def close_chat(self, data: dict) -> dict:
        """``POST /api/chats/close`` (section 4.6): take a chat with a person off the
        list (``on`` true, the default), or put it back. It is in your state (UN-RFC
        0044 section 4.2) and opens again by itself with the next chat line."""
        s = self._ready()
        key = _key(data.get("key"))
        if data.get("on", True):
            s.close_chat(key)
        else:
            s.open_chat(key)
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    def ignored(self) -> dict:
        """``GET /api/ignore`` (section 4.6): the keys you ignore, with their labels."""
        s = self._ready()
        return {"ignored": [{"key": k, "label": label or s.label_of(k)}
                            for k, label in s.ignored()]}

    def ignore(self, data: dict) -> dict:
        """``POST /api/ignore`` (section 4.6): ignore a key (``on`` true, with a ``label``) or
        stop ignoring it. Every open group is redrawn."""
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
        """``GET /api/groups/{gid}/report?id=`` (section 4.6): who a post can be reported
        to - moderators, the owner, the hierarchy's maintainers, the node operator."""
        s = self._ready()
        m = self._find(s, gid, message_id)
        return {"targets": [{"i": i, "who": who} for i, (who, _, _) in
                            enumerate(await s.report_targets(m))],
                "reasons": [{"id": k, "label": v} for k, v in REPORT_REASONS.items()]}

    async def report(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/report`` (section 4.6): report a post to the chosen
        targets (by their ``i`` from ``GET``), with a ``reason``, a ``note`` in Markdown
        and ``files`` (as on a post), optionally without your name."""
        s = self._ready()
        m = self._find(s, gid, str(data.get("id", "")))
        chosen = {int(i) for i in data.get("targets", [])}
        targets = [t for i, t in enumerate(await s.report_targets(m)) if i in chosen]
        if not targets:
            raise SessionError("report to whom?")
        # a screenshot or a document, encrypted to each receiver (UN-RFC 0027 3.3)
        files = self._files_to_post(s, s.my_inbox, data.get("files"), check=False)
        sent = await s.report(m, targets, str(data.get("note", "")).strip(),
                              anonymous=bool(data.get("anonymous")), files=files,
                              reason=str(data.get("reason", "")))
        return {"sent": sent}

    async def block(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/block`` (section 4.6): a hierarchy maintainer blocks a
        key in the hierarchy the group is in (UN-RFC 0018 section 8.2). Answers the hierarchy."""
        s = self._ready()
        where = await naming.block(s, gid, _key(data.get("key")),
                                   str(data.get("reason", "")).strip())
        s.emit(ev.GroupUpdated(gid))
        return {"hierarchy": str(where)}
