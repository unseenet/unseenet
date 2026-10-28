"""Your own rules (UN-RFC 0046 section 4.20, UN-RFC 0051): reading, writing, checking and
turning them off, seen marks, watched and ignored threads, and the score, actions and
"Why?" each row gets when you have rules.

Belongs here: ``GET``/``POST /api/rules``, ``POST /api/rules/check``, ``POST
/api/groups/{gid}/seen``, ``POST /api/threads``, and ``_score_rows`` - what a group's or
the timeline's rows get from your rules. Without rules nothing here changes a row.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from datetime import datetime

from . import *  # noqa: F403  - the module's names, as when this was one file


def _problems(rs) -> list[dict]:
    return [{"line": p.line, "message": p.message} for p in rs.problems]


class Rules:
    def group_settings_help(self) -> dict:
        """``GET /api/help/group-settings`` (unseenet-gui#178): per setting of Edit group,
        what it does, whom it affects and what changing it later does - ``{"intro",
        "settings": [{"key", "label", "what", "affects", "later"}]}``, the same text in
        every client. Needs no unlocked vault."""
        from ...settings_help import group_settings_help
        return group_settings_help()

    def rules(self) -> dict:
        """``GET /api/rules``: your rules as you wrote them, whether they are on, how many
        are used and the lines that are not, each with why - and ``suggestion``, the text
        every client offers when you have none (never used unless you save it), and
        ``help``, the language in short, the same in every client."""
        from ...scoring import HELP, SUGGESTION
        s = self._ready()
        text = s.feed_rules()
        rs = s.check_feed_rules(text)
        return {"text": text, "on": s.rules_on(), "rules": len(rs.rules), "problems": _problems(rs),
                "suggestion": SUGGESTION, "help": HELP}

    def set_rules(self, body: dict) -> dict:
        """``POST /api/rules`` with ``text`` (your rules; "" removes them) and/or ``on``
        (use them, or turn them off and keep the text). Returns as ``GET``."""
        s = self._ready()
        if "text" in body:
            if not isinstance(body["text"], str):
                raise SessionError("text must be text")
            try:
                s.set_feed_rules(body["text"])
            except SessionError as exc:
                raise SessionError(str(exc)) from exc
        if "on" in body:
            s.set_rules_on(bool(body["on"]))
        s.emit(ev.GroupsChanged())          # every list may look different now
        return self.rules()

    def check_rules(self, body: dict) -> dict:
        """``POST /api/rules/check`` with ``text``: how many rules would be used and the
        problems of the lines that would not, without keeping anything."""
        rs = self._ready().check_feed_rules(str(body.get("text", "")))
        return {"rules": len(rs.rules), "problems": _problems(rs)}

    def mark_seen(self, gid: str, body: dict) -> dict:
        """``POST /api/groups/{gid}/seen`` with ``until`` (ISO 8601): everything in the group
        dated up to then has been seen - shown, not opened (UN-RFC 0044 4.5)."""
        s = self._ready()
        try:
            until = datetime.fromisoformat(str(body.get("until", "")).replace("Z", "+00:00"))
        except ValueError as exc:
            raise SessionError("until: a date and time, e.g. 2026-10-26T18:00:00Z") from exc
        if until.tzinfo is None:
            raise SessionError("until needs a time zone")
        s.mark_seen(gid, until)
        return {"seen_to": s.seen_to(gid)}

    def thread_mark(self, body: dict) -> dict:
        """``POST /api/threads`` with ``id`` (the thread's first post) and ``mark``:
        "watched", "ignored" or "" (neither)."""
        s = self._ready()
        mid = str(body.get("id", ""))
        if not mid.startswith("<"):
            raise SessionError("id: the Message-ID of the thread's first post")
        try:
            s.set_thread_mark(mid, str(body.get("mark", "")))
        except SessionError as exc:
            raise SessionError(str(exc)) from exc
        s.emit(ev.GroupsChanged())
        return {"id": mid, "mark": s.thread_mark(mid)}

    @staticmethod
    def _score_rows(out: list[dict], results) -> None:
        """Put each row's score, actions, whether it is hidden and why (UN-RFC 0051
        section 10) on it; only called when there are rules."""
        for row, res in zip(out, results):
            row["score"] = res.score
            row["actions"] = sorted(res.actions)
            row["hidden"] = not res.shown
            row["why"] = res.explain()
