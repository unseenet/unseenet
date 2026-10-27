"""Spam reports (UN-RFC 0045) for front ends: the issuers you follow, posts hidden by
reports, and being an issuer.

Belongs here: ``GET /api/reports``, ``POST /api/reports/follow``, ``POST
/api/reports/refresh``, ``POST /api/groups/{gid}/show`` (a hidden post shown anyway),
``POST /api/reports/start``, ``POST /api/reports/publish``, ``GET /api/reports/mine``,
``POST /api/reports/withdraw``, ``GET /api/reports/received`` and ``POST
/api/reports/hierarchy`` (a maintainer names its readers' default issuers).

A post hidden by a report keeps its place in every list with ``reported`` set (who,
why, which report) - front ends show "Hidden by *issuer*: spam" there, with "Show
anyway" and "Stop following this issuer" (section 7.3).

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import *  # noqa: F403  - the module's names, as when this was one file
from ....core import reports as rpt


def _report(r: rpt.Report) -> dict:
    return {"id": r.message_id, "date": r.date.isoformat(), "note": r.note,
            "posts": [{"id": p.id, "group": p.group, "reason": p.reason} for p in r.posts],
            "keys": [{"key": k.key, "reason": k.reason, "until": rpt.iso(k.until)} for k in r.keys]}


class Reports:
    def reports(self) -> dict:
        """``GET /api/reports``: the issuers you follow and those your hierarchies name
        (``issuers``: key, label, yours, hierarchies, on), the reasons a report can
        give, and you as an issuer (``mine``: your group, policy, contact, automatic -
        or null before you start one)."""
        s = self._ready()
        mine = None
        try:
            name = s.issuer_for()                       # yours, or one beside it in the vault
        except SessionError:
            name = None
        if name:
            gid = s.my_reports_group(name)
            m = s.manifest_data(gid)
            mine = {"group": gid, "policy": m.get("policy", ""), "contact": m.get("contact", ""),
                    "automatic": m.get("automatic") is True, "identity": name,
                    "label": s.identity_label(s.identity(name).key_text, s.display_name(name))
                    if name != s.default_identity_name() else "you"}
        return {"issuers": s.report_issuers(), "reasons": list(rpt.REASONS),
                "reason_labels": dict(rpt.REASON_LABELS), "mine": mine}

    async def follow_issuer(self, body: dict) -> dict:
        """``POST /api/reports/follow`` with ``key`` and ``on`` (true: follow in every
        group, also turning one a hierarchy names back on; false: stop following), and
        an optional ``label``. Reads the issuer's reports at once. Returns as ``GET``."""
        s = self._ready()
        key = _key(body.get("key"))
        if body.get("on", True):
            s.follow_issuer(key, str(body.get("label", "")))
            try:
                await s.refresh_reports()
            except NETWORK_ERRORS:
                pass                         # read with the next refresh
        else:
            s.unfollow_issuer(key)
        s.emit(ev.GroupsChanged())           # what is hidden may differ everywhere
        return self.reports()

    async def refresh_reports(self) -> dict:
        """``POST /api/reports/refresh``: read the reports of the issuers that apply."""
        s = self._ready()
        n = await s.refresh_reports()
        s.emit(ev.GroupsChanged())
        return {"issuers": n, "reports": len(s.report_book().reports)}

    def show_reported(self, gid: str, body: dict) -> dict:
        """``POST /api/groups/{gid}/show`` with ``id``: show a post hidden by a report
        anyway, on this device (section 7.3)."""
        s = self._ready()
        mid = str(body.get("id", ""))
        if not mid.startswith("<"):
            raise SessionError("id: the post's Message-ID")
        s.show_reported(mid)
        s.emit(ev.GroupUpdated(gid))
        return {"id": mid}

    async def start_reports(self, body: dict) -> dict:
        """``POST /api/reports/start`` with ``policy``, ``contact`` and ``automatic``:
        start or change your reports group. With ``"separate": {"name", "display"}``
        the issuer is a new identity beside yours in the vault - for an organisation
        or a hierarchy - and yours stays the one in use. Returns as ``GET``."""
        s = self._ready()
        args = (str(body.get("policy", "")), str(body.get("contact", "")), bool(body.get("automatic")))
        sep = body.get("separate")
        if sep:
            name = str((sep or {}).get("name") or "reports").strip()
            if name in s.data["identities"]:
                raise SessionError(f"there is already an identity {name!r} in this vault")
            s.new_identity(name, str((sep or {}).get("display") or "Spam reports").strip())
            with s._acting(name):
                await s.start_reports(*args)
        else:
            try:
                name = s.issuer_for()
            except SessionError:
                name = s.default_identity_name()
            with s._acting(name):
                await s.start_reports(*args)
        s.emit(ev.GroupsChanged())
        return self.reports()

    async def publish_report(self, body: dict) -> dict:
        """``POST /api/reports/publish`` with ``posts`` ([{id, group, reason}]), ``keys``
        ([{key, reason, days}], days 1-365, 365 when left out) and ``note``."""
        s = self._ready()
        now = datetime.now(timezone.utc)
        try:
            posts = [(str(p["id"]), str(p["group"]), str(p.get("reason", "spam")))
                     for p in body.get("posts", [])]
            keys = []
            for k in body.get("keys", []):
                days = int(k.get("days", 365))
                if not 1 <= days <= 365:
                    raise SessionError("days: 1 to 365")
                keys.append((_key(k.get("key")), str(k.get("reason", "spam")),
                             None if days == 365 else now + timedelta(days=days)))
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionError(f"posts and keys: {exc}") from exc
        issuer = s.issuer_for()                         # checked now, before the job
        note = str(body.get("note", ""))
        from ....core import reports as _r
        try:
            _r.report_body(posts, keys, note)           # a mistake is said at once, not later
        except (ValueError, crypto.CryptoError) as exc:
            raise SessionError(str(exc)) from exc

        # a job: the issuer's postage (and, the first time, its ripening) can take
        # minutes; the job's events (section 5) say when it is published
        async def send() -> str:
            return await s.publish_report(posts, keys, note, issuer)
        return {"job": self._new_job(s.my_reports_group(issuer), send)}

    async def my_reports(self) -> dict:
        """``GET /api/reports/mine``: the reports you published, newest first."""
        return {"reports": [_report(r) for r in await self._ready().my_reports()]}

    async def withdraw_report(self, body: dict) -> dict:
        """``POST /api/reports/withdraw`` with ``id``: withdraw one of your reports."""
        return {"id": await self._ready().withdraw_report(str(body.get("id", "")))}

    def received_reports(self) -> dict:
        """``GET /api/reports/received``: reports others sent you (the post, its group
        and its author), for an issuer to look at and publish."""
        s = self._ready()
        out = []
        for m in s.reports_sent_to_you():                   # your inbox and team inboxes
            found = s.received_report(m)
            if found:
                out.append({"message": m.message_id, "subject": m.subject, "date": m.date.isoformat()
                            if m.date else None, "id": found[0], "group": found[1],
                            "author_key": found[2] or None, "reason": found[3],
                            "inbox": m.group, "from": m.sender_key})
        return {"received": out}

    async def hierarchy_issuers(self, body: dict) -> dict:
        """``POST /api/reports/hierarchy`` with ``hierarchy`` and ``keys`` (the whole
        list, at most 16): as its maintainer, name the issuers its readers follow by
        default (section 7.1)."""
        s = self._ready()
        keys = [_key(k) for k in body.get("keys", [])]
        h = await naming.set_report_issuers(s, str(body.get("hierarchy", "")), keys)
        return {"hierarchy": h, "keys": keys}
