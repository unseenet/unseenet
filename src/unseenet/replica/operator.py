"""The replica's operator channel (UN-RFC 0065 section 8, #874 part 2): the first server
that uses the channel.

What the replica tells its operators - changes held for them, a twin alarm, a disputed
council, hearings about to close, rounds that fail - and the council work they do from
their everyday client: agree, hold, second, object, talk, reply, and reading hearings,
members, talk and log. Each command does exactly what ``unseenet-replica <command>``
does, through the same functions, and what it queues is posted at once.

Belongs here: the replica's commands and notices, and the loop that reads the channel.

Not here: the channel itself (``client/operator.py``), its rules (``core/operator.py``).
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..client import operator as oc
from ..core import operator as op

log = logging.getLogger("unseenet.replica")

POLL_SECONDS = 60                 # how often the channel is read for commands
CLOSING = timedelta(hours=48)     # a hearing this close to its end is told about
QUEUED = "Queued: the replica posts it at its next round."


def _lists_first(args: list[str]) -> tuple[bool, list[str]]:
    """``lists`` as the first word: the list council (UN-RFC 0020), else the registrar."""
    if args and args[0].lower() == "lists":
        return True, list(args[1:])
    return False, list(args)


class ReplicaChannel:
    """The channel of one replica. ``rep`` is the running ``Replica``; ``state_dir`` its
    folder (config, status, outbox)."""

    def __init__(self, rep, group_id: str, mode: str, state_dir: Path, **kw):
        self.rep, self.d = rep, Path(state_dir)
        self.latest: dict | None = None      # the newest round's status, not told yet
        self.info: dict = {"reader": None, "error": None}
        self.chan = oc.OperatorChannel(rep.s, group_id, self._commands(), mode=mode,
                                       status=self._status, **kw)

    # --- commands: the replica's own command line, run here -----------------------------
    def _cli(self, fn, **kw) -> str:
        """Run one of ``unseenet-replica``'s commands and give back what it said."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                code = fn(Namespace(dir=str(self.d), json=False, yes=True, force=False, **kw))
            except SystemExit as exc:
                if exc.code not in (None, 0):
                    raise RuntimeError(str(exc.code) if isinstance(exc.code, str)
                                       else out.getvalue().strip() or "not done") from None
                code = 0
        text = out.getvalue().strip()
        if code:
            raise RuntimeError(text or "not done")
        return text

    async def _queued(self, text: str) -> str:
        """What was queued goes now, not at the next round (section 8)."""
        if QUEUED in text:
            await self.rep._outbox()
            box = self.d / "outbox"
            left = list(box.glob("*.json")) if box.is_dir() else []
            text = text.replace(QUEUED, "Posted." if not left else
                                "Queued: a node did not take it yet; the replica tries again "
                                "at its next round.")
        return text

    def _status_of(self, lists: bool) -> dict:
        from .cli import read_status
        st = read_status(self.d)
        return (st.get("lists") or {}) if lists else st

    def _commands(self) -> list[op.Command]:
        from . import cli

        def read_only(name, help_, fn, usage="", **fixed):
            async def run(args):
                lists, rest = _lists_first(args)
                extra = dict(fixed)
                if name == "read":
                    if not rest or rest[0] not in ("talk", "log"):
                        raise ValueError("read talk or read log")
                    extra.update(group=rest[0], n=10)
                return self._cli(fn, lists=lists, **extra)
            return op.Command(name, help_, run=run, usage=usage)

        def change(name, help_, fn, describe, usage, label, build):
            async def run(args):
                return await self._queued(self._cli(fn, **build(args)))
            return op.Command(name, help_, run=run, changes=True, describe=describe,
                              usage=usage, label=label)

        def need(args, n, what):
            if len(args) < n:
                raise ValueError(what)

        # agree, hold
        def agree_what(args):
            need(args, 1, "Which held change? (status lists them)")
            held = self._status_of(False).get("held") or {}
            if args[0] not in held:
                raise ValueError(f"No change {args[0]} is held now.")
            return f"Let the held change {args[0]} go ahead"

        def hold_what(args):
            need(args, 1, "hold none, or the kinds: admission,promotion,removal,...")
            cli._kinds(args[0]) if args[0] not in ("none", "") else None
            return f"Hold {args[0]} from now on"

        # second, object
        def proposal(args) -> tuple[bool, str, dict]:
            need(args, 1, "Which proposal? (hearings lists them)")
            for lists in (False, True):
                st = self._status_of(lists)
                pending = (st.get("proposals_pending") or {}).get(args[0])
                hearing = next((h for h in st.get("hearings") or [] if h["id"] == args[0]), None)
                if pending or hearing:
                    return lists, args[0], pending or hearing
            raise ValueError(f"No proposal {args[0]} is waiting or in its hearing.")

        def second_what(args):
            from ..core import proposals as pr
            lists, pid, p = proposal(args)
            if "body" not in p:
                raise ValueError(f"Proposal {pid} is in its hearing already; nothing to second.")
            shown = pr.parse_proposal(p["body"])
            return (f"Second proposal {pid}{' (list council)' if lists else ''}: "
                    f"{shown.reason[:200]}")

        def object_what(args):
            lists, pid, _ = proposal(args)
            need(args, 2, "object <id> <reason>")
            return f"Object to proposal {pid}{' (list council)' if lists else ''}: " \
                   f"{' '.join(args[1:])[:200]}"

        def object_build(args):
            lists, pid, _ = proposal(args)
            return dict(id=pid, reason=" ".join(args[1:]), withdraw=False, lists=lists)

        # talk, reply
        def text_of(args, skip: int) -> str:
            text = args.text
            for _ in range(skip):
                text = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
            return text.lstrip(":").strip()

        def talk_what(args):
            lists, _ = _lists_first(args)
            text = text_of(args, 1 if lists else 0)
            if not text:
                raise ValueError("talk: <what to say>")
            return f"Post in talk{' (list council)' if lists else ''} as the member: " \
                   f"{text.splitlines()[0][:120]}"

        def talk_build(args):
            lists, _ = _lists_first(args)
            text = text_of(args, 1 if lists else 0)
            return dict(subject=text.splitlines()[0][:80], text=text, lists=lists)

        def reply_parts(args):
            lists, rest = _lists_first(args)
            need(rest, 1, "reply <id>: <answer>")
            mid = rest[0].rstrip(":")
            text = text_of(args, 2 if lists else 1)
            if not text:
                raise ValueError("reply <id>: <answer>")
            return lists, (mid if mid.startswith("<") else f"<{mid}>"), text

        def reply_what(args):
            lists, mid, text = reply_parts(args)
            return f"Answer {mid} in talk as the member: {text.splitlines()[0][:120]}"

        def reply_build(args):
            lists, mid, text = reply_parts(args)
            return dict(id=mid, text=text, lists=lists)

        return [
            read_only("hearings", "proposals in their hearing, and those waiting", cli.hearings,
                      "[lists]"),
            read_only("members", "the council's members and candidates", cli.members, "[lists]"),
            read_only("read", "the newest posts in talk or log", cli.read, "[lists] talk|log"),
            change("agree", "let a held change go ahead", cli.agree, agree_what, "<label>",
                   "Agree", lambda a: dict(label=a[0])),
            change("hold", "which changes wait for you", cli.hold, hold_what, "<kinds>|none",
                   "Hold them", lambda a: dict(kinds=a[0])),
            change("second", "post a waiting proposal too", cli.second, second_what, "<id>",
                   "Second it", lambda a: dict(id=proposal(a)[1], lists=proposal(a)[0])),
            change("object", "object to a proposal (public)", cli.object_, object_what,
                   "<id> <reason>", "Object", object_build),
            change("talk", "post in the council's talk group", cli.talk, talk_what,
                   "[lists]: <text>", "Post it", talk_build),
            change("reply", "answer a post in talk", cli.reply, reply_what, "[lists] <id>: <text>",
                   "Post it", reply_build),
            op.Command("resign", "step down from the council", cli_only=True),
            op.Command("sign", "post this replica's copy of a new council's genesis",
                       cli_only=True),
            op.Command("twin-gone", "the other user of this replica's key is stopped",
                       cli_only=True),
        ]

    def _status(self) -> str:
        from .cli import explain, read_config, read_status
        return "\n".join(explain(read_status(self.d), read_config(self.d)))

    # --- notices, from the status after a round (section 4) -----------------------------
    async def tell(self, st: dict, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        c = self.chan
        twin = st.get("twin")
        if twin:
            await c.notice("twin", "TWIN ALARM: something else posts with this replica's key - "
                           "most likely a copy of it on another machine. It signs nothing until "
                           f"you act. The article: {twin.get('subject')!r}.\nStop the other copy, "
                           "then on the server: unseenet-replica twin-gone "
                           f"{twin.get('message_id')}", "alarm", key="twin")
        else:
            await c.notice("twin", "The twin alarm is over: the replica signs again.", "alarm",
                           key="twin", over=True)
        if st.get("disputed"):
            await c.notice("disputed", "The council is disputed: its members' copies of the "
                           "manifest disagree. Nothing changes until it is settled.", "alarm",
                           key="disputed")
        else:
            await c.notice("disputed", "The council is no longer disputed.", "alarm",
                           key="disputed", over=True)
        held = st.get("held") or {}
        for label, what in held.items():
            why = what.get("why") if isinstance(what, dict) else what
            await c.notice("held", f"A change waits for you: {label}" + (f" - {why}" if why else "")
                           + f"\nAnswer: agree {label}", "warn", key=f"held:{label}",
                           offers=[op.offer(f"agree {label}", "Agree")])
        for key in [k for k in c.state["open"] if k.startswith("held:") and k[5:] not in held]:
            await c.notice("held", f"{key[5:]} no longer waits for you.", "info", key=key,
                           over=True)
        if st.get("error"):
            await c.notice("round-failed", f"A round failed: {st['error']}", "warn", key="round")
        else:
            await c.notice("round-failed", "Rounds work again.", "info", key="round", over=True)
        for lists in (False, True):
            src = (st.get("lists") or {}) if lists else st
            for h in src.get("hearings") or []:
                try:
                    closes = datetime.fromisoformat(h["closes"].replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    continue
                if h.get("state") == "open" and timedelta(0) < closes - now <= CLOSING:
                    await c.notice("hearing-closing", f"The hearing on proposal {h['id']} "
                                   f"closes {closes:%d %b %H:%M} UTC ({h['objections']} "
                                   f"objection(s), {h['active']} active): {h['reason'][:200]}",
                                   "info", key=f"closing:{h['id']}")
        await c.flush()

    async def round(self, st: dict) -> None:
        """After the replica's round: tell, then answer what came."""
        if not await self.chan.ready():
            return
        await self.tell(st)
        await self.chan.poll()

    def hand(self, st: dict) -> None:
        """The status of the round just done, to tell from at the channel's next turn.
        Never waits: posting in the channel costs postage, minutes on a small machine,
        and must not hold up the council's rounds."""
        self.latest = dict(st)

    async def loop(self, stop: asyncio.Event, seconds: float = POLL_SECONDS) -> None:
        """The channel's own work, beside the replica's rounds: every ``seconds``, tell
        what the newest round found (``hand``) and answer what came - an answer in a
        minute, not at the next round, and the rounds never wait for it."""
        while not stop.is_set():
            try:
                ready = await self.chan.ready()
                self.info.update(reader=ready, error=None)
                if ready:
                    st, self.latest = self.latest, None
                    if st is not None:
                        await self.tell(st)
                    await self.chan.poll()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the replica goes on without it
                log.warning("operator channel not read now: %s", exc)
                self.info["error"] = str(exc)
            try:
                await asyncio.wait_for(stop.wait(), seconds)
            except asyncio.TimeoutError:
                pass


def setup_channel(rep, cfg: dict, state_dir) -> ReplicaChannel | None:
    """The channel the replica's configuration names (``operator_group``, and
    ``operator_channel`` for the mode), with its key made now if it has none; None when
    it names none or turns it off. (``channel`` in the configuration is the update
    channel, ``stable`` or ``main`` - another thing.)"""
    group = cfg.get("operator_group")
    if group and "@" not in group:
        log.warning("operator_group %r is not a Group ID: no operator channel", group)
        return None
    mode = cfg.get("operator_channel", "notices")
    if not group or mode == "off" or state_dir is None:
        return None
    key = oc.make_channel_key(rep.s, group)
    rep.status["operator"] = {"group": group, "key": key, "mode": mode}
    return ReplicaChannel(rep, group, mode, Path(state_dir))
