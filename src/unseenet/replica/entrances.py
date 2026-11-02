"""A replica's duties for a list council's entrance list (UN-RFC 0020 sections 5.1, 6.3).

Once a day, with the nodes (``replica/lists.py``), the replica

- reads the entrances' announcements in the council's announcement group, and each
  named publisher's release posts in its releases channel - from the network, signed by
  the channel's owner or a poster it lists, not from the entrance;
- **fetches** each entrance over Tor: its ``/.well-known/unseenet-entrance`` must name
  the key it announced with; then ``version.json`` and every file the publisher's post
  for that version names, each checked against its SHA-256;
- puts what it found in the same daily report as the nodes (``reached``, ``missed``,
  ``served``, ``software``);
- computes the entrance list for the day before yesterday and posts it when it changed.

Belongs here: reading, fetching and posting for the entrance list. Not here: the rules
(``core/entrances.py``).

Part of ``Replica`` (see run.py), beside ``ListDuties``."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, timedelta

from ..core import council as cn
from ..core import crypto
from ..core import entrances as en
from ..core import lists as ls
from ..core.groups import split_group_id

log = logging.getLogger("unseenet.replica")

ENTRANCE_TIMEOUT = 900.0           # one entrance, every file, over Tor
MAX_INFO = 1 << 16
MAX_FILE = 48 << 20


class EntranceDuties:
    """Mixed into ``Replica`` with ``ListDuties``: ``self.s`` (the Session), ``self.st``,
    ``self.status``, ``_lists_state``, ``_read_lists``, ``_maybe_post``, ``_import_body``,
    ``_list_decisions``."""

    # --- reading -----------------------------------------------------------------------------

    async def _read_entrances(self, lc: ls.ListCouncil) -> list[en.Entrance]:
        group = lc.announce.get("entrances")
        if not group:
            return []
        found = []
        for m in await self.s.fetch_group(group):
            if not (m.readable and m.author_key and m.date):
                continue
            try:
                found.append(en.parse(m.body, key=m.author_key, date=m.date,
                                      message_id=m.message_id))
            except en.EntranceProblem:
                continue
        return found

    async def _read_releases(self, group: str) -> dict[str, en.Release]:
        """A publisher's releases of the web client, from its releases channel: only
        posts by the owner its Group ID names, or by a poster that owner lists."""
        try:
            manifest = await self.s.fetch_manifest(group)
            messages = await self.s.fetch_group(group)
        except Exception as exc:  # noqa: BLE001 - an unreadable channel has no releases
            log.info("list council: releases of %s not read: %s", group, exc)
            return {}
        if manifest is None or crypto.fingerprint(manifest.owner) != split_group_id(group)[1]:
            return {}
        posts = []
        for m in messages:
            if not (m.readable and m.author_key and m.date):
                continue
            try:
                if manifest.can_post_directly(crypto.key_from_text(m.author_key)):
                    posts.append((m.body, m.date))
            except crypto.CryptoError:
                continue
        return en.releases(posts)

    # --- measuring (section 6.3) -------------------------------------------------------------

    async def _measure_entrances(self, lc: ls.ListCouncil, now: datetime):
        """(reached, missed, served, software) for today's report."""
        reached, missed, served, software = set(), set(), {}, {}
        if "entrances" not in lc.lists:
            return reached, missed, served, software
        current = en.newest(await self._read_entrances(lc), now)
        rels: dict[str, dict] = {}
        for key, e in sorted(current.items()):
            if e.publisher not in rels:
                rels[e.publisher] = await self._read_releases(e.publisher)
            try:
                got = await asyncio.wait_for(self._check_entrance(e, rels[e.publisher]),
                                             ENTRANCE_TIMEOUT)
            except Exception as exc:  # noqa: BLE001 - any failure is "not reached" today
                log.info("list council: entrance %s not reached: %s", e.base(), exc)
                got = None
            if got is None:
                missed.add(key)
                continue
            reached.add(key)
            version, soft = got
            if version:
                served[key] = version
            if soft:
                software[key] = soft
        log.info("list council: measured %d entrance(s), %d reached, %d serving a signed release",
                 len(current), len(reached), len(served))
        return reached, missed, served, software

    async def _check_entrance(self, e: en.Entrance, rels: dict[str, en.Release]):
        """None when it does not answer with its key; else (the signed version it serves
        unchanged or None, the software it states)."""
        base = e.base()
        info = json.loads(await self._fetch_entrance(base + ".well-known/unseenet-entrance",
                                                     MAX_INFO))
        if not en.info_names(info, e.key):
            return None
        soft = str(info.get("software") or "")[:ls.MAX_SOFTWARE] or None
        try:
            version = str(json.loads(await self._fetch_entrance(base + "version.json",
                                                                MAX_INFO)).get("version", ""))
        except Exception:  # noqa: BLE001 - reached, but serving no signed version
            return None, soft
        rel = rels.get(version)
        if rel is None:
            return None, soft
        for path, digest in sorted(rel.files.items()):
            try:
                data = await self._fetch_entrance(base + path, MAX_FILE)
            except Exception:  # noqa: BLE001 - a file it does not serve
                return None, soft
            if hashlib.sha256(data).hexdigest() != digest:
                log.warning("list council: entrance %s serves %s changed from release %s",
                            base, path, version)
                return None, soft
        return version, soft

    async def _fetch_entrance(self, url: str, limit: int) -> bytes:
        """GET over Tor; raises unless the answer is a 200 within ``limit`` octets."""
        from ..client import webfetch
        socks = await self.s._ensure_tor(lambda *a, **k: None)
        got = await webfetch.fetch(url, socks, limit=limit, accept="*/*")
        if got.cut:
            raise ValueError(f"{url}: more than {limit} octets")
        return got.octets

    # --- computing and posting (section 8) -----------------------------------------------------

    async def _entrances_round(self, lc: ls.ListCouncil, chain: cn.Chain, members: set[str],
                               day: date, now: datetime) -> None:
        if "entrances" not in lc.lists:
            return
        es = self._lists_state().setdefault("entrances", {})
        added = next((m.date for m in chain.counted
                      if "entrances" in (m.data.get("lists") or {})), chain.counted[0].date)
        genesis = added.date()
        if es.get("computed") == day.isoformat() or day < genesis:
            return
        reports, _ = await self._read_reports(lc)
        posted = await self._read_lists(lc.lists["entrances"], members, kind="entrances")
        before = [x for x in posted if x[0] < day]
        anns = await self._read_entrances(lc)
        publishers = sorted({a.publisher for a in anns})
        rels = {p: await self._read_releases(p) for p in publishers}
        imp = await self._import_body(chain, lc, "entrances")
        inputs = en.Inputs(anns, rels, before[-1][3] if before else set(),
                           en.imported_entrances(imp) if imp else [], genesis)
        body, verdicts = en.entrance_list(
            day=day, seq=chain.current.seq, inputs=inputs,
            measurements=ls.Measurements(reports, members), council=lc,
            decisions=self._list_decisions(day))
        if await self._maybe_post(lc.lists["entrances"], "entrance list", day, body, posted, now):
            log.info("list council: posted the entrance list for %s (%d entrance(s))", day,
                     sum(v.listed for v in verdicts.values()))
        es["computed"] = day.isoformat()
        es["listed"] = sum(v.listed for v in verdicts.values())
        es["verdicts"] = {k: v.why for k, v in sorted(verdicts.items())}
        self.s.save()
