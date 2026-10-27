"""Content labels (UN-RFC 0053) for front ends: the labellers that count, what to do
with each warning, and being a labeller.

Belongs here: ``GET /api/labels``, ``POST /api/labels/follow`` (``{"key", "label",
"topics", "follow": false}`` to stop), ``POST /api/labels/warning`` (``{"warning",
"choice"}``), ``POST /api/labels/refresh``, ``POST /api/labels/start`` and ``POST
/api/labels/publish`` (a job). Every row has ``labels``: the post's warnings (by whom,
the reader's choice) and topics, and ``action`` - show, blur or hide - which a front
end follows, never silently (section 6).

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from ....core import labels as lb
from ....core import tags as tg


class ContentLabels:
    def labels(self) -> dict:
        s = self._ready()
        mine = None
        if s.is_labeller():
            m = s.manifest_data(s.my_labels_group())
            mine = {"group": s.my_labels_group(), "policy": m.get("policy", ""),
                    "contact": m.get("contact", ""), "automatic": m.get("automatic") is True,
                    "topics": m.get("topics") is True}
        return {"labellers": s.labellers(), "warnings": [
                    {"warning": w, "label": tg.WARNING_LABELS[w], "choice": c}
                    for w, c in s.warning_choices().items()],
                "mine": mine}

    async def follow_labeller(self, body: dict) -> dict:
        s = self._ready()
        key = str(body.get("key", "")).strip()
        if body.get("follow") is False:
            s.unfollow_labeller(key)
        else:
            s.follow_labeller(key, str(body.get("label", "")), bool(body.get("topics")))
            self.spawn(s.refresh_labels())
        s.emit(ev.GroupsChanged())
        return self.labels()

    def warning_choice(self, body: dict) -> dict:
        s = self._ready()
        s.set_warning_choice(str(body.get("warning", "")), str(body.get("choice", "")))
        s.emit(ev.GroupsChanged())
        return self.labels()

    async def refresh_labels(self) -> dict:
        return {"labellers": await self._ready().refresh_labels()}

    async def start_labels(self, body: dict) -> dict:
        s = self._ready()
        await s.start_labels(str(body.get("policy", "")), str(body.get("contact", "")),
                             bool(body.get("automatic")), bool(body.get("topics")))
        return self.labels()

    async def publish_labels(self, body: dict) -> dict:
        """``{"posts": [{"id", "group", "labels"}], "note"}``: answers ``{"job"}`` at
        once - postage takes a while, as for a report (UN-RFC 0046 section 5)."""
        s = self._ready()
        try:
            posts = [(str(p["id"]), str(p["group"]), list(p.get("labels") or []))
                     for p in body.get("posts") or []]
            lb.label_body(posts, str(body.get("note", "")))
        except (KeyError, TypeError, lb.LabelError) as exc:
            raise SessionError(f"posts: {exc}") from exc
        if not s.is_labeller():
            raise SessionError("start your labels channel first")
        note = str(body.get("note", ""))

        async def send() -> str:
            return await s.publish_labels(posts, note)
        return {"job": self._new_job(s.my_labels_group(), send)}
