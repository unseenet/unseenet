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
from .. import names as nm
from ..core import hierarchy_claims as hc
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
LIST_KINDS = {"node list": "nodes", "root list": "root", "entrance list": "entrances",
              "sources list": "sources"}
OUTCOME_DAYS = 120                 # days of computed lists kept for shadow reports


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


def own_groups(lc: ls.ListCouncil) -> list[str]:
    """The council groups a list council keeps with its own members (UN-RFC 0020
    section 4): every list group, the reports and claims groups, and the announcement
    groups (the gateway directory among them). Sorted, each once."""
    return sorted({*lc.lists.values(), lc.reports, lc.claims, *lc.announce.values()} - {""})


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
        group = self.lists_group(cfg)
        if not group:
            return
        out = self.status.setdefault("lists", {"group": group})
        chain = await self.s.council_chain(group)
        cur = chain.current
        if cur is None:
            out["note"] = "the list council does not count yet (its genesis is not signed by all)"
            return
        # a shadow computes the lists as the members do, posts nothing, and shows what it
        # computed in its shadow report to the names council (one membership, #943)
        out["role"] = self.role(cur)
        if chain.disputed:
            out["note"] = "the list council's manifests disagree: nothing is posted"
            return
        try:
            lc = ls.list_council(cur.data)
        except ls.ListProblem as exc:
            out["note"] = f"the list council's manifest is not usable: {exc}"
            return
        if lc is None:
            out["note"] = "the council keeps no lists"
            return
        st = self._lists_state()
        self._list_shadow = not await self._member_of_all(cur, lc)
        out["shadow"] = self._list_shadow
        await self._lists_public(chain, cfg, now, out, lc)
        members = {crypto.key_to_text(k) for k in cur.keys}
        announcements = await self._read_announcements()
        today = _day(now)
        if not self._list_shadow:
            await self._measure(lc, members, announcements, today, now)
        await self._compute_and_post(lc, chain, members, announcements, today, now)
        await self._root_round(lc, chain, members, today, now)
        await self._entrances_round(lc, chain, members, today - timedelta(days=LIST_LAG), now)
        await self._sources_round(lc, chain, members, today - timedelta(days=LIST_LAG), now)
        self._list_activity = await self._activity(chain, lc, members)
        out.update({"members": len(members), "announced": len({a.key for a in announcements}),
                    "measured": st["measured"], "computed": st["computed"],
                    "listed": st.get("listed", 0),
                    "root": (st.get("root") or {}).get("computed"),
                    "granted": (st.get("root") or {}).get("granted"),
                    "entrances": (st.get("entrances") or {}).get("listed"),
                    "entrances_day": (st.get("entrances") or {}).get("computed"),
                    "sources": (st.get("sources") or {}).get("computed")})

    async def _lists_public(self, chain: cn.Chain, cfg: dict, now: datetime, out: dict,
                            lc: ls.ListCouncil | None = None) -> None:
        """The list council's proposals, hearings and log (UN-RFC 0061), by the same code
        as the registrar's, on this council's own part of the state: what it signed,
        held, logged and decided is kept apart from the registrar's. Then its own groups
        - the list groups, reports, claims and announcement groups - are brought in step
        with its members (UN-RFC 0020 section 4), so that a member admitted to the
        council can post in them too."""
        sub = self._lists_state().setdefault("public", {})
        for k, empty in (("signed", []), ("held", {}), ("logged", []), ("hearings_done", []),
                         ("applying", None), ("list_decisions", [])):
            sub.setdefault(k, empty)
        agreed = self.agreed(cfg)                       # from the replica's own state
        st, status = self.st, self.status
        self.st, self.status = sub, out
        try:
            await self._public(chain, now, agreed)
            for g in own_groups(lc) if lc is not None else ():
                await self._keep_in_step(chain, g)
        finally:
            self.st, self.status = st, status
        out["decisions"] = len(sub["list_decisions"])

    # --- one membership for all the project's councils (#943) ------------------------------

    async def _member_of_all(self, cur: cn.CouncilManifest, lc: ls.ListCouncil) -> bool:
        """Whether this replica may post for the list council: a member of it and of every
        group it keeps. A member just admitted waits, computing as a shadow, until those
        groups have been brought in step (a round or two)."""
        if cur.member(self.me.public_key) is None:
            return False
        for g in own_groups(lc):
            chain = await self.s.council_chain(g)
            if chain.current is not None and chain.current.member(self.me.public_key) is None:
                return False
        return True

    def _note_outcome(self, what: str, day: date, body: str) -> None:
        kind = LIST_KINDS.get(what, what)
        out = self._lists_state().setdefault("outcomes", {})
        out.setdefault(day.isoformat(), {})[kind] = ls.import_hash(body)
        for d in sorted(out)[:-OUTCOME_DAYS]:
            del out[d]

    def list_outcomes(self) -> list:
        """The lists this replica computed, as decisions of UN-RFC 0054 section 10 for the
        names council's shadow reports and its judge: ``list:<kind>`` and the list's hash,
        on the list's day."""
        from . import rules
        out = []
        for d, kinds in sorted((self.st.get("lists") or {}).get("outcomes", {}).items()):
            day = datetime.combine(date.fromisoformat(d), time(), timezone.utc)
            for kind, h in sorted(kinds.items()):
                out.append(rules.Decision(f"list:{kind}", day, h, False))
        return out

    async def _activity(self, chain: cn.Chain, lc: ls.ListCouncil, members: set[str]) -> dict:
        """Each member's newest post in the list council's groups - its reports, lists,
        claims, proposals, talk and log - so that silence counts across all the councils
        (UN-RFC 0054 section 12, item 3)."""
        cur = chain.current
        groups = {cur.group_id, *own_groups(lc)} | {
            g for g in (cur.data.get(k) for k in ("proposals", "talk", "log")) if g}
        last: dict[str, datetime] = {}
        for g in sorted(groups):
            try:
                messages = await self.s.fetch_group(g)
            except Exception as exc:  # noqa: BLE001 - one group unread counts nothing
                log.info("list council: %s not read: %s", g, exc)
                continue
            for m in messages:
                if m.author_key in members and m.date and (
                        m.author_key not in last or m.date > last[m.author_key]):
                    last[m.author_key] = m.date
        return last

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

    async def _read_lists(self, group: str, members: set[str], kind: str = "nodes") -> list[tuple]:
        """The lists the members posted: (day, seq, body, the entries' keys, Date)."""
        field_ = {"nodes": "node_key", "entrances": "key"}.get(kind)
        out = []
        for m in await self.s.fetch_group(group):
            if not (m.readable and m.author_key in members and m.date):
                continue
            # read as the council wrote it, not as a client would use it: a client leaves
            # out addresses it cannot use, which must not change who keeps a place
            try:
                data = json.loads(m.body)
                keys = ({str(n[field_]) for n in data.get(kind, []) if field_ in n}
                        if field_ else set())
            except (ValueError, KeyError, TypeError, AttributeError):
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
        e_reached, e_missed, served, e_soft = await self._measure_entrances(lc, now)
        dns = await self._dns_answers(lc, now)
        body = ls.report_body(today, reached | e_reached, missed | e_missed,
                              disconnected=disconnected, incomplete=incomplete,
                              software={**software, **e_soft}, served=served, dns=dns)
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
        if st["computed"] == day.isoformat() or "nodes" not in lc.lists:
            return
        cur = chain.current
        reports, _ = await self._read_reports(lc)
        posted = await self._read_lists(lc.lists["nodes"], members)
        genesis = _day(chain.counted[0].date)
        if day < genesis:
            return
        before = [x for x in posted if x[0] < day]
        previous = before[-1][3] if before else set()
        imp = await self._import_body(chain, lc, "nodes")
        imported = ls.imported_nodes(imp) if imp else {}
        body, verdicts = ls.node_list(
            day=day, seq=cur.seq, announcements=announcements,
            measurements=ls.Measurements(reports, members), network=network_groups(),
            previous=previous, council=lc, decisions=self._list_decisions(day),
            imported=imported, genesis=genesis)
        if await self._maybe_post(lc.lists["nodes"], "node list", day, body, posted, now):
            log.info("list council: posted the node list for %s (%d node(s))", day,
                     sum(v.listed for v in verdicts.values()))
        st["computed"] = day.isoformat()
        st["listed"] = sum(v.listed for v in verdicts.values())
        st["verdicts"] = {k: v.why for k, v in sorted(verdicts.items())}
        self.s.save()

    async def _maybe_post(self, group: str, what: str, day: date, body: str, posted: list,
                          now: datetime) -> bool:
        """Post a computed list when it differs from the newest posted, or that one is a
        month old; post it again when the newest for the same day differs (section 8).
        Every list computed is noted by its hash for the shadow report (#943); a shadow
        posts nothing."""
        self._note_outcome(what, day, body)
        if getattr(self, "_list_shadow", False):
            return False
        newest = posted[-1] if posted else None
        if newest is not None and not (newest[2] != body and newest[0] <= day or (
                newest[2] == body and now - newest[4] > REPOST_AFTER)):
            return False
        if newest is not None and newest[0] == day and newest[2] != body:
            log.warning("list council: the newest %s for %s differs from this replica's; "
                        "posting its own again (section 8)", what, day)
        await self._post_list_json(group, f"{what} {day.isoformat()}", body)
        return True

    async def _import_body(self, chain: cn.Chain, lc: ls.ListCouncil, kind: str) -> str | None:
        """The import a list of ``kind`` starts from (section 9): an article in the council
        group, posted by a member, whose body has the hash the council's manifest names."""
        want = ls.import_for(lc, kind)
        if not want:
            return None
        members = {crypto.key_to_text(k) for k in chain.current.keys}
        for m in await self.s.fetch_group(chain.current.group_id):
            if (m.readable and m.author_key in members and m.body
                    and ls.import_hash(m.body) == want):
                return m.body
        return None

    # --- the sources list (section 6.8) ---------------------------------------------------

    async def _sources_round(self, lc: ls.ListCouncil, chain: cn.Chain, members: set[str],
                             day: date, now: datetime) -> None:
        """Post where the publishers' releases are found: the import with the passed
        ``sources`` decisions applied. Nothing is measured."""
        if "sources" not in lc.lists:
            return
        st = self._lists_state().setdefault("sources", {})
        if st.get("computed") == day.isoformat():
            return
        imp = await self._import_body(chain, lc, "sources")
        body = ls.sources_list(day=day, seq=chain.current.seq,
                               imported=ls.imported_sources(imp) if imp else None,
                               decisions=self._list_decisions(day))
        if body is None:
            self.status.setdefault("lists", {})["sources_note"] = \
                "the sources list has no import yet"
            return
        posted = await self._read_lists(lc.lists["sources"], members, kind="sources")
        if await self._maybe_post(lc.lists["sources"], "sources list", day, body, posted, now):
            log.info("list council: posted the sources list for %s", day)
        st["computed"] = day.isoformat()
        self.s.save()

    # --- the root list (sections 5.2, 6.2) -------------------------------------------------

    async def _dns_answers(self, lc: ls.ListCouncil, now: datetime) -> dict[str, list[str]]:
        """For the day's report (#888): the keys ``_unseenet.nic.<tld>`` names, for every
        top-level domain a revealed claim waits on and every hierarchy granted by DNS.
        The root list goes by what most replicas found, not by one replica's answer."""
        if "root" not in lc.lists:
            return {}
        tlds = self.reg.tlds()
        if tlds is None:
            return {}
        rs = self._lists_state().setdefault("root", {})
        decided = rs.get("dns", {})
        ask = set(rs.get("tld_grants", {}))
        posts = [nm.Post(m.message_id, m.subject or "", m.author_key, m.date, m.body)
                 for m in await self.s.fetch_group(lc.claims)
                 if m.readable and m.author_key and m.date]
        for c in hc.read_claims(posts):
            if (c.claim_body is not None and c.id not in decided
                    and hc.needs_dns(c.claim_body, tlds)):
                ask.add(hc.parse_claim(c.claim_body)["name"])
        out = {}
        for tld in sorted(ask)[:ls.MAX_DNS_NAMES]:
            out[tld] = self._dns_keys(tld)
        return out

    def _dns_keys(self, tld: str) -> list[str]:
        """The keys a TLD's record names now (none when there is no answer)."""
        prefix = nm.dns_record_value("")
        try:
            values = self.reg.dns_txt(nm.tld_record_name(tld))
        except Exception:  # noqa: BLE001 - no answer names nobody
            return []
        keys = set()
        for v in values:
            k = v[len(prefix):].strip() if v.startswith(prefix) else ""
            try:
                crypto.key_from_text(k)
            except Exception:  # noqa: BLE001 - not a key: not counted
                continue
            keys.add(k)
        return sorted(keys)[:ls.MAX_DNS_KEYS]


    async def _root_round(self, lc: ls.ListCouncil, chain: cn.Chain, members: set[str],
                          today: date, now: datetime) -> None:
        """Read the hierarchy claims, check DNS where a name is a top-level domain, and
        post the root list for the day before yesterday when it changed."""
        if "root" not in lc.lists:
            return
        rs = self._lists_state().setdefault("root", {})
        for k, empty in (("computed", None), ("dns", {}), ("dns_ok", {})):
            rs.setdefault(k, empty)
        day = today - timedelta(days=LIST_LAG)
        added = next((m.date for m in chain.counted if "root" in (m.data.get("lists") or {})),
                     chain.counted[0].date)
        if rs["computed"] == day.isoformat() or day < _day(added):
            return
        tlds = self.reg.tlds()
        if tlds is None:
            self.status.setdefault("lists", {})["root_note"] = "the list of top-level domains is not known yet"
            return
        posts = [nm.Post(m.message_id, m.subject or "", m.author_key, m.date, m.body)
                 for m in await self.s.fetch_group(lc.claims)
                 if m.readable and m.author_key and m.date]
        until = hc.end_of(day)
        ready, _ = nm.ready_claims([c for c in hc.read_claims(posts) if c.date < until], until)
        reports = ls.Measurements((await self._read_reports(lc))[0], members)
        for c in ready:                    # what most replicas found, on a settled day (#888)
            if c.id not in rs["dns"] and hc.needs_dns(c.claim_body, tlds):
                name = hc.parse_claim(c.claim_body)["name"]
                key = hc.dns_key(c.claim_body, c.sender)
                d = _day(c.revealed or c.date)
                while d <= day:
                    found = reports.dns_names(d, name, key)
                    if found is not None:
                        rs["dns"][c.id] = found
                        break
                    d += timedelta(days=1)
        await self.refresh_levels({c.sender for c in ready})
        level = {c.sender: self.level_of(c.sender) for c in ready}
        imp = await self._import_body(chain, lc, "root")
        imported = ls.imported_root(imp) if imp else {}
        dec = self._list_decisions(day)
        reserved = {n for n, h in imported.items() if h.policy == "reserved"} | dec.reserved

        def apply(gone):
            return hc.apply_claims(ready, until=until, genesis=added, imported=imported,
                                   reserved=reserved, removed=dec.removed["root"], tlds=set(tlds),
                                   level=level, min_level=chain.current.min_level,
                                   dns=rs["dns"], dns_gone=gone)
        state = apply(set())
        for name, g in state.grants.items():          # TLD grants: their record, every day
            if g.expires is None:
                entry = rs["dns_ok"].get(name)
                if not isinstance(entry, list) or entry[0] != g.maintainer:
                    entry = [g.maintainer, _day(g.granted or added).isoformat()]
                d = date.fromisoformat(entry[1]) + timedelta(days=1)
                while d <= day:
                    if reports.dns_names(d, name, g.maintainer):
                        entry[1] = d.isoformat()
                    d += timedelta(days=1)
                rs["dns_ok"][name] = entry
        gone = {n for n, e in rs["dns_ok"].items() if isinstance(e, list)
                and day - date.fromisoformat(e[1]) > hc.DNS_GONE}
        state = apply(gone)
        rs["tld_grants"] = {n: g.maintainer for n, g in state.grants.items() if g.expires is None}
        body = hc.root_list(day, chain.current.seq, state, imported, reserved)
        posted = await self._read_lists(lc.lists["root"], members)
        if await self._maybe_post(lc.lists["root"], "root list", day, body, posted, now):
            log.info("list council: posted the root list for %s (%d granted)", day,
                     len(state.grants))
        rs["computed"] = day.isoformat()
        rs["granted"] = len(state.grants)
        rs["why"] = dict(list(state.why.items())[-50:])
        self.s.save()


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

