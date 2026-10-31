"""One replica of a council registrar, or a shadow on its way in (UN-RFC 0054 Part II).

Belongs here: one round - read the council and its groups, decide the claims that are
ready (``registrar.Registrar``), and then what the replica's role asks of it: as a
**shadow**, the daily report (section 10); as a **member**, certificates and answers,
the heartbeat (section 9); as a **full member**, the next council manifest (sections
11, 12, 19, 20) - posted in the registrar's group and in the claims group alike, unless
the operator holds it (section 13). Ripening the key runs beside the rounds. After each
round the replica writes ``status.json`` (no secrets) for ``unseenet-replica status``.

Not here: the rules every replica computes the same way (``rules.py``), setting up
and the command line (``cli.py``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .. import __version__
from .. import names as nm
from ..client.session import Session, SessionError
from ..core import council as cn
from ..core import crypto
from ..core import ripening as rp
from ..core.article import new_article
from ..core.groups import make_group_id
from ..registrar import Registrar, dig_txt
from . import rules

log = logging.getLogger("unseenet.replica")

SOFTWARE = f"unseenet-replica {__version__}"
ALIVE_EVERY = (timedelta(days=7), timedelta(days=29))   # a random time within, section 9
HOLDABLE = ("admission", "promotion", "removal")         # section 13; a renunciation follows


class Replica:
    """A replica of the council registrar ``group``. ``hold``: the kinds of change the
    operator agrees to first (section 13); ``state_dir``: where ``status.json`` goes."""

    def __init__(self, session: Session, group: str = nm.NAMES_GROUP, *,
                 hold: set[str] = frozenset(), state_dir: Path | None = None,
                 tlds=None, dns_txt: Callable[[str], list[str]] = dig_txt,
                 now: Callable[[], datetime] | None = None, rng: random.Random | None = None,
                 levels: Callable[[str], int | None] | None = None, ripen: bool = True,
                 config: Callable[[], dict] | None = None):
        self.s = session
        self.group = group
        self.hold = set(hold)
        self.state_dir = state_dir
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.rng = rng or random.SystemRandom()
        self.reg = Registrar(session, group, tlds=tlds, dns_txt=dns_txt, now=self.now,
                             shadow=True)
        self.me = session.identity()
        st = session.data.setdefault("replica", {})
        for key, empty in (("started", None), ("reported", []), ("report_at", {}),
                           ("alive_next", None), ("signed", []), ("held", {}),
                           ("agreed", []), ("objections_seen", [])):
            st.setdefault(key, empty)
        self.st = st
        self._levels = levels
        self._level_cache: dict[str, tuple[int, int | None]] = {}
        self.ripen = ripen
        self.config = config
        self.status: dict = {}

    # --- what the replica is -----------------------------------------------------------

    def role(self, cur: cn.CouncilManifest | None) -> str:
        if cur is None:
            return "waiting"
        m = cur.member(self.me.public_key)
        if m is None:
            return "shadow"
        return "full member" if m.full else "member on probation"

    # --- a round -------------------------------------------------------------------------

    def _read_config(self) -> dict:
        """The operator's choices, read again every round (``cli.py`` writes them)."""
        cfg = self.config() if self.config else {}
        if "hold" in cfg:
            self.hold = {k for k in cfg["hold"] if k in HOLDABLE}
        return cfg

    def agreed(self, cfg: dict) -> set[str]:
        return set(self.st["agreed"]) | set(cfg.get("agreed", []))

    async def run_once(self) -> dict:
        now = self.now()
        today = rules.day_of(now)
        cfg = self._read_config()
        if not self.st["started"]:
            self.st["started"] = nm.rfc3339(now)
        chain = await self.s.council_chain(self.group)
        cur = chain.current
        role = self.role(cur)
        self.status = {"time": nm.rfc3339(now), "software": SOFTWARE, "group": self.group,
                       "key": self.me.key_text, "role": role,
                       "level": self._own_level(), "disputed": chain.disputed}
        if cur is None:
            self.status["note"] = "the council does not count yet (its genesis is not signed by all)"
            self._write_status()
            return self.status
        self.reg.shadow = role == "shadow"
        await self.reg.run_once()
        posts = await self.reg.read_public()
        council_posts = [nm.Post(m.message_id, m.subject or "", m.author_key, m.date, m.body)
                         for m in getattr(self.reg, "messages", []) if m.author_key and m.date]
        decisions = [rules.Decision(x[0], datetime.strptime(x[1], "%Y-%m-%d").replace(
            tzinfo=timezone.utc), x[2], bool(x[3])) for x in self.reg.st["decisions"]]
        members = {crypto.key_to_text(k) for k in cur.keys}
        candidates = set(rules.reports_by_key(posts)) | {
            p.subject[len(rules.ADMIT) + 1:].strip() for p in council_posts
            if p.subject.startswith(rules.ADMIT + " ")}
        await self.refresh_levels(candidates - members)

        if role == "shadow":
            await self._report(decisions, today, now)
        else:
            await self._heartbeat(now)
            if cfg.get("resign") and not self.st.get("resigned"):
                await self.resign()
        world = self._world(chain, posts, council_posts, decisions)
        self._note_objections(posts, cur)
        change = rules.next_change(world, today) if not chain.disputed else None
        self.status.update(self._describe(world, cur, decisions, today))
        if change is not None:
            self.status["next_change"] = {"kind": change.kind, "key": change.key,
                                          "date": nm.rfc3339(change.date), "why": change.why}
            if role == "full member":
                await self._sign(change, chain, self.agreed(cfg))
        else:
            self.st["held"] = {}                 # nothing is due: nothing waits
        await self._keep_in_step(chain, self.reg.claims_group)
        await self._keep_in_step(chain, cur.room)
        await self._room_keys(chain, now)
        self.status["held"] = dict(self.st["held"])
        self.s.save()
        self._write_status()
        return self.status

    # --- shadow reports (section 10) -------------------------------------------------------

    async def _report(self, decisions: list[rules.Decision], today: datetime, now: datetime) -> None:
        """Post the report for the day settled today (day - 8), at a random time of the
        day, once. A day missed is not made up: it would not count."""
        day = today - rules.REPORT_LAG * rules.DAY
        started = rules.day_of(nm.parse_rfc3339(self.st["started"]))
        if day < started or rules.day_text(day) in self.st["reported"]:
            return
        at = self.st["report_at"].setdefault(rules.day_text(day), self.rng.randrange(0, 20 * 3600))
        if now < today + timedelta(seconds=at):
            return
        body = rules.report_body(day, decisions)
        await self.reg._post_json(rules.report_subject(day), body, group=self.reg.claims_group)
        self.st["reported"] = (self.st["reported"] + [rules.day_text(day)])[-120:]
        self.st["report_at"] = {k: v for k, v in self.st["report_at"].items()
                                if k >= rules.day_text(day - 30 * rules.DAY)}
        log.info("posted the shadow report for %s", rules.day_text(day))

    # --- heartbeats (section 9) --------------------------------------------------------------

    async def _heartbeat(self, now: datetime) -> None:
        nxt = self.st["alive_next"]
        if nxt and now < nm.parse_rfc3339(nxt):
            return
        body = json.dumps({"software": SOFTWARE}, sort_keys=True, separators=(",", ":")) + "\n"
        await self.reg._post_json(f"{rules.ALIVE} {rules.day_text(now)}", body)
        lo, hi = ALIVE_EVERY
        wait = lo + timedelta(seconds=self.rng.randrange(0, int((hi - lo).total_seconds())))
        self.st["alive_next"] = nm.rfc3339(now + wait)
        log.info("posted a heartbeat")

    # --- the next council manifest ------------------------------------------------------------

    def _world(self, chain: cn.Chain, posts: list[nm.Post], council_posts: list[nm.Post],
               decisions: list[rules.Decision]) -> rules.World:
        cur = chain.current
        members = {crypto.key_to_text(k) for k in cur.keys}
        full = {crypto.key_to_text(k) for k in cur.full}
        known_from = rules.day_of(nm.parse_rfc3339(self.st["started"]))
        reports = rules.reports_by_key(posts)
        certs, last_post, resigned, admits, renounced = [], {}, {}, [], None
        founder = crypto.key_to_text(cur.founding.founder) if cur.founding else None
        for p in sorted(council_posts, key=lambda p: (p.date, p.message_id)):
            last_post[p.author] = p.date
            if p.subject.startswith("name "):
                try:
                    certs.append(rules.Cert(nm.parse_certificate(p.body), p.date))
                except nm.NameProblem:
                    pass
            elif p.subject.strip() == rules.RESIGN and p.author in members:
                resigned.setdefault(p.author, p.date)
            elif p.subject.startswith(rules.ADMIT + " ") and p.author == founder:
                admits.append((p.date, p.subject[len(rules.ADMIT) + 1:].strip()))
            elif p.subject.strip() == rules.RENOUNCE and p.author == founder and renounced is None:
                renounced = p.date
        by_commit = {}
        for x in self.reg.st["decisions"]:
            o = x[4] if len(x) > 4 else ""
            by_commit[x[0]] = (o if o.startswith('{"issue"') else "", bool(x[3]))
        keys = set(reports) | {k for _, k in admits}
        return rules.World(
            chain=chain, judge=rules.Judge(decisions, reports, known_from), certs=certs,
            decisions=by_commit, last_post=last_post, resigned=resigned,
            level={k: self.level_of(k) for k in keys - members},
            sponsors=rules.sponsorships(posts, members, full), admits=admits,
            renounced=renounced, now=self.now())

    async def resign(self) -> None:
        """Step down (section 20): a signed ``resign`` in the registrar's group; the
        other members' replicas remove this key."""
        await self.reg._post_json(rules.RESIGN, "{}\n")
        self.st["resigned"] = nm.rfc3339(self.now())
        log.warning("posted resign: the other members' replicas will remove this key")

    async def _sign(self, change: rules.Change, chain: cn.Chain, agreed: set[str] = frozenset()) -> None:
        """Post this member's copy of ``change``, unless held or already posted. A
        renunciation is never held: it is the founder's to make (section 19)."""
        if change.body in self.st["signed"]:
            return
        if change.kind in self.hold and change.label not in agreed:
            if change.label not in self.st["held"]:
                log.warning("holding a %s of %s (%s); agree with: unseenet-replica agree %s",
                            change.kind, change.key, change.why, change.label)
            self.st["held"] = {change.label: {"kind": change.kind, "key": change.key,
                                              "date": nm.rfc3339(change.date), "why": change.why}}
            return
        await self._post_manifest(self.group, change.body)
        self.st["signed"] = (self.st["signed"] + [change.body])[-50:]
        self.st["held"].pop(change.label, None)
        log.info("signed the council's %s of %s: %s", change.kind, change.key or "-", change.why)

    async def _keep_in_step(self, chain: cn.Chain, group_id: str | None) -> None:
        """Sections 8 and 21: the claims group's council, and the room's, are kept the
        same as the registrar's. A full member posts there the change that brings it in
        step."""
        cur = chain.current
        if not group_id or cur is None or self.role(cur) != "full member":
            return
        other = await self.s.council_chain(group_id)
        oc = other.current
        if oc is None or other.disputed:
            return
        # a group founded without a founding period keeps none (section 19)
        founding = cur.founding if oc.founding is not None else None
        if [m.as_json() for m in oc.members] == [m.as_json() for m in cur.members] \
                and oc.founding == founding:
            return
        body = cn.next_body(oc, date=max(cur.date, oc.date), members=cur.members,
                            founding=founding)
        if body in self.st["signed"]:
            return
        m = cn.CouncilManifest.from_body(group_id, body)
        if cn.change_ok(oc, m, other.last_admission or other.counted[0].date) is not None:
            log.warning("%s cannot be brought in step with the council in one change", group_id)
            return
        await self._post_manifest(group_id, body)
        self.st["signed"] = (self.st["signed"] + [body])[-50:]

    # --- the room's keys (section 21) -------------------------------------------------------

    async def _room_keys(self, chain: cn.Chain, now: datetime) -> None:
        """Hand on the room's key by itself: a first epoch for all members; a grant to a
        member that has no envelope of the current epoch; a new epoch, closing the one
        before, when someone who is no longer a member holds the current key. The full
        member whose key sorts first acts; the next one if nothing has come within 24
        hours, and so on. Envelope tags say whose key each was sealed to, so every
        replica sees the same need from public articles."""
        from ..core.groups import envelope_tag
        room = chain.current.room if chain.current else None
        if not room or self.role(chain.current) != "full member":
            return
        rc = await self.s.council_chain(room)
        cur = rc.current
        if cur is None or rc.disputed:
            return
        self.s.group_entry(room)["type"] = "closed"     # posts there are encrypted
        await self.s.fetch_group(room)                  # opens our envelopes: the keys
        keys = await self.s.council_room_keys(room)
        updates = {k["epoch"]: k for k in keys if k["kind"] == "key-update"}
        epoch = max(updates) if updates else None
        members = cur.keys
        ever = {k for m in chain.counted for k in m.keys} | {k for m in rc.counted for k in m.keys}
        if epoch is None:
            need, label, todo = "update", "room:1", (1, members, False)
        else:
            tags = set().union(*(k["tags"] for k in keys if k["epoch"] == epoch))
            gone = [k for k in ever - set(members) if envelope_tag(room, epoch, k) in tags]
            missing = [k for k in members if envelope_tag(room, epoch, k) not in tags]
            if gone:
                need, label, todo = "update", f"room:{epoch + 1}", (epoch + 1, members, True)
            elif missing:
                need = "grant"
                label = f"room:{epoch}:" + ",".join(sorted(crypto.key_to_text(k) for k in missing))
                todo = (epoch, missing, False)
            else:
                self.st.pop("room_need", None)
                return
        since = self.st.setdefault("room_need", {}).setdefault(label, nm.rfc3339(now))
        self.st["room_need"] = {label: since}
        order = sorted(crypto.key_to_text(k) for k in cur.full)
        mine = order.index(self.me.key_text) if self.me.key_text in order else None
        if mine is None or now < nm.parse_rfc3339(since) + timedelta(hours=24) * mine:
            return
        ep, to, closes = todo
        secret = None
        if need == "grant":
            hexed = self.s.group_entry(room).get("keys", {}).get(str(ep))
            if not hexed:
                return                                  # we do not hold it: the next one acts
            secret = bytes.fromhex(hexed)
        try:
            await self.s.council_room_issue(room, ep, to, secret=secret, closes_previous=closes)
            log.info("room %s: %s of epoch %d for %d member(s)", room, need, ep, len(to))
        except SessionError as exc:                     # another member was first
            log.info("room %s: %s not taken (%s)", room, need, exc)

    async def _post_manifest(self, group_id: str, body: str) -> None:
        art = new_article(group_id, None, body.rstrip("\n").rstrip("\r"),
                          extra=[("Control", "manifest"), ("Content-Type", "application/json")])
        await self.s.post_article(art, None, sign_with=self.me)

    # --- what others ask of the operator (section 13.1) ------------------------------------------

    def _note_objections(self, posts: list[nm.Post], cur: cn.CouncilManifest) -> None:
        full = {crypto.key_to_text(k) for k in cur.full}
        found = []
        for who, key, when, why in rules.objections(posts):
            tag = f"{who}:{key}:{nm.rfc3339(when)}"
            item = {"by": who, "about": key, "date": nm.rfc3339(when), "why": why,
                    "by_full_member": who in full}
            found.append(item)
            if who in full and tag not in self.st["objections_seen"]:
                self.st["objections_seen"] = (self.st["objections_seen"] + [tag])[-500:]
                log.warning("objection by a full member to %s: %s", key, why[:200])
        self.status["objections"] = found[-20:]

    # --- ripening ---------------------------------------------------------------------------------

    def _own_level(self) -> int | None:
        try:
            return self.s.ripening().level
        except Exception:  # noqa: BLE001 - shown as unknown
            return None

    def level_of(self, key: str) -> int | None:
        """The ripening level ``key`` has proved in its ripe@ group (UN-RFC 0025),
        read by ``refresh_levels``; None if unknown or unripe."""
        if self._levels is not None:
            return self._levels(key)
        got = self._level_cache.get(key)
        return got[1] if got else None

    async def refresh_levels(self, keys: set[str]) -> None:
        """Read and check the ripening chains of ``keys``, those not checked lately."""
        if self._levels is not None or not rp.available():
            return
        for key in keys:
            try:
                pk = crypto.key_from_text(key)
                m = await self.s.fetch_manifest(make_group_id(rp.GROUP_NAME, pk))
                if m is None or "ripening" not in m.raw:
                    continue
                chain = rp.Chain.from_manifest(m.raw["ripening"])
                old = self._level_cache.get(key)
                if old and old[0] == chain.t:
                    continue
                rp.verify(pk, chain)
                self._level_cache[key] = (chain.t, rp.level(chain.t))
            except (rp.RipeningError, crypto.CryptoError, SessionError, OSError, ValueError):
                continue

    async def ripen_until(self, level: int, stop: asyncio.Event | None = None) -> None:
        """Ripen this replica's key to ``level`` beside the rounds, publishing each level
        reached (UN-RFC 0025 section 7)."""
        if not rp.available():
            log.warning("key ripening is not available on this machine")
            return
        while (self._own_level() or -1) < level and not (stop and stop.is_set()):
            if not await self.s.ripen_segment():
                break
            lv = self._own_level()
            if lv is not None and lv != self.s.published_level():
                try:
                    await self.s.publish_ripening()
                    log.info("key ripened to level %d", lv)
                except (SessionError, OSError, ConnectionError) as exc:
                    log.warning("could not publish ripening yet: %s", exc)

    # --- status -------------------------------------------------------------------------------------

    def _describe(self, w: rules.World, cur: cn.CouncilManifest, decisions, today) -> dict:
        me = self.me.key_text
        out = {"members": len(cur.members), "full": len(cur.full),
               "min_level": cur.min_level, "held": dict(self.st["held"]),
               "decisions": len(decisions)}
        if cur.founding is not None:
            f = cur.founding
            out["founding"] = {"until": nm.rfc3339(f.until), "size": f.size,
                               "renounced": f.renounced, "lasts": cur.founding_lasts(today)}
        reports = w.judge.reports.get(me, {})
        days = rules.window(today)
        out["reports_60"] = sum(1 for d in days if d in reports)
        out["agreeing_60"] = sum(1 for d in days
                                 if rules.day_agrees(reports.get(d), w.judge.by_day.get(d, [])))
        m = cur.member(self.me.public_key)
        if m is not None:
            out["joined"] = nm.rfc3339(m.joined)
            if not m.full:
                end = m.joined + (cn.FOUNDER_PROBATION if m.by == cn.FOUNDER else cn.PROBATION)
                out["full_from"] = nm.rfc3339(end)
        out["alive_next"] = self.st["alive_next"]
        return out

    def _write_status(self) -> None:
        if self.state_dir is None:
            return
        path = Path(self.state_dir) / "status.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.status, indent=1, sort_keys=True) + "\n")
        tmp.replace(path)


async def run(session: Session, *, group: str = nm.NAMES_GROUP, interval: float = 300,
              once: bool = False, ripen_to: int | None = None, **kw) -> None:
    """Rounds every ``interval`` seconds; the key ripens beside them."""
    rep = Replica(session, group, **kw)
    stop = asyncio.Event()
    ripening = None
    try:
        while True:
            try:
                status = await rep.run_once()
                want = ripen_to if ripen_to is not None else status.get("min_level")
                if want is not None and ripening is None and (rep._own_level() or -1) < want:
                    ripening = asyncio.create_task(rep.ripen_until(want, stop))
            except (SessionError, OSError, ConnectionError, asyncio.IncompleteReadError) as exc:
                log.warning("round failed: %s", exc)
                rep.status.update({"error": str(exc), "time": nm.rfc3339(rep.now())})
                rep._write_status()
            if once:
                return
            await asyncio.sleep(interval)
    finally:
        stop.set()
        if ripening is not None:
            ripening.cancel()
        await session.close()
