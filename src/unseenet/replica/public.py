"""A replica's public duties around its council (UN-RFC 0061): the council's open
groups, hearings and the log.

Belongs here: keeping the council's ``proposals``, ``talk`` and ``log`` groups in step;
hearings - opening them, counting objections from ripened keys, closing them and
applying what passed (section 7); the log, which the replicas keep by themselves
(section 8); and the **outbox**, through which the operator posts with the member key
that the running replica holds (``unseenet-replica propose|second|talk|object``).

Not here: the rules (``core/proposals.py``), the replica's round (``run.py``).

Part of ``Replica`` (see run.py)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .. import names as nm
from ..core import council as cn
from ..core import crypto
from ..core import proposals as pr

log = logging.getLogger("unseenet.replica")

GROUPS = ("proposals", "talk", "log")
INACTIVE_WARN = timedelta(days=14)          # section 8: members who stop being active


def items_of(messages) -> list[pr.Item]:
    return [pr.Item(m.message_id, m.subject or "", m.author_key, m.date, m.body)
            for m in messages if m.readable and m.author_key and m.date]


class PublicDuties:
    """Mixed into ``Replica``: needs ``self.s``, ``self.st``, ``self.me``, ``self.hold``,
    ``self.status``, ``self.state_dir``, ``self.level_of``, ``self.refresh_levels``,
    ``self._keep_in_step``, ``self._post_manifest`` and ``self.role``."""

    # --- the outbox ---------------------------------------------------------------------

    async def _outbox(self) -> None:
        """Post what the operator queued with the member key (oldest first). A post
        that fails stays for the next round."""
        if self.state_dir is None:
            return
        box = Path(self.state_dir) / "outbox"
        if not box.is_dir():
            return
        for path in sorted(box.glob("*.json")):
            try:
                item = json.loads(path.read_text())
                await self.s.post(item["group"], item["subject"], item["body"],
                                  content_type=item.get("content_type"),
                                  references=item.get("references") or None)
            except (OSError, ValueError, KeyError) as exc:
                log.warning("outbox %s not posted: %s", path.name, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - a node said no: keep it, say why
                log.warning("outbox %s not posted yet: %s", path.name, exc)
                continue
            path.unlink(missing_ok=True)
            log.info("posted %s from the outbox", item["subject"])

    # --- the council's open groups (sections 3-8) -------------------------------------------

    async def _public(self, chain: cn.Chain, now: datetime, agreed: set[str]) -> None:
        cur = chain.current
        groups = {k: cur.data.get(k) for k in GROUPS}
        for g in groups.values():
            await self._keep_in_step(chain, g)
        self.status["seq"] = cur.seq
        self.status["groups"] = {k: v for k, v in groups.items() if v}
        if not groups["proposals"]:
            return
        proposals = items_of(await self.s.fetch_group(groups["proposals"]))
        talk = items_of(await self.s.fetch_group(groups["talk"])) if groups["talk"] else []
        await self._hearings(chain, proposals, talk, groups.get("log"), now, agreed)
        if groups.get("log") and self.role(cur) == "full member":
            await self._log_changes(chain, proposals + talk, groups["log"], now)

    async def _hearings(self, chain: cn.Chain, proposals: list[pr.Item], talk: list[pr.Item],
                        logbook: str | None, now: datetime, agreed: set[str]) -> None:
        cur = chain.current
        full = self.role(cur) == "full member"
        hs = pr.hearings(chain, proposals, talk)
        objections = [i for i in proposals if i.subject.startswith(pr.OBJECTION + " ")]
        await self.refresh_levels({i.author for i in objections})
        level = {i.author: self.level_of(i.author) for i in objections}
        shown, done = [], set(self.st.setdefault("hearings_done", []))
        counted = {h.proposal.id for h in hs}
        for h in hs:
            p = h.proposal
            out = pr.outcome(h, objections, level, cur.min_level, now)
            shown.append({"id": p.id, "kind": p.kind, "reason": p.reason[:300],
                          "state": out.state, "objections": out.objections,
                          "active": out.active, "closes": nm.rfc3339(out.closes),
                          "urgent": p.urgent})
            if not full or not logbook:
                continue
            await self._log(logbook, f"hearing {p.id} open",
                            f"A proposal of the council stands in public until "
                            f"{out.closes:%Y-%m-%d %H:%M} UTC ({h.days} days). Anybody with a "
                            f"ripened key may object in the proposals group.\n\n"
                            f"Change: {json.dumps(p.change, sort_keys=True)}\n\nReason: {p.reason}\n")
            if out.state == "extended":
                await self._log(logbook, f"hearing {p.id} extended",
                                f"{out.objections} objections against {out.active} active "
                                f"members: the hearing is extended to {out.closes:%Y-%m-%d} "
                                f"(UN-RFC 0061 section 7).\n")
            if out.state not in ("passed", "failed") or p.id in done:
                continue
            note = ""
            if out.state == "passed" and p.kind not in pr.APPLIED_KINDS:
                note = (f" This software cannot apply a {p.kind} change yet; it is recorded "
                        "here and applied when it can.")
            await self._log(logbook, f"hearing {p.id} closed",
                            f"{out.objections} objections from ripened keys against "
                            f"{out.active} active members: the proposal {out.state}.{note}\n")
            if out.state == "failed" or p.kind not in pr.APPLIED_KINDS:
                self.st["hearings_done"] = (self.st["hearings_done"] + [p.id])[-500:]
                continue
            if out.applies > now:
                continue
            label = f"proposal:{p.id}"
            if "proposal" in self.hold and label not in agreed:
                self.st["held"] = {label: {"kind": "proposal", "key": None,
                                           "date": nm.rfc3339(out.applies),
                                           "why": f"passed its hearing: {p.reason[:200]}"}}
                continue
            try:
                body = pr.applied_body(cur, p, out.applies)
                m = cn.CouncilManifest.from_body(cur.group_id, body)
                why = cn.change_ok(cur, m, chain.last_admission or chain.counted[0].date)
            except (pr.ProposalProblem, ValueError) as exc:
                why = str(exc)
            if why:
                log.warning("proposal %s passed but cannot be applied: %s", p.id, why)
                await self._log(logbook, f"proposal {p.id} not applied",
                                f"It passed, but the manifest it makes would not count: {why}.\n")
            elif body not in self.st["signed"]:
                await self._post_manifest(cur.group_id, body)
                self.st["signed"] = (self.st["signed"] + [body])[-50:]
                log.info("applied proposal %s", p.id)
            self.st["hearings_done"] = (self.st["hearings_done"] + [p.id])[-500:]
        self.status["hearings"] = shown
        # proposals posted but not counting yet: what a member may second
        pending = {}
        for i in proposals:
            if i.subject.startswith(pr.PROPOSAL + " "):
                pid = i.subject[len(pr.PROPOSAL) + 1:].strip()
                if pid not in counted and now - i.date <= pr.COUNT_WITHIN:
                    pending.setdefault(pid, {"body": i.body, "by": [], "first": nm.rfc3339(i.date)})
                    pending[pid]["by"].append(i.author)
        self.status["proposals_pending"] = pending

    # --- the log (section 8) ------------------------------------------------------------------

    async def _log(self, logbook: str, subject: str, text: str) -> None:
        """Post one log entry, once from this replica."""
        logged = self.st.setdefault("logged", [])
        if subject in logged:
            return
        try:
            await self.s.post(logbook, subject, text)
        except Exception as exc:  # noqa: BLE001 - tried again next round
            log.warning("log entry %r not posted: %s", subject, exc)
            return
        self.st["logged"] = (logged + [subject])[-2000:]

    async def _log_changes(self, chain: cn.Chain, spoken: list[pr.Item], logbook: str,
                           now: datetime) -> None:
        """The council's changes, its founding period, forks, and members who will stop
        being active within 14 days."""
        if chain.disputed:
            await self._log(logbook, f"fork at {chain.fork_seq}",
                            f"Two different council manifests number {chain.fork_seq} both count: "
                            "keys are stolen or misused. Nothing from that number on is applied "
                            "(UN-RFC 0054 section 5).\n")
        for before, after in zip(chain.counted, chain.counted[1:]):
            if after.date >= now - timedelta(days=30):      # a new replica: not all history
                await self._log(logbook, f"council {after.seq}", _describe_change(before, after))
        cur = chain.current
        f = cur.founding
        if f is not None and not f.renounced and cur.founding_lasts(now):
            missing = max(0, f.size - len(cur.full))
            await self._log(logbook, f"founding {cur.seq}",
                            f"The council is in its founding period until {f.until:%Y-%m-%d}, "
                            f"or until it has {f.size} full members ({missing} to go). "
                            f"Founder: {crypto.key_to_text(f.founder)}.\n")
        last: dict[str, datetime] = {}
        for i in spoken:
            if i.author not in last or i.date > last[i.author]:
                last[i.author] = i.date
        for k in cur.full:
            key = crypto.key_to_text(k)
            if key in last:
                ends = last[key] + pr.ACTIVE_WITHIN
                if now < ends <= now + INACTIVE_WARN:
                    await self._log(logbook, f"inactive soon {key} {ends:%Y-%m-%d}",
                                    f"{key} stops being an active member on {ends:%Y-%m-%d} "
                                    f"unless it posts in the talk or proposals group. Its replica "
                                    f"keeps working; it only no longer counts when people decide "
                                    f"(UN-RFC 0061 section 2).\n")


def _describe_change(before: cn.CouncilManifest, after: cn.CouncilManifest) -> str:
    """A counted change of the council in plain words, for the log."""
    old = {m.key: m for m in before.members}
    new = {m.key: m for m in after.members}
    for k, m in new.items():
        if k not in old:
            how = "by the founder's request" if m.by == cn.FOUNDER else \
                "after running as a shadow, agreeing with the council"
            return (f"Admitted {crypto.key_to_text(k)} on probation, {how} "
                    f"(UN-RFC 0054 sections 11, 19). Manifest {after.seq}, {after.date:%Y-%m-%d}.\n")
    for k in old:
        if k not in new:
            return (f"Removed {crypto.key_to_text(k)} (UN-RFC 0054 section 12: a certificate no "
                    f"claim explains, losing alone on DNS, silence or stepping down). "
                    f"Manifest {after.seq}, {after.date:%Y-%m-%d}.\n")
    for k, m in new.items():
        if m.full and not old[k].full:
            return (f"{crypto.key_to_text(k)} is a full member now: its probation is over. "
                    f"Manifest {after.seq}, {after.date:%Y-%m-%d}.\n")
    if before.founding != after.founding and after.founding is not None:
        if after.founding.renounced:
            return f"The founder renounced the founding period. Manifest {after.seq}.\n"
        return (f"The founding period now lasts until {after.founding.until:%Y-%m-%d}. "
                f"Manifest {after.seq}.\n")
    changed = sorted(k for k in set(before.data) | set(after.data)
                     if k not in ("council", "serial") and before.data.get(k) != after.data.get(k))
    params = [k for k in ("min_level", "max_probation", "sponsors")
              if getattr(before, k) != getattr(after, k)]
    return (f"Manifest {after.seq}, {after.date:%Y-%m-%d}: changed "
            f"{', '.join(changed + params) or 'nothing visible'}.\n")
