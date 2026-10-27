"""Session: spam reports (UN-RFC 0045) - following issuers, what they report, and
issuing reports yourself.

**Each reader decides.** A report hides nothing for a reader who does not follow its
issuer. A client follows the issuers a group's hierarchy names, for that hierarchy's
groups only (section 7.1), and those the reader chose, for every group (7.2); the
reader can stop following any of them, those the hierarchy names too. A hidden post is
never hidden silently: ``visible`` marks it (``Message.reported``) and clients show
"Hidden by *issuer*: spam" in its place, one action from being shown (7.3). Your own
posts and your contacts' are never hidden by reports.

Belongs here: which issuers you follow and which apply to a group, reading their
``reports@`` groups (``refresh_reports``), what they say about a post (``report_hit``),
showing a hidden post anyway, and being an issuer: starting your ``reports@`` group,
publishing and withdrawing reports, and turning a report you received into one.

Not here: the form of reports and the book (``core/reports.py``), the issuers a
hierarchy names (``hierarchies.py``), sending a report to someone (people.py).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

import re
from . import *  # noqa: F403  - the shared names: SessionError, Message, ...
from .. import session as _s   # names tests patch on the module, read at call time
from ... import hierarchies as hz
from ...core import reports as rpt
from ...core.groups import make_manifest

SHOWN_MAX = 500            # posts shown anyway, remembered on this device
ISSUERS_TTL = 30.0         # seconds the issuers per group are kept (hierarchy lists change rarely)


class ReportsMixin:
    # --- which issuers you follow (section 7) ---
    def _issuer_settings(self) -> dict:
        """``{"follow": {key: label}, "off": [key, ...]}``: issuers you chose, and those
        a hierarchy names that you turned off. Part of your settings (UN-RFC 0044)."""
        s = self.data.setdefault("report_issuers", {})
        s.setdefault("follow", {})
        s.setdefault("off", [])
        return s

    def hierarchy_issuers(self, group_id: str) -> dict[str, str]:
        """{issuer key: hierarchy} that the maintainers above a group name (7.1)."""
        if group_id.startswith("inbox@") or "@" not in group_id:
            return {}
        try:
            name = group_id.rpartition("@")[0]
            return hz.report_issuers_for(name, naming.root_list(self), naming.hierarchy_lists(self))
        except Exception:  # noqa: BLE001  lists that cannot be read name nobody
            return {}

    def _issuer_cache(self) -> dict:
        import time
        cache = getattr(self, "_issuers_cached", None)
        if cache is None or time.monotonic() - cache["at"] > ISSUERS_TTL:
            cache = self._issuers_cached = {"at": time.monotonic(), "groups": {}, "read": None}
        return cache

    def _issuers_changed(self) -> None:
        self._issuers_cached = None
        self._report_book = None

    def named_issuers(self, group_id: str) -> dict[str, str]:
        """{issuer key: where it is named}: by the group's hierarchy (``"dk"``) and by
        the group's owner (``"group"``, section 7.5)."""
        out = dict(self.hierarchy_issuers(group_id))
        for k in rpt.group_issuers(self.manifest_data(group_id)):
            out.setdefault(k, "group")
        return out

    def report_issuers_for(self, group_id: str) -> set[str]:
        """The issuers whose reports apply in a group: those its hierarchy and its
        owner name, unless you turned them off, and those you follow yourself."""
        groups = self._issuer_cache()["groups"]
        if group_id not in groups:
            s = self._issuer_settings()
            out = {k for k in self.named_issuers(group_id) if k not in s["off"]}
            groups[group_id] = out | set(s["follow"])
        return set(groups[group_id])

    def report_issuers(self) -> list[dict]:
        """Every issuer you follow, or that a hierarchy or the owner of one of your
        groups names, each ``{"key", "label", "yours": bool, "hierarchies": [...],
        "groups": [Group ID, ...], "on": bool}``."""
        s = self._issuer_settings()
        named: dict[str, set[str]] = {}
        by_group: dict[str, set[str]] = {}
        for gid in self.data.get("subscribed", []):
            for key, h in self.hierarchy_issuers(gid).items():
                named.setdefault(key, set()).add(h)
            for key in rpt.group_issuers(self.manifest_data(gid)):    # section 7.5
                by_group.setdefault(key, set()).add(gid)
        out = []
        for key in sorted(set(named) | set(by_group) | set(s["follow"])):
            out.append({"key": key,
                        "label": self.issuer_label(key),
                        "yours": key in s["follow"],
                        "hierarchies": sorted(named.get(key, ())),
                        "groups": sorted(by_group.get(key, ())),
                        "on": key in s["follow"] or key not in s["off"]})
        return out

    def issuer_label(self, key: str) -> str:
        """What you call an issuer: the name you gave it when following, else its label."""
        return self._issuer_settings()["follow"].get(key) or self.identity_label(key)

    def follow_issuer(self, key: str, label: str = "") -> None:
        """Follow an issuer's reports in every group (section 7.2); also turns one a
        hierarchy names back on."""
        key = key.strip()
        try:
            crypto.key_from_text(key)
        except crypto.CryptoError as exc:
            raise SessionError(f"not a key: {key}") from exc
        s = self._issuer_settings()
        s["follow"][key] = label.strip() or s["follow"].get(key, "")
        if key in s["off"]:
            s["off"].remove(key)
        self._issuers_changed()
        self.save()

    def unfollow_issuer(self, key: str) -> None:
        """Stop following an issuer, also one a hierarchy names (section 7.2)."""
        s = self._issuer_settings()
        s["follow"].pop(key, None)
        if key not in s["off"] and any(
                key in self.named_issuers(g) for g in self.data.get("subscribed", [])):
            s["off"].append(key)
        self._issuers_changed()
        self.save()

    # --- what the issuers report ---
    def _issuers_to_read(self) -> set[str]:
        """The issuers that apply to any group you follow, and those you follow."""
        cache = self._issuer_cache()
        if cache["read"] is None:
            out = set(self._issuer_settings()["follow"])
            for gid in self.data.get("subscribed", []):
                out |= self.report_issuers_for(gid)
            cache["read"] = out
        return set(cache["read"])

    async def refresh_reports(self) -> int:
        """Read the ``reports@`` groups of the issuers that apply to your groups, with
        the other groups, over Tor as always (section 10). Returns how many issuers
        could be read."""
        read = 0
        for key in sorted(self._issuers_to_read()):
            try:
                gid = rpt.reports_group(crypto.key_from_text(key))
                m = await self.fetch_manifest(gid)
                if m is None or m.expired():
                    continue
                self.group_entry(gid)["manifest"] = dict(m.raw)
                await self.fetch_group(gid)
                read += 1
            except (SessionError, OSError, ConnectionError, NNTPError, crypto.CryptoError) as exc:
                log.debug("reports of %s not read: %s", key, exc)
        self._issuers_changed()
        return read

    def report_book(self) -> rpt.Book:
        """What the issuers that apply to you have reported, from the ``reports@``
        groups read; withdrawn reports are gone with their articles."""
        cached = getattr(self, "_report_book", None)
        if cached is not None:
            return cached
        book = rpt.Book()
        for key in self._issuers_to_read():
            try:
                gid = rpt.reports_group(crypto.key_from_text(key))
            except crypto.CryptoError:
                continue
            automatic = self.manifest_data(gid).get("automatic") is True
            for msg in self.cache.get(gid, {}).values():
                report = self._as_report(msg)
                if report is not None:
                    book.add(report, automatic)
        self._report_book = book
        return book

    def report_hit(self, msg: "Message", issuers: set[str] | None = None) -> dict | None:
        """Why a post is hidden by a report, or None: ``{"issuer", "label", "reason",
        "automatic", "kind" ("post" or "key"), "report"}``. Private posts, your own,
        your contacts' and the reports themselves are never hidden (section 7.3)."""
        if (msg.private or msg.to_key is not None or msg.group.startswith("inbox@")
                or rpt.is_reports_group(msg.group) or not msg.author_key):
            return None
        if msg.author_key in self._my_keys() or msg.author_key in self.data.get("contacts", {}):
            return None
        if issuers is None:
            issuers = self.report_issuers_for(msg.group)
        if not issuers:
            return None
        book = self.report_book()
        hit = book.post(msg.message_id, issuers) or book.key(msg.author_key, issuers)
        if hit is None:
            return None
        return {"issuer": hit.issuer, "label": self.issuer_label(hit.issuer),
                "reason": hit.reason, "automatic": hit.automatic, "kind": hit.kind,
                "report": hit.report}

    def mark_reported(self, msgs: list["Message"]) -> list["Message"]:
        """Set ``Message.reported`` on posts hidden by reports (not on those you chose
        to show anyway). Clients show those as hidden, with why (section 7.3)."""
        if not self._issuers_to_read():
            for m in msgs:
                m.reported = None
            return msgs
        shown = set(self.data.get("reports_shown", []))
        per_group: dict[str, set[str]] = {}
        for m in msgs:
            if m.group not in per_group:
                per_group[m.group] = self.report_issuers_for(m.group)
            m.reported = None if m.message_id in shown else self.report_hit(m, per_group[m.group])
        return msgs

    def show_reported(self, message_id: str) -> None:
        """Show a post hidden by a report anyway (section 7.3), on this device."""
        shown = self.data.setdefault("reports_shown", [])
        if message_id not in shown:
            shown.append(message_id)
            del shown[:-SHOWN_MAX]
            self.save()

    def hidden_by_reports(self, group_id: str) -> list[tuple[str, str, int]]:
        """(issuer label, reason, posts) hidden in a group by reports."""
        counts: dict[tuple[str, str], int] = {}
        for m in self.mark_reported(list(self.cache.get(group_id, {}).values())):
            if m.reported:
                k = (m.reported["label"], m.reported["reason"])
                counts[k] = counts.get(k, 0) + 1
        return [(who, why, n) for (who, why), n in sorted(counts.items())]

    # --- being an issuer (sections 3, 4) ---
    def my_reports_group(self, name: str | None = None) -> str:
        """``reports@<fingerprint>`` of this identity, started or not."""
        return rpt.reports_group(self.identity(name).public_key)

    def is_issuer(self, name: str | None = None) -> bool:
        """Whether an identity (the one in use by default) has started its reports group
        in this vault."""
        gid = self.my_reports_group(name)
        return bool(self.data["groups"].get(gid, {}).get("owner"))

    def issuer_names(self) -> list[str]:
        """The identities in this vault that issue spam reports - yours, or one added
        beside it (a project's issuer in its maintainer's everyday vault): reports sent
        to you can then be published from where you read them."""
        return [n for n in self.data.get("identities", {}) if self.is_issuer(n)]

    def issuer_for(self, name: str | None = None) -> str:
        """The identity to publish reports as: ``name``, else the one in use if it is
        an issuer, else the vault's only issuer. SessionError if there is none."""
        names = self.issuer_names()
        if name is not None:
            if name not in names:
                raise SessionError(f"{name} issues no reports here")
            return name
        here = self.default_identity_name()
        if here in names:
            return here
        if len(names) == 1:
            return names[0]
        raise SessionError("start your reports group first (start_reports)" if not names
                           else "which issuer? " + ", ".join(names))

    def _acting(self, name: str):
        """Act as identity ``name`` for a moment: every key, postage and ripening then
        is that identity's."""
        import contextlib

        @contextlib.contextmanager
        def ctx():
            before = self._acting_as
            self._acting_as = name
            try:
                yield
            finally:
                self._acting_as = before
        return ctx()

    async def start_reports(self, policy: str = "", contact: str = "",
                            automatic: bool = False) -> str:
        """Start, or change, this identity's ``reports@`` channel: what it reports
        (``policy``), where to object (``contact``: an inbox or a URL), and whether a
        program makes the reports (section 8). Your inbox is made too, if you have none:
        reports sent to you arrive there. Returns its Group ID."""
        extra = {"policy": policy.strip() or None, "contact": contact.strip() or None,
                 "automatic": True if automatic else None}
        gid = self.my_reports_group()
        try:
            current = await self.fetch_manifest(gid)
        except (SessionError, OSError, ConnectionError, NNTPError):
            current = None
        serial = max(int(self.manifest_data(gid).get("serial", 0)),
                     current.serial if current else 0) + 1
        try:
            art = make_manifest(self.identity(), rpt.GROUP_NAME, "channel", serial=serial,
                                title="Spam reports", min_pow=_s.DEFAULT_POW,
                                extra=extra, pow_bits=await self.required_pow(gid),
                                lifetime=self.key_bound_lifetime())
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        await self._post_article(art)
        entry = self.group_entry(gid)
        entry["manifest"] = json.loads(art.body)
        entry.update({"type": "channel", "owner": True})
        self.save()
        await self.ensure_inbox()           # reports sent to you arrive there (section 7.4)
        return gid

    async def publish_report(self, posts=(), keys=(), note: str = "", issuer: str | None = None) -> str:
        """Publish a report in an issuer's ``reports@`` group: ``posts`` as (Message-ID,
        Group ID, reason), ``keys`` as (key, reason, until or None for 365 days).
        ``issuer``: the identity to publish as (``issuer_for``). The reporter's key is
        never in it (section 7.4). Returns its Message-ID."""
        name = self.issuer_for(issuer)
        if name != self.default_identity_name():
            with self._acting(name):
                return await self.publish_report(posts, keys, note, name)
        try:
            body = rpt.report_body(posts, keys, note)
        except (ValueError, crypto.CryptoError) as exc:
            raise SessionError(str(exc)) from exc
        gid, me = self.my_reports_group(), self.identity()
        art = await self._post_with_postage(gid, lambda bits: rpt.report_article(
            me, body, from_name=self.display_name() or "Report issuer", pow_bits=bits))
        self._report_book = None
        return art.message_id

    async def my_reports(self, issuer: str | None = None) -> list[rpt.Report]:
        """The reports an issuer here has published that are still there, newest first."""
        try:
            name = self.issuer_for(issuer)
        except SessionError:
            return []
        gid = self.my_reports_group(name)
        out = [r for r in map(self._as_report, await self.fetch_group(gid)) if r is not None]
        return sorted(out, key=lambda r: r.date, reverse=True)

    @staticmethod
    def _as_report(msg: "Message") -> rpt.Report | None:
        """A post in a ``reports@`` group as a report; None if it is not one."""
        if not msg.readable:
            return None
        try:
            return rpt.read_report(msg.message_id, msg.group, msg.author_key, msg.date, msg.body)
        except rpt.ReportError:
            return None

    async def withdraw_report(self, message_id: str, issuer: str | None = None) -> str:
        """Withdraw one of an issuer's reports: what it said no longer counts (section 4)."""
        name = self.issuer_for(issuer)
        with self._acting(name):
            mid = await self.withdraw(self.my_reports_group(name), message_id)
        self._report_book = None
        return mid

    def reports_sent_to_you(self) -> list["Message"]:
        """Reports others sent you: in your inbox and in the team inboxes you read
        (an issuer's or a hierarchy's contact), newest first."""
        msgs = list(self.private_messages())
        for gid in self.data.get("team_keys", {}):
            msgs += [m for m in self.cache.get(gid, {}).values() if m.readable]
        seen, out = set(), []
        for m in sorted(msgs, key=lambda m: m.date or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
            if m.message_id not in seen and self.received_report(m):
                seen.add(m.message_id)
                out.append(m)
        return out

    def received_report(self, msg: "Message") -> tuple[str, str, str, str] | None:
        """(Message-ID, Group ID, author key, reason) named in a report someone sent
        you, so an issuer can publish it - without the reporter (section 7.4). The
        reason is one of UN-RFC 0045's; one it does not know is ``other``."""
        found = self.report_fields(msg)
        if "Group" not in found or "Message-ID" not in found:
            return None
        why = next((k for k, v in REPORT_REASONS.items() if v == found.get("Reason")), "spam")
        return (found["Message-ID"], found["Group"], found.get("Author key", ""),
                why if why in rpt.REASONS else "other")
