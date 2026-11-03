"""Operator channels (UN-RFC 0065, #876): what a server and its operators agree on.

A server posts notices in its channel - a team inbox (UN-RFC 0047) whose readers are the
server's channel key and its operators' team keys - and takes commands from it. This is
the part without a network: reading a command, the confirmation code for anything that
changes something (section 5.2), carrying each command out once and never one too old
(5.3), the answers (5.4), what chat may not do (5.5), and offers - buttons (section 6).

Belongs here: ``Desk`` (a server's commands and their state), ``Command``, ``Answer``,
the inner headers and offers.

Not here: reading and posting the channel (``client/operator.py``), each server's own
commands (in the server's package).
"""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable

CODE_SECONDS = 30 * 60            # a confirmation code is valid this long (section 5.2)
COMMAND_MAX_AGE = 60 * 60         # a command older than this is not carried out (5.3)
HANDLED_DAYS = 30                 # how long handled Message-IDs are kept (5.3)
LEVELS = ("info", "warn", "alarm")
MODES = ("off", "notices", "commands")     # the server's operator_channel setting (5.5)
READ_ONLY = ("help", "status", "notices")  # what every server takes, also in notices (5.1)
MAX_OFFERS = 6
OFFER_LABEL_MAX = 40
_KIND = re.compile(r"^[a-z0-9-]{1,32}$")
_SERVER = re.compile(r"^[A-Za-z0-9-]{1,32}$")
_CODE = re.compile(r"^\d{4}$")
_OFFER_NAME = re.compile(r"^offer-([1-6])$")   # Offer-1 .. Offer-6: a header appears once

# the inner headers (sections 3.2, 4, 5.2, 5.4, 6)
H_NOTICE, H_LEVEL, H_KEY, H_OVER = "Operator-Notice", "Notice-Level", "Notice-Key", "Notice-Over"
H_SERVER, H_CODE, H_FOR, H_RESULT, H_OFFER = (
    "Server-Name", "Confirm-Code", "Confirm-For", "Command-Result", "Offer")
RESULTS = ("asked", "done", "refused", "failed")


# --- offers (section 6) ---
@dataclass(frozen=True)
class Offer:
    reply: str
    label: str = ""

    def header(self) -> str:
        return f"{self.reply} | {self.label}" if self.label and self.label != self.reply else self.reply


def offer(reply: str, label: str = "") -> Offer:
    """An offer, checked: a reply on one line, a label of at most 40 characters."""
    reply, label = " ".join(reply.split()), " ".join(label.split())
    if not reply or "|" in reply:
        raise ValueError("an offer's reply is one line of text without |")
    if len(label) > OFFER_LABEL_MAX:
        raise ValueError(f"an offer's label is at most {OFFER_LABEL_MAX} characters")
    return Offer(reply, label)


def parse_offers(values: list[str]) -> list[Offer]:
    """The offers of a message's ``Offer-<n>`` headers, in order, at most six; broken
    ones are left out."""
    out = []
    for v in values:
        reply, _, label = (v or "").partition("|")
        try:
            out.append(offer(reply, label))
        except ValueError:
            continue
        if len(out) == MAX_OFFERS:
            break
    return out


def operator_fields(headers: list[tuple[str, str]]) -> dict | None:
    """What a client shows of a message in an operator channel, from its inner headers:
    ``{"notice", "level", "key", "over", "server", "code", "for", "result", "offers"}``,
    or None for a message that has none of them (an operator's command)."""
    get = {}
    offers = []
    for k, v in headers:
        lk = k.lower()
        m = _OFFER_NAME.match(lk)
        if m:
            offers.append((int(m.group(1)), v))
        else:
            get.setdefault(lk, (v or "").strip())
    offers = [v for _, v in sorted(offers)]
    notice = get.get(H_NOTICE.lower(), "")
    result = get.get(H_RESULT.lower(), "")
    parsed = parse_offers(offers)
    if not (notice or result or parsed):
        return None
    level = get.get(H_LEVEL.lower(), "info")
    return {"notice": notice if _KIND.match(notice) else ("other" if notice else None),
            "level": level if level in LEVELS else "info",
            "key": get.get(H_KEY.lower()) or None,
            "over": get.get(H_OVER.lower(), "").lower() == "yes",
            "server": get.get(H_SERVER.lower()) or None,
            "code": get.get(H_CODE.lower()) or None,
            "for": get.get(H_FOR.lower()) or None,
            "result": result if result in RESULTS else None,
            "offers": [{"reply": o.reply, "label": o.label or o.reply} for o in parsed]}


def notice_headers(kind: str, level: str = "info", *, key: str | None = None, over: bool = False,
                   server: str | None = None, offers=()) -> list[tuple[str, str]]:
    """The inner headers of a notice (section 4), checked."""
    if not _KIND.match(kind):
        raise ValueError("a notice's kind is a word of a-z, 0-9 and -, at most 32")
    if level not in LEVELS:
        raise ValueError("a notice's level is info, warn or alarm")
    out = [(H_NOTICE, kind), (H_LEVEL, level)]
    if key:
        out.append((H_KEY, " ".join(key.split())[:64]))
    if over:
        out.append((H_OVER, "yes"))
    return out + _common(server, offers)


def _common(server: str | None, offers) -> list[tuple[str, str]]:
    out = []
    if server:
        if not _SERVER.match(server):
            raise ValueError("a server's name is letters, digits and -, at most 32")
        out.append((H_SERVER, server))
    offers = list(offers)
    if len(offers) > MAX_OFFERS:
        raise ValueError(f"at most {MAX_OFFERS} offers")
    return out + [(f"{H_OFFER}-{i}", o.header()) for i, o in enumerate(offers, 1)]


# --- commands (section 5) ---
class Args(list):
    """A command's words after the verb (``args[0]`` ...), and ``text``: all it said after
    the verb, also on later lines - for ``talk: <text>``."""
    text: str = ""

    @classmethod
    def of(cls, words: list[str], text: str) -> "Args":
        a = cls(words)
        a.text = text
        return a


@dataclass
class Command:
    """One of a server's commands. ``run(args)`` does it and says in words what happened.
    ``describe(args)``: for a command that ``changes`` something, what it would do, in
    words, for the confirmation (section 5.2); it may raise ``ValueError`` for wrong
    arguments. ``cli_only``: never from the channel (section 5.5)."""
    name: str
    help: str
    run: Callable[[list[str]], Awaitable[str]] | None = None
    changes: bool = False
    describe: Callable[[list[str]], str] | None = None
    cli_only: bool = False
    usage: str = ""
    label: str = ""                    # the confirmation offer's label ("Second it")


@dataclass
class Answer:
    """What the server answers a command (section 5.4)."""
    result: str
    text: str
    code: str | None = None
    offers: list[Offer] = field(default_factory=list)

    def headers(self, command_id: str, server: str | None = None) -> list[tuple[str, str]]:
        out = [(H_RESULT, self.result)]
        if self.code:
            out += [(H_CODE, self.code), (H_FOR, command_id)]
        return out + _common(server, self.offers)


class Desk:
    """A server's side of its channel: its commands, and what it remembers - the
    Message-IDs it handled, the confirmations it waits for. ``state`` is a dict the
    server keeps (in its vault or state file) and is changed in place. ``mode`` is the
    ``operator_channel`` setting (section 5.5). ``server``: its name, which a message in
    a box several servers read starts with (section 3.2)."""

    def __init__(self, commands: list[Command], state: dict, *, mode: str = "notices",
                 server: str | None = None, now: Callable[[], float] = time.time,
                 code: Callable[[], str] | None = None):
        if mode not in MODES:
            raise ValueError("operator_channel is off, notices or commands")
        if server is not None and not _SERVER.match(server):
            raise ValueError("a server's name is letters, digits and -, at most 32")
        self.commands = {c.name: c for c in commands}
        self.state, self.mode, self.server, self.now = state, mode, server, now
        self._code = code or (lambda: f"{secrets.randbelow(10000):04d}")
        state.setdefault("handled", {})
        state.setdefault("waiting", {})

    def help(self) -> str:
        lines = ["help - this list", "status - how the server is", "notices - what is still open"]
        for c in sorted(self.commands.values(), key=lambda c: c.name):
            if c.name in READ_ONLY:
                continue
            what = c.help + (" (only on the server itself)" if c.cli_only else
                             " (asks you to confirm)" if c.changes else "")
            lines.append(f"{c.name}{' ' + c.usage if c.usage else ''} - {what}")
        if self.mode != "commands":
            lines.append("")
            lines.append("Commands from here are off: this server takes only help, status and "
                         "notices (operator_channel = notices).")
        return "\n".join(lines)

    def _prune(self, now: float) -> None:
        handled = self.state["handled"]
        for mid in [m for m, t in handled.items() if now - t > HANDLED_DAYS * 86400]:
            del handled[mid]
        waiting = self.state["waiting"]
        for who in [w for w, x in waiting.items() if now > x["until"]]:
            del waiting[who]

    def _parse(self, text: str, others=frozenset()) -> tuple[str, Args, bool] | None:
        """``(verb, args, addressed)``: ``addressed`` when it starts with this server's
        name and a colon (section 3.2); None when it starts with another server's name
        (``others``, lower case) or says nothing."""
        text = (text or "").strip()
        name, colon, rest = text.partition(":")
        head = name.strip().lower() if colon and "\n" not in name else ""
        addressed = bool(self.server) and head == self.server.lower()
        if addressed:
            text = rest.strip()
        elif head and head in others:
            return None                              # for another server (section 3.2)
        words = text.splitlines()[0].split() if text else []
        if not words:
            return None
        verb = words[0].rstrip(":").lower()          # "talk: hello" as "talk hello"
        rest = text[len(words[0]):].strip()
        return verb, Args.of(words[1:], rest), addressed

    async def take(self, message_id: str, sender: str, date: datetime | None,
                   text: str, *, to_me: bool | None = None, shared: bool = False,
                   others=frozenset()) -> Answer | None:
        """A message from a reader of the channel (the caller has checked that, section
        3.3). The answer to post as its reply, or None when it is not for this server or
        was handled before. ``date``: the message's Date.

        In a box several servers read (``shared``, section 3.2) a message is for this
        server when it starts with its name, or answers one of its messages (``to_me``
        True; False: another server's). Anything else is for all of them: each answers
        ``help``, ``status`` and ``notices``, and a ``yes`` with the code it waits for;
        the rest is left to the server it names."""
        now = self.now()
        self._prune(now)
        if message_id in self.state["handled"]:
            return None                              # once only (section 5.3)
        parsed = self._parse(text, others)
        if parsed is None:
            return None
        verb, args, addressed = parsed
        if not addressed and to_me is not True and shared:
            if to_me is False:
                return None                          # an answer to another server
            waiting = self.state["waiting"].get(sender)
            if verb == "yes" and not (waiting and list(args) == [waiting["code"]]):
                return None
            if verb not in READ_ONLY + ("yes",):
                return None
        self.state["handled"][message_id] = now
        waiting = self.state["waiting"].pop(sender, None)
        if date is not None and now - date.timestamp() > COMMAND_MAX_AGE:
            return Answer("refused", "This came too late (over an hour after it was written): "
                                     "not carried out. Send it again if it is still wanted.")
        if verb == "yes":
            return await self._confirm(waiting, args)
        if verb == "no":
            return Answer("refused", f"Cancelled: {waiting['what']}" if waiting
                          else "There is nothing waiting to cancel.")
        cancelled = (f"Cancelled: {waiting['what']}\n\n" if waiting else "")
        answer = await self._command(message_id, sender, verb, args)
        if cancelled:
            answer.text = cancelled + answer.text
        return answer

    async def _confirm(self, waiting: dict | None, args: list[str]) -> Answer:
        if waiting is None:
            return Answer("refused", "There is nothing waiting for you to confirm.")
        if len(args) != 1 or args[0] != waiting["code"]:
            return Answer("refused", f"Wrong code: cancelled - {waiting['what']}")
        if self.mode != "commands":
            return Answer("refused", "Commands from here are off (operator_channel = notices).")
        cmd = self.commands.get(waiting["verb"])
        return await self._run(cmd, Args.of(waiting["args"], waiting.get("text", "")))

    async def _command(self, message_id: str, sender: str, verb: str, args: list[str]) -> Answer:
        if verb == "help":
            return Answer("done", self.help())
        cmd = self.commands.get(verb)
        if cmd is None:
            return Answer("refused", f"Unknown command: {verb}. Answer help for the list.",
                          offers=[Offer("help")])
        if cmd.cli_only:
            return Answer("refused", f"{verb} is done only on the server itself, from its "
                                     "command line - never from here.")
        if self.mode != "commands" and verb not in READ_ONLY:
            return Answer("refused", "Commands from here are off: this server takes only help, "
                                     "status and notices (operator_channel = notices).")
        if not cmd.changes:
            return await self._run(cmd, args)
        try:
            what = cmd.describe(args) if cmd.describe else f"{verb} {' '.join(args)}".strip()
        except ValueError as exc:
            return Answer("refused", f"{exc}\nUsage: {verb} {cmd.usage}".rstrip())
        code = self._code()
        assert _CODE.match(code)
        self.state["waiting"][sender] = {"code": code, "verb": verb, "args": list(args),
                                         "text": getattr(args, "text", ""), "what": what,
                                         "until": self.now() + CODE_SECONDS, "for": message_id}
        minutes = CODE_SECONDS // 60
        return Answer("asked", f"{what}?\nAnswer *yes {code}* within {minutes} minutes. "
                               "Anything else cancels it.", code=code,
                      offers=[Offer(f"yes {code}", cmd.label or "Yes"), Offer("no", "Cancel")])

    @staticmethod
    async def _run(cmd: Command | None, args: list[str]) -> Answer:
        if cmd is None or cmd.run is None:
            return Answer("failed", "This server cannot do that any more.")
        try:
            return Answer("done", await cmd.run(args))
        except Exception as exc:  # noqa: BLE001 - said to the operator, not raised
            return Answer("failed", f"It did not work: {exc}")
