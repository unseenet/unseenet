"""A server's operator channel (UN-RFC 0065, #876), on a ``Session``.

The server makes its channel key itself and keeps it in its vault as the team key for
the channel (section 3.1); the operator lists its public key among the channel's
readers with the owner key. The server then posts notices there and reads its
operators' commands, which ``core.operator.Desk`` answers.

Belongs here: the channel key, whether the server is a reader yet, notices (once per
matter, ``info`` gathered into digests, ``warn`` a little late), reading and answering
commands, and the owner's side - adding the server and operators to a channel.

Not here: the commands themselves (each server's own), the rules of a command
(``core/operator.py``).
"""

from __future__ import annotations

import asyncio
import random
import time

from ..core import crypto
from ..core import operator as op
from ..core.markup import MARKDOWN_TYPE
from .session import KIND_CHAT, Session, SessionError

DIGEST_SECONDS = 3600         # info notices are gathered at most this long (section 4)
WARN_DELAY = 600              # warn notices wait up to this long (section 4, 9)


def box_servers(session: Session, group_id: str) -> list[dict]:
    """The servers in an operator box, as its messages name them: ``{"name", "key"}``,
    for a client to offer as whom a new message is for (section 3.2) - nobody has to
    remember the names. Servers that have not posted yet have no name."""
    data = session.manifest_data(group_id)
    keys = list(data.get("operator_servers", []))
    names: dict[str, str] = {}
    for m in sorted(session.cache.get(group_id, {}).values(), key=lambda m: m.number):
        if m.readable and m.sender_key and m.operator and m.operator.get("server"):
            if m.operator.get("notice") or m.sender_key in keys:
                names[m.sender_key] = m.operator["server"]
                keys += [] if m.sender_key in keys else [m.sender_key]
    return [{"name": names.get(k, ""), "key": k} for k in keys]


def address(name: str, text: str) -> str:
    """A message for one server in a box several read: its name and a colon first."""
    return f"{name}: {text.lstrip()}" if name else text


def make_channel_key(session: Session, group_id: str) -> str:
    """The server's channel key for ``group_id``, made now if it has none: kept in its
    vault like a team key, never sent anywhere. Returns its public key, as text, for the
    operator to list among the channel's readers (section 3.1)."""
    keys = session._team_keys()
    if group_id not in keys:
        team = crypto.Identity.generate()
        keys[group_id] = {"seed": team.seed.hex(), "identity": session.default_identity_name(),
                          "name": "", "server": True}
        session.save()
    return session.team_key(group_id).key_text


async def add_server(session: Session, group_id: str, server_key: str,
                     team_name: str | None = None) -> None:
    """Owner: list a server's channel key among the box's readers, and among its
    servers, and mark the inbox as an operator box. No invitation: the server made the
    key and holds it."""
    data = await session._own_inbox(group_id)
    key = server_key.strip()
    crypto.key_from_text(key)
    readers = list(data.get("readers", []))
    servers = list(data.get("operator_servers", []))
    readers += [] if key in readers else [key]
    servers += [] if key in servers else [key]
    changes = {"readers": readers, "operator_servers": servers, "operator_channel": True}
    if team_name is not None:
        changes["team_name"] = team_name.strip() or None
    await session.update_group(group_id, **changes)


class OperatorChannel:
    """The server's side. ``commands``: its own (``core.operator.Command``); ``status``:
    a function that says, in words, how the server is (for ``status``). ``mode``:
    ``operator_channel`` (``off``, ``notices``, ``commands``)."""

    def __init__(self, session: Session, group_id: str, commands: list[op.Command] = (), *,
                 mode: str = "notices", status=None, server: str | None = None,
                 now=time.time, warn_delay: float = WARN_DELAY, code=None):
        self.s, self.group, self.server, self.now = session, group_id, server, now
        self.warn_delay = warn_delay
        self.state = session.data.setdefault("operator_channels", {}).setdefault(group_id, {})
        self.state.setdefault("open", {})
        self.state.setdefault("digest", [])
        self.state.setdefault("servers", [])
        self._status = status
        builtin = [op.Command("status", "how the server is", run=self._status_text),
                   op.Command("notices", "what is still open", run=self._open_text)]
        self.desk = op.Desk(builtin + list(commands), self.state, mode=mode, server=server,
                            now=now, code=code)

    def _server_keys(self, manifest: dict | None = None) -> set[str]:
        """The other servers in the box: listed by its owner (``operator_servers``) or
        seen posting notices (section 3.2)."""
        data = manifest if manifest is not None else self.s.manifest_data(self.group)
        mine = self.key.key_text if self.key else None
        return (set(data.get("operator_servers", [])) | set(self.state.get("servers", []))) - {mine}

    @property
    def key(self) -> crypto.Identity | None:
        return self.s.team_key(self.group)

    async def ready(self) -> bool:
        """True when the channel's manifest lists this server's channel key (section 3.1);
        until then it posts and takes nothing."""
        if self.key is None:
            raise SessionError("this server has no channel key: make one first")
        m = await self.s.fetch_manifest(self.group)
        if m is None or m.type != "inbox":
            return False
        self.s.group_entry(self.group)["manifest"] = dict(m.raw)
        self.s.group_entry(self.group)["type"] = "inbox"
        self.s.group_entry(self.group)["owner_key"] = crypto.key_to_text(m.owner)
        if self.group not in self.s.data["subscribed"]:
            self.s.subscribe(self.group)
        readers = m.raw.get("readers", [])
        if self.key.key_text not in readers:
            return False
        await self._greet(m.raw, readers)
        return True

    async def _greet(self, manifest: dict, readers: list[str]) -> None:
        """Say hello when the server becomes a reader, and again when an operator is
        added: a message the operators can answer from any client - one that cannot
        start a message in a team inbox can always reply (UN-RFC 0065 section 7)."""
        me = self.key.key_text
        others = sorted(set(readers) - {me} - self._server_keys(manifest))
        greeted = set(self.state.get("greeted", []))
        if not others or set(others) <= greeted:
            return
        pending = self.state.get("greeting")
        msgs = await self.s.fetch_group(self.group)
        if pending and set(pending["for"]) == set(others):
            # tried before and cut off (a restart, a timeout after the node took it):
            # posted already if the channel shows it - one hello, not two. Dates are
            # coarse (UN-RFC 0009), so article numbers tell what came after.
            if any(m.sender_key == me and m.operator and m.operator.get("notice") == "hello"
                   and m.number > pending["after"] for m in msgs):
                self.state["greeted"] = others
                self.state.pop("greeting", None)
                self.s.save()
                return
        else:
            self.state["greeting"] = {"for": others,
                                      "after": max((m.number for m in msgs), default=0)}
            self.s.save()
        name = self.server or manifest.get("team_name") or "This server"
        text = (f"**{name}** reads this box now. Answer this message with `help` for what "
                "it can do here, or `status` for how it is.")
        if self._server_keys(manifest):
            text += (f" Other servers read the box too: start a new message with "
                     f"`{name}:` for this one.")
        if self.desk.mode != "commands":
            text += ("\n\nCommands that change something are off (operator_channel = "
                     "notices); they are turned on on the server.")
        await self._post(text, op.notice_headers("hello", "info", server=self.server,
                                                 offers=[op.offer("help"), op.offer("status")]))
        self.state["greeted"] = others
        self.state.pop("greeting", None)
        self.s.save()

    # --- notices (section 4) ---
    async def notice(self, kind: str, text: str, level: str = "info", *, key: str | None = None,
                     over: bool = False, offers=(), now: float | None = None) -> str | None:
        """Tell the operators. A matter with a ``key`` is told once until it is over; its
        ``over`` notice only when it was open. ``info`` waits for the next digest
        (``flush``), ``warn`` a random time of up to ``warn_delay``, ``alarm`` nothing.
        The Message-ID when something was posted now."""
        op.notice_headers(kind, level, key=key, over=over, server=self.server, offers=offers)
        opened = self.state["open"]
        if key is not None:
            if over:
                if key not in opened:
                    return None
                del opened[key]
            elif key in opened:
                return None
            else:
                opened[key] = {"kind": kind, "level": level, "text": text.strip().splitlines()[0][:200]}
            self.s.save()
        if level == "info" and not over:
            self.state["digest"].append({"at": now or self.now(), "text": text.strip()})
            self.s.save()
            return await self.flush(now=now)
        if level == "warn" and self.warn_delay:
            await asyncio.sleep(random.uniform(0, self.warn_delay))
        return await self._post(text, op.notice_headers(kind, level, key=key, over=over,
                                                         server=self.server, offers=offers))

    async def flush(self, force: bool = False, now: float | None = None) -> str | None:
        """Post the gathered ``info`` notices as one digest, once the oldest has waited
        ``DIGEST_SECONDS`` (or now, with ``force``)."""
        digest = self.state["digest"]
        now = now or self.now()
        if not digest or (not force and now - digest[0]["at"] < DIGEST_SECONDS):
            return None
        body = "\n\n".join(d["text"] for d in digest)
        mid = await self._post(body, op.notice_headers("digest", "info", server=self.server))
        digest.clear()
        self.s.save()
        return mid

    async def _post(self, text: str, headers, references=None) -> str:
        return await self.s.send_private(self.group, "", text.rstrip() + "\n", kind=KIND_CHAT,
                                         as_team=self.group, extra=list(headers),
                                         content_type=MARKDOWN_TYPE,
                                         references=references, remember=False)

    # --- commands (section 5) ---
    async def poll(self) -> list[tuple[str, op.Answer]]:
        """Read the channel and answer each new command from a reader (section 3.3).
        ``(command Message-ID, answer)`` of what was answered now. On the first poll the
        messages already there are taken as handled, not answered."""
        msgs = sorted(await self.s.fetch_group(self.group), key=lambda m: m.number)
        readers = set(self.s.manifest_data(self.group).get("readers", []))
        me = self.key.key_text
        first = not self.state.get("started")
        out = []
        for msg in msgs:
            if (msg.readable and msg.sender_key and msg.sender_key != me and msg.operator
                    and msg.operator.get("notice") and msg.sender_key not in self.state["servers"]):
                self.state["servers"].append(msg.sender_key)       # another server's (3.2)
        servers = self._server_keys()
        mine = {m.message_id for m in msgs if m.sender_key == me}
        theirs = {m.message_id for m in msgs if m.sender_key in servers}
        others = {m.operator["server"].lower() for m in msgs
                  if m.sender_key in servers and m.operator and m.operator.get("server")}
        for msg in msgs:
            if not msg.readable or not msg.sender_key:
                continue
            if first:
                self.state["handled"][msg.message_id] = self.now()
                continue
            team = self.s.team_sender(msg)
            if (msg.sender_key == me or msg.sender_key in servers
                    or msg.sender_key not in readers
                    or not team or team["group"] != self.group or not team["verified"]):
                continue
            parent = msg.references[-1] if msg.references else None
            to_me = True if parent in mine else False if parent in theirs else None
            answer = await self.desk.take(msg.message_id, msg.sender_key, msg.date, msg.body,
                                          to_me=to_me, shared=bool(servers), others=others)
            if answer is None:
                continue
            self.s.save()
            await self._post(answer.text, answer.headers(msg.message_id, self.server),
                             references=[msg.message_id])
            out.append((msg.message_id, answer))
        if first:
            self.state["started"] = self.now()
        self.s.save()
        return out

    async def _status_text(self, args) -> str:
        if self._status is None:
            return "Running."
        got = self._status()
        return op.as_markdown(await got if asyncio.iscoroutine(got) else str(got))

    async def _open_text(self, args) -> str:
        opened = self.state["open"]
        if not opened:
            return "Nothing is open."
        return "\n".join(f"- **{v['level']}** {v['text']} (`{k}`)" for k, v in sorted(opened.items()))
