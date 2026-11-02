"""A replica's duties for a list council (UN-RFC 0020), beside the registrar's.

One replica, one key, several councils: the same ``unseenet-replica`` that is a member
of the names council can be a member of a list council too (``lists`` in its config,
set when it signs that council's genesis). For that council it

- **measures** the announced nodes once a day, at a random time: reaches each over Tor,
  checks that it answers with the node key it announced with (UN-RFC 0016), notes the
  software it states and the groups it lists, reads which of yesterday's canaries it
  has, and posts today's canary to it alone (UN-RFC 0021);
- **reports** what it found: ``report <date>`` in the council's reports group (section 7);
- **computes** the node list for the day before yesterday - by then every member's
  report of that day is in - and posts it to the council's node list group when it
  differs from the newest there, or that one is a month old (section 8).

Belongs here: reading and posting for a list council. Not here: the rules, which are
pure and shared (``core/lists.py``); the registrar's duties (``run.py``).

Part of ``Replica`` (see run.py)."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import date, datetime, time, timedelta, timezone

from ..core import announcements as an
from ..core import carrying as ca
from ..core import council as cn
from ..core import crypto
from ..core import lists as ls
from ..core.article import new_article
from ..core.encoding import b64
from ..core.groups import is_key_bound
from ..known_nodes import NODES_ANNOUNCE_GROUP
from ..nntp import strip_reader_headers

log = logging.getLogger("unseenet.replica")

LIST_LAG = 2                       # the list for the day before yesterday: all reports are in
REPOST_AFTER = timedelta(days=30)  # section 8: at least monthly
REACH_TIMEOUT = 240.0              # one node, over Tor
MEASURE_BETWEEN = (1 * 3600, 20 * 3600)   # seconds into the UTC day: a random time within
FROM = "Unseenet list council"


def _day(t: datetime) -> date:
    return t.astimezone(timezone.utc).date()


def _start(d: date) -> datetime:
    return datetime.combine(d, time(), timezone.utc)


def network_groups():
    """The network's own groups as every replica of this version sees them: the
    infrastructure groups and the endorsed groups of the shipped hierarchy list for
    ``unseenet``. (Once the list council keeps ``unseenet.*``, its own list.)"""
    from .. import hierarchies as hz
    return ca.network_groups(hz.builtin_checkgroups().groups.values())


class ListDuties:
    """Mixed into ``Replica``: ``self.s`` (the Session), ``self.me``, ``self.st``,
    ``self.now``, ``self.rng``, ``self.status``."""

    def _lists_state(self) -> dict:
        st = self.st.setdefault("lists", {})
        for k, empty in (("measure_at", {}), ("measured", None), ("posted_canaries", {}),
                         ("computed", None)):
            st.setdefault(k, empty)
        return st

    async def _lists_round(self, cfg: dict, now: datetime) -> None:
        group = cfg.get("lists")
        if not group:
            return
        out = self.status.setdefault("lists", {"group": group})
        chain = await self.s.council_chain(group)
        cur = chain.current
        if cur is None:
            out["note"] = "the list council does not count yet (its genesis is not signed by all)"
            return
        if cur.member(self.me.public_key) is None:
            out["note"] = "this replica is not a member of the list council"
            return
        if chain.disputed:
            out["note"] = "the list council's manifests disagree: nothing is posted"
            return
        try:
            lc = ls.list_council(cur.data)
        except ls.ListProblem as exc:
            out["note"] = f"the list council's manifest is not usable: {exc}"
            return
        if lc is None or "nodes" not in lc.lists:
            out["note"] = "the council keeps no node list"
            return
        st = self._lists_state()
        await self._lists_public(chain, cfg, now, out)
        members = {crypto.key_to_text(k) for k in cur.keys}
        announcements = await self._read_announcements()
        today = _day(now)
        await self._measure(lc, members, announcements, today, now)
        await self._compute_and_post(lc, chain, members, announcements, today, now)
        out.update({"members": len(members), "announced": len({a.key for a in announcements}),
                    "measured": st["measured"], "computed": st["computed"],
                    "listed": st.get("listed", 0)})

    async def _lists_public(self, chain: cn.Chain, cfg: dict, now: datetime, out: dict) -> None:
        """The list council's proposals, hearings and log (UN-RFC 0061), by the same code
        as the registrar's, on this council's own part of the state: what it signed,
        held, logged and decided is kept apart from the registrar's."""
        sub = self._lists_state().setdefault("public", {})
        for k, empty in (("signed", []), ("held", {}), ("logged", []), ("hearings_done", []),
                         ("applying", None), ("list_decisions", [])):
            sub.setdefault(k, empty)
        agreed = self.agreed(cfg)                       # from the replica's own state
        st, status = self.st, self.status
        self.st, self.status = sub, out
        try:
            await self._public(chain, now, agreed)
        finally:
            self.st, self.status = st, status
        out["decisions"] = len(sub["list_decisions"])

    def _list_decisions(self, day: date) -> ls.DecisionState:
        sub = self._lists_state().get("public", {})
        return ls.decisions_until([ls.Decision(date.fromisoformat(a), i, c)
                                   for a, i, c in sub.get("list_decisions", [])], day)

    # --- reading ----------------------------------------------------------------------------

    async def _read_announcements(self) -> list[an.Announcement]:
        found = []
        for m in await self.s.fetch_group(NODES_ANNOUNCE_GROUP):
            if not (m.readable and m.author_key and m.date):
                continue
            try:
                found.append(an.parse(m.body, key=m.author_key, date=m.date,
                                      message_id=m.message_id))
            except an.AnnouncementProblem:
                continue
        return found

    async def _read_reports(self, lc: ls.ListCouncil) -> tuple[list[ls.Report], list]:
        """(reports, canary messages) of the council's reports group."""
        reports, canaries = [], []
        for m in await self.s.fetch_group(lc.reports):
            if not (m.readable and m.author_key and m.date):
                continue
            subject = m.subject or ""
            if subject.startswith(ls.REPORT_PREFIX):
                try:
                    reports.append(ls.parse_report(m.body, key=m.author_key, date=m.date,
                                                   message_id=m.message_id))
                except ls.ListProblem:
                    continue
            elif subject.startswith(ls.CANARY_PREFIX):
                canaries.append(m)
        return reports, canaries

    async def _read_lists(self, group: str, members: set[str]) -> list[tuple]:
        """The node lists the members posted: (day, seq, body, node keys, Date)."""
        out = []
        for m in await self.s.fetch_group(group):
            if not (m.readable and m.author_key in members and m.date):
                continue
            # read as the council wrote it, not as a client would use it: a client leaves
            # out addresses it cannot use, which must not change who keeps a place
            try:
                data = json.loads(m.body)
                keys = {str(n["node_key"]) for n in data["nodes"]}
            except (ValueError, KeyError, TypeError):
                continue
            got = ls.updated_day(str(data.get("updated", "")))
            if got is None:
                continue
            seq, day = got
            out.append((day, seq, m.body.rstrip("\n") + "\n", keys, m.date))
        return sorted(out, key=lambda x: (x[0], x[4]))

    # --- measuring (section 7, UN-RFC 0021) --------------------------------------------------

    async def _measure(self, lc: ls.ListCouncil, members: set[str], announcements,
                       today: date, now: datetime) -> None:
        st = self._lists_state()
        if st["measured"] == today.isoformat():
            return
        at = st["measure_at"].setdefault(today.isoformat(), self.rng.randrange(*MEASURE_BETWEEN))
        if now < _start(today) + timedelta(seconds=at):
            return
        current = {a.key: a for a in an.newest(announcements, now).values()}
        _, canaries = await self._read_reports(lc)
        yesterday = today - timedelta(days=1)
        posted = set(st["posted_canaries"].get(yesterday.isoformat(), []))
        readings: dict[str, ls.Reading] = {}
        reached, missed, software = set(), set(), {}
        for key, a in sorted(current.items()):
            got = await self._reach(a, lc, members, yesterday)
            if got is None:
                missed.add(key)
                continue
            reading, soft = got
            reached.add(key)
            readings[key] = reading
            if soft:
                software[key] = soft
        disconnected, incomplete = ls.connection_verdicts(readings, posted, network_groups())
        body = ls.report_body(today, reached, missed, disconnected=disconnected,
                              incomplete=incomplete, software=software)
        await self._post_list_json(lc.reports, ls.report_subject(today), body)
        # today's canaries, each to its node alone, for tomorrow's reading
        sent = []
        for key in sorted(reached):
            if await self._post_canary(current[key], lc, today):
                sent.append(key)
        st["posted_canaries"] = {k: v for k, v in st["posted_canaries"].items()
                                 if k >= yesterday.isoformat()}
        st["posted_canaries"][today.isoformat()] = sent
        st["measure_at"] = {k: v for k, v in st["measure_at"].items() if k >= today.isoformat()}
        st["measured"] = today.isoformat()
        self.s.save()
        log.info("list council: measured %d node(s), %d reached, %d disconnected, %d incomplete",
                 len(current), len(reached), len(disconnected), len(incomplete))

    async def _reach(self, a: an.Announcement, lc: ls.ListCouncil, members: set[str],
                     yesterday: date) -> tuple[ls.Reading, str | None] | None:
        """Reach the node at its announced address; None unless it answers with the key
        it announced with."""
        from ..core import transport
        try:
            target = transport.connect_target(a.address)
        except transport.AddressProblem:
            return None
        since = _start(yesterday).strftime("%Y%m%d %H%M%S")

        async def run(c):
            info = {}
            if c.capability("UNSEENET-NODEINFO") is not None:
                lines = await c.multiline("LIST UNSEENET.NODEINFO", 215)
                info = json.loads(lines[0]) if lines else {}
            node_key = info.get("node_key")
            if not node_key or crypto.key_from_text(node_key) != crypto.key_from_text(a.key):
                return None
            groups = {line.split()[0] for line in await c.list_active() if line.strip()}
            r = ls.Reading(groups={g for g in groups if not is_key_bound(g)},
                           patterns=list(a.patterns))
            if lc.reports in groups:
                for msgid in await c.newnews(lc.reports, since):
                    raw = await c.article(msgid)
                    seen = _canary_in(raw, lc.reports, members, yesterday)
                    if seen:
                        r.seen.add(seen)
            soft = info.get("software")
            return r, (str(soft)[:ls.MAX_SOFTWARE] if soft else None)
        try:
            return await asyncio.wait_for(self.s._call(run, target), REACH_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - any failure is "not reached" today
            log.debug("list council: %s not reached: %s", a.address, exc)
            return None

    async def _post_canary(self, a: an.Announcement, lc: ls.ListCouncil, today: date) -> bool:
        from ..core import transport
        art = new_article(lc.reports, ls.canary_subject(a.key, today),
                          ls.canary_body(a.key, today, b64(secrets.token_bytes(16))),
                          from_name=FROM, extra=[("Content-Type", "application/json")])
        try:
            await asyncio.wait_for(
                self.s.post_article(art, node=transport.connect_target(a.address),
                                    sign_with=self.me), REACH_TIMEOUT)
            return True
        except Exception as exc:  # noqa: BLE001 - a refused canary is noted, not fatal
            log.info("list council: %s refused today's canary: %s", a.name, exc)
            return False

    async def _post_list_json(self, group: str, subject: str, body: str) -> None:
        def build(bits):
            art = new_article(group, subject, body, from_name=FROM,
                              extra=[("Content-Type", "application/json")])
            return art.finalize(self.me, bits)
        await self.s._post_with_postage(group, build)

    # --- computing and posting (section 8) -----------------------------------------------------

    async def _compute_and_post(self, lc: ls.ListCouncil, chain: cn.Chain, members: set[str],
                                announcements, today: date, now: datetime) -> None:
        st = self._lists_state()
        day = today - timedelta(days=LIST_LAG)
        if st["computed"] == day.isoformat():
            return
        cur = chain.current
        reports, _ = await self._read_reports(lc)
        posted = await self._read_lists(lc.lists["nodes"], members)
        genesis = _day(chain.counted[0].date)
        if day < genesis:
            return
        before = [x for x in posted if x[0] < day]
        previous = before[-1][3] if before else set()
        imported = await self._imported(chain, lc)
        body, verdicts = ls.node_list(
            day=day, seq=cur.seq, announcements=announcements,
            measurements=ls.Measurements(reports, members), network=network_groups(),
            previous=previous, council=lc, decisions=self._list_decisions(day),
            imported=imported, genesis=genesis)
        newest = posted[-1] if posted else None
        if newest is None or newest[2] != body and newest[0] <= day or (
                newest[2] == body and now - newest[4] > REPOST_AFTER):
            if newest is not None and newest[0] == day and newest[2] != body:
                log.warning("list council: the newest node list for %s differs from this "
                            "replica's; posting its own again (section 8)", day)
            await self._post_list_json(lc.lists["nodes"], f"node list {day.isoformat()}", body)
            log.info("list council: posted the node list for %s (%d node(s))", day,
                     sum(v.listed for v in verdicts.values()))
        st["computed"] = day.isoformat()
        st["listed"] = sum(v.listed for v in verdicts.values())
        st["verdicts"] = {k: v.why for k, v in sorted(verdicts.items())}
        self.s.save()

    async def _imported(self, chain: cn.Chain, lc: ls.ListCouncil) -> dict[str, dict]:
        """The genesis import (section 9): the node list in the council group whose
        Message-ID the genesis manifest names, posted by a member."""
        if not lc.import_id:
            return {}
        members = {crypto.key_to_text(k) for k in chain.current.keys}
        for m in await self.s.fetch_group(chain.current.group_id):
            if m.message_id == lc.import_id and m.author_key in members and m.readable:
                try:
                    data = json.loads(m.body)
                    nodes = data.get("nodes", data)
                    return {n["node_key"]: n for n in nodes.get("nodes", [])
                            if isinstance(n, dict) and n.get("node_key")}
                except (ValueError, AttributeError, TypeError):
                    return {}
        return {}


def _canary_in(raw: bytes | None, group: str, members: set[str], day: date) -> str | None:
    """The node key of a canary of ``day``, signed by a member, in ``group``."""
    from ..core.article import Article, ArticleError
    if not raw:
        return None
    try:
        art = Article.from_bytes(strip_reader_headers(raw))
        art.verify_signature()
    except (ArticleError, ValueError, crypto.CryptoError):
        return None
    if art.group != group or crypto.key_to_text(art.author_key) not in members:
        return None
    return ls.read_canary(art.body, day)

