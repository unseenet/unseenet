"""What the local client API does (UN-RFC 0046), without the web server.

``LocalAPI`` holds one session - a person's unlocked vault, or a service's
key (section 3.2) - with its ``ClientRuntime``, and answers every request of
UN-RFC 0046 section 4 as plain JSON-safe data. ``server.py`` puts it behind
HTTP and a WebSocket; a test or another transport can call it directly.

Moved here from unseenet-gui's runtime (unseenet #139, point 8), so every
front end - the GUI, a screen-reader client, a bot in another language -
gets the same behaviour.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import timedelta
from pathlib import Path

from ... import __version__
from ... import names as nm
from ...core import about as about_text
from ...core import crypto
from ...core import markup
from ...core import ripening as rp
from ...core.groups import (KIND_CHAT, KIND_POST, group_refs, manifest_article, message_kind,
                            personal_inbox_id)
from ...core.vault import Vault, VaultError
from .. import events as ev
from .. import naming
from ..grouptree import group_tree
from ..runtime import NETWORK_ERRORS, RIPEN_TO, SERVICE_RIPEN_TO, ClientRuntime
from ..session import MAX_MENTION_NOTICES, GroupInfo, Message, Session, SessionError
from ..threads import CONTACT, FOR_YOU

API_VERSION = 1
MAX_READ = 500                  # ids per read request
MAX_REFERENCES = 50
GROUP_TYPES = ("open", "moderated", "channel", "closed")
KINDS = {"both": None, "post": [KIND_POST], "chat": [KIND_CHAT]}
SETTINGS_FIELDS = ("title", "description", "rules", "rules_type", "view", "kinds",
                   "low_latency", "min_pow", "retention_days", "comments", "comment_days")
FIXED_FIELDS = ("type", "owner", "name", "local")      # never change (UN-RFC 0004, 4)
PROGRAM_HEADERS = ("x-", "gateway-")                   # what a program may add (section 4.9)


class Locked(Exception):
    """409: unlock (or set up) first."""


class NotFound(Exception):
    """404: no such group or post."""


def _key(text) -> str:
    text = str(text or "").strip()
    crypto.key_from_text(text)                     # raises ValueError on a bad key
    return text


def _kind(data: dict) -> str:
    kind = str(data.get("kind", KIND_POST))
    if kind not in (KIND_POST, KIND_CHAT):
        raise SessionError("kind is post or chat")
    return kind


class LocalAPI:
    """One runtime for UN-RFC 0046. Give it a vault path (a person's client) or
    a session made with ``Session.from_key`` and ``service=True`` (a bot or
    gateway, section 3.2)."""

    def __init__(self, vault_path: Path | None = None, *, session: Session | None = None,
                 service: bool = False, refresh_seconds: float | None = None,
                 ripen_to: int | None = None):
        if (vault_path is None) == (session is None):
            raise ValueError("give a vault path or a session")
        self.vault_path = Path(vault_path) if vault_path is not None else None
        self.service = service
        self.session: Session | None = None
        self.runtime: ClientRuntime | None = None
        self.status = "Locked"
        self.connected = False
        self._refresh_seconds = refresh_seconds
        self._ripen_to = ripen_to if ripen_to is not None else (
            SERVICE_RIPEN_TO if service else RIPEN_TO)
        self._listeners: set[asyncio.Queue] = set()
        self._tasks: set[asyncio.Task] = set()
        self._jobs = 0
        self._send = asyncio.Lock()          # one job at a time: progress belongs to it
        self._job: tuple[str, str] | None = None
        self._off = None
        if session is not None:
            self._attach(session)

    # --- events (section 5) --------------------------------------------------
    def listen(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._listeners.add(q)
        return q

    def unlisten(self, q: asyncio.Queue) -> None:
        self._listeners.discard(q)

    def _broadcast(self, data: dict) -> None:
        for q in list(self._listeners):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(data)

    def _on_event(self, e: ev.Event) -> None:
        if isinstance(e, ev.Status):
            self.status = e.text
        elif isinstance(e, ev.Refreshed):
            self.connected = e.error is None
        self._broadcast(e.to_dict())
        if isinstance(e, ev.Refreshed) and self.session is not None:
            # the status line every front end shows after a round (as the TUI's)
            self._say(f"Offline ({e.error}) - showing saved posts" if e.error
                      else f"Connected to {self.session.node}")
        if self._job is not None:            # progress of the job being sent
            job, group = self._job
            if isinstance(e, ev.PowProgress) and not e.done:
                self._job_event(job, group, "pow", fraction=round(e.fraction, 3))
            elif isinstance(e, ev.Ripening) and e.next_at:
                self._job_event(job, group, "ripening",
                                fraction=round(min(1.0, e.t / e.next_at), 3))

    def emit(self, event: str, **data) -> None:
        """Send an event of a front end's own (UN-RFC 0046 section 6), such as an
        extension's progress, to everyone listening on ``/api/events``. Name it
        ``x-<extension>-...``."""
        self._broadcast({"event": event, **data})

    def _job_event(self, job: str, group: str, state: str, **more) -> None:
        self._broadcast({"event": "job", "job": job, "group": group, "state": state, **more})

    def _say(self, text: str) -> None:
        self.status = text
        self._broadcast(ev.Status(text).to_dict())

    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # --- unlocking and setting up (section 4.2) --------------------------------
    def _attach(self, session: Session) -> None:
        self.session = session
        session.status = lambda text: None           # Status events carry it
        self._off = session.on(self._on_event)
        if self.service:
            self.status = "Starting"

    def needs_setup(self) -> bool:
        s = self.session
        return s is not None and (not s.has_identity() or not s.node)

    async def unlock(self, passphrase: str) -> dict:
        if self.service:
            raise SessionError("a service has no vault to unlock")
        if self.session is None:
            fast = os.environ.get("UNSEENET_INSECURE_FAST_KDF") == "1"
            kdf = {"ops": 1, "mem": 8192 * 1024} if fast else {}
            self._say("Unlocking vault ...")
            try:
                vault = await asyncio.to_thread(Vault.open, self.vault_path, passphrase, **kdf)
            except VaultError as exc:
                self._say("Locked")
                raise SessionError(str(exc) or "wrong passphrase") from exc
            self._attach(Session(vault))
            if self.needs_setup():
                self._say("Choose a name and a node")
            else:
                await self.start()
        return self.state()

    async def setup(self, display: str, node: str) -> dict:
        if self.service:
            raise SessionError("a service is set up with its key file")
        s = self._unlocked()
        display, node = display.strip(), node.strip()
        if self.needs_setup():
            if not s.has_identity():
                if not display:
                    raise SessionError("choose a name")
                s.new_identity(display.lower().replace(" ", "-"), display)
            if not s.node:
                if not node:
                    raise SessionError("choose a node")
                s.add_node(node)
            await self.start()
        return self.state()

    async def start(self) -> None:
        """Run the client runtime: saved posts at once, then the network."""
        s = self._unlocked()
        if self.runtime is not None:
            return
        kw = {} if self._refresh_seconds is None else {"refresh_seconds": self._refresh_seconds}
        self.runtime = ClientRuntime(s, ripen_to=self._ripen_to, **kw)
        loaded = await self.runtime.start()
        self._say(f"{loaded} saved posts available offline - connecting ...")

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.runtime is not None:
            await self.runtime.stop()
            self.runtime = None
        if self.session is not None:
            with contextlib.suppress(Exception):
                await self.session.close()
            if self._off:
                self._off()
                self._off = None
        if not self.service:
            self.session = None
            self.status = "Locked"

    def _unlocked(self) -> Session:
        if self.session is None:
            raise Locked("locked")
        return self.session

    def _ready(self) -> Session:
        s = self._unlocked()
        if self.needs_setup():
            raise Locked("set up first")
        return s

    # --- state (section 4.1) ---------------------------------------------------
    def state(self) -> dict:
        s = self.session
        out = {"api": API_VERSION, "version": __version__, "service": self.service,
               "unlocked": s is not None, "setup": self.needs_setup(),
               "connected": self.connected, "status": self.status, "identity": None,
               "node": None, "nodes": [],
               "inbox_ready": bool(self.runtime and self.runtime.inbox_ready),
               "ripening": None}
        if self.vault_path is not None:
            out["vault_exists"] = self.vault_path.exists()
        if s is not None and s.has_identity():
            ident = s.identity()
            out["identity"] = {"key": ident.key_text, "display": s.display_name(),
                               "label": s.identity_label(ident.key_text, s.display_name())}
            out["node"], out["nodes"] = s.node, list(s.nodes)
            t = s.ripening().t
            out["ripening"] = {"level": rp.level(t), "t": t, "next_at": rp.next_threshold(t),
                               "published": s.published_level(), "available": rp.available(),
                               "paused": bool(self.runtime and self.runtime.ripening_paused)}
        return out

    async def set_ripening_paused(self, paused: bool) -> dict:
        """Pause or resume ripening in the background (#337), for this run only.
        Answers the state's ``ripening``; every listener gets ``ripening-paused``."""
        self._ready()
        if self.runtime is None:
            raise Locked("not running")
        if paused:
            await self.runtime.pause_ripening()
        else:
            await self.runtime.resume_ripening()
        self._broadcast({"event": "ripening-paused", "paused": self.runtime.ripening_paused})
        return self.state()["ripening"]

    def about(self) -> dict:
        return about_text.as_dict(__version__)

    # --- groups (section 4.3) --------------------------------------------------
    def groups(self) -> dict:
        s = self._ready()
        rt = self.runtime
        ready = bool(rt and rt.inbox_ready)
        available = rt.available if rt and rt.available else None
        groups = [self._group(s, g) for g in s.subscribed_groups(available)
                  if g.group_id != s.my_inbox and not s.is_data_group(g.group_id)]
        people = [{"id": CONTACT + k, "key": k, "contact": bool(s.contact_name(k)),
                   "name": s.contact_name(k) or s.label_of(k),
                   "unread": s.unread_from(k, KIND_CHAT)} for k in s.chat_partners()]
        c = s.for_you_counts()
        tops: dict[str, list[dict]] = {}
        for g in sorted(groups, key=lambda g: g["label"]):
            tops.setdefault(g["hierarchy"], []).append(g)
        return {"groups": groups, "people": people,
                "hierarchies": [{"name": h, "tree": self._tree(h, gs)}
                                for h, gs in sorted(tops.items())],
                "inbox": {"id": s.my_inbox if ready else None,
                          "unread": s.unread_private_posts() if ready else 0},
                "for_you": {"id": FOR_YOU, "replies": c.replies, "mentions": c.mentions},
                "moderation": len(s.submissions()), "name_requests": self._name_requests(s)}

    @staticmethod
    def _group(s: Session, g: GroupInfo, also: set | frozenset = frozenset()) -> dict:
        """A GroupInfo dict with ``shown``: the name as people should see it, the
        fingerprint left out only where the hierarchy lists it (UN-RFC 0018)."""
        return {**g.to_dict(), "shown": s.group_label(g.group_id, also)}

    @staticmethod
    def _name_requests(s: Session) -> int:
        try:
            return len(naming.name_requests(s))
        except Exception:  # noqa: BLE001 - name lists not read yet
            return 0

    @staticmethod
    def _tree(top: str, groups: list[dict]) -> dict:
        """The TUI's group tree (client.grouptree): under ``alt.*`` names without
        ``alt.``, a shared part of a name as a folder. Groups by ID."""
        def walk(node) -> dict:
            return {"label": node.label, "path": node.path, "own": node.own_label,
                    "groups": [g["id"] for g in node.items],
                    "children": [walk(c) for c in node.children]}
        return walk(group_tree(top, [(g["label"], g) for g in groups]))

    def _head(self, s: Session, gid: str) -> dict:
        if gid.startswith(CONTACT):
            key = _key(gid[len(CONTACT):])
            g = GroupInfo(gid, "Private conversation. Only the two of you can read it.",
                          type="contact", view=s.view_of(gid), owner_view="chat",
                          kinds=(KIND_CHAT,), unread=s.unread_from(key, KIND_CHAT))
            return {**g.to_dict(), "label": s.contact_name(key) or s.label_of(key),
                    "hierarchy": "", "key": key, "contact": bool(s.contact_name(key)),
                    "may_post": True}
        if gid == FOR_YOU:
            c = s.for_you_counts()
            g = GroupInfo(gid, "Replies to your posts and posts that name you, from all your groups",
                          view="threads", replies=c.replies, mentions=c.mentions)
            return {**g.to_dict(), "label": "For you", "hierarchy": "", "may_post": False}
        if gid == s.my_inbox:
            g = s.group_info(gid)
            g.type = "inbox"
            return {**g.to_dict(), "label": "Private posts", "hierarchy": "", "may_post": False,
                    "description": "Only you can read these. Nodes see sealed envelopes."}
        if gid not in s.data["groups"] and gid not in s.data["subscribed"]:
            raise NotFound("no such group")
        data = s.manifest_data(gid)
        out = {**self._group(s, s.group_info(gid)), "may_post": s.may_post(gid),
               "rules": data.get("rules", ""), "rules_type": data.get("rules_type"),
               "rules_tree": markup.manifest_text(data.get("rules", ""), data.get("rules_type"))
               if data.get("rules") else [],
               "portals": [{"network": n, "source": src} for n, src in s.group_portals(gid)],
               "portal_warning": s.portal_warning(gid)}
        if out["owner"] or s.moderates(gid):
            out["roles"] = self._roles(s, gid)
        return out

    @staticmethod
    def _roles(s: Session, gid: str) -> dict:
        data = s.manifest_data(gid)

        def people(keys) -> list[dict]:
            return [{"key": k, "label": s.label_of(k)} for k in keys]
        out = {"moderators": people(data.get("moderators", [])),
               "posters": people(data.get("posters", [])),
               "banned": [{"key": k, "label": s.label_of(k), "reason": r}
                          for k, r in s.banned(gid)],
               "moderates": s.moderates(gid), "maintainer": LocalAPI._maintains(s, gid)}
        if s.group_entry(gid).get("owner") and data.get("type") == "closed":
            out["members"] = people(s.members(gid))
        return out

    @staticmethod
    def _maintains(s: Session, gid: str) -> bool:
        """You maintain a hierarchy this group is in: you may block people in all of it."""
        me = s.identity().key_text
        try:
            return any(h.maintainer == me for h in naming.governing(s, gid))
        except Exception:  # noqa: BLE001 - lists not read yet
            return False

    def group(self, gid: str) -> dict:
        s = self._ready()
        head = self._head(s, gid)
        if head["view"] == "chat" and not gid.startswith(CONTACT) and gid != FOR_YOU:
            # read as a chat: every line in the order it came (UN-RFC 0008 section 3.1)
            rows = [(m, 0) for m in s.visible(sorted(s.cache.get(gid, {}).values(),
                                                      key=lambda m: m.number))]
        else:
            rows = s.threads(gid)
        mine, patterns = s.my_message_ids(), s._mention_patterns()
        keys = {s.identity(n).key_text for n in s.data["identities"]}
        return {"group": head,
                "rows": [self._row(s, m, d, mine, patterns, keys) for m, d in rows]}

    @staticmethod
    def _row(s: Session, m: Message, depth: int, mine: set, patterns, keys: set) -> dict:
        if m.to_key:
            who, key = "You → " + s.label_of(m.to_key), m.to_key
        elif m.private and m.sender_key:
            who, key = s.identity_label(m.sender_key, m.from_name), m.sender_key
        else:
            who, key = s.identity_label(m.author_key, m.from_name), m.author_key
        d = m.to_dict()
        notice = None
        if s.is_notice(m) and m.mention_group and "@" in m.mention_group:
            name, fp = m.mention_group.rsplit("@", 1)
            notice = {"group": m.mention_group, "id": m.mention_of,
                      "label": s.group_label(m.mention_group), "ref": f"#{name}@{fp}",
                      "followed": m.mention_group in s.data["subscribed"]}
        return {"message": d, "depth": depth, "read": s.is_read(m),
                "mine": m.author_key in keys or bool(m.to_key),
                # the text as a safe tree, Markdown or plain (UN-RFC 0031): draw this,
                # never the text as HTML
                "tree": markup.body(d["text"], m.content_type, m.kind) if m.readable else [],
                "groups": [r.text for r in group_refs(f"{m.subject}\n{d['text']}")]
                if m.readable else [],
                "notice": notice,
                "for_me": s.for_me(m, mine, patterns), "who": who, "who_key": key,
                "contact": bool(key and s.contact_name(key)),
                "bot": not m.private and s.is_bot(m.author_key),     # UN-RFC 0030 section 6
                "may_edit": s.may_edit(m), "may_withdraw": s.may_cancel(m)}

    @staticmethod
    def _pool(s: Session, gid: str) -> list[Message]:
        if gid == s.my_inbox or gid.startswith(CONTACT):
            return s.private_messages()
        if gid == FOR_YOU:
            return [m for msgs in s.cache.values() for m in msgs.values()]
        return list(s.cache.get(gid, {}).values())

    def _find(self, s: Session, gid: str, message_id: str) -> Message:
        m = next((m for m in self._pool(s, gid) if m.message_id == message_id), None)
        if m is None:
            raise NotFound("that post is not here any more")
        return m

    def mark_read(self, gid: str, ids: list) -> dict:
        s = self._ready()
        wanted = {str(i) for i in list(ids)[:MAX_READ]}
        for m in self._pool(s, gid):
            if m.message_id in wanted:
                s.mark_read(m, save=False)
        s.save()
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    def set_view(self, gid: str, view) -> dict:
        if view not in ("threads", "chat", None):
            raise SessionError("view is threads, chat or null")
        self._ready().set_view(gid, view)
        return {"ok": True}

    def subscribe(self, gid: str, on: bool) -> dict:
        s = self._ready()
        s.subscribe(gid, on)
        if on:
            self.spawn(self._fetch(gid))
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    async def browse(self, pattern: str = "*") -> dict:
        s = self._ready()
        found = await s.list_groups(pattern or "*")
        avail = {g.group_id: g for g in found}
        return {"groups": [self._group(s, s.group_info(g.group_id, avail, counts=False))
                           for g in found]}

    def refresh(self) -> dict:
        self._ready()
        if self.runtime is not None:
            self.spawn(self.runtime.refresh())
        return {"ok": True}

    async def _fetch(self, gid: str) -> None:
        with contextlib.suppress(*NETWORK_ERRORS):
            await self.session.fetch_group(gid)

    def known_nodes(self) -> dict:
        s = self._ready()
        return {"nodes": [{"address": n.address, "name": n.name, "description": n.description,
                           "operator": n.operator} for n in s.known_nodes()]}

    async def group_ref(self, text: str) -> dict:
        """What a #group reference can mean (unseenet #172), followed groups first."""
        s = self._ready()
        refs = group_refs(text)
        if not refs:
            return {"groups": []}
        found = await s.find_group_ref(refs[0])
        also = {g.group_id for g in found}
        return {"groups": [{**self._group(s, s.group_info(g.group_id, {g.group_id: g},
                                                          counts=False), also),
                            "warning": naming.group_warning(s, g.group_id, also)}
                           for g in found]}

    # --- writing: jobs (sections 4.4, 4.5) --------------------------------------
    def _new_job(self, group: str, send, after=None) -> str:
        self._jobs += 1
        job = f"job{self._jobs}"
        self.spawn(self._run_job(job, group, send, after))
        return job

    async def _run_job(self, job: str, group: str, send, after) -> None:
        async with self._send:
            self._job = (job, group)
            self._job_event(job, group, "pow", fraction=0.0)
            try:
                msgid = await send()
            except (*NETWORK_ERRORS, ValueError) as exc:
                self._job_event(job, group, "failed", error=str(exc) or type(exc).__name__)
                return
            finally:
                self._job = None
        self._job_event(job, group, "sent", message_id=msgid)
        if after is not None:
            with contextlib.suppress(*NETWORK_ERRORS):
                await after(msgid)
        self._job_event(job, group, "reached", message_id=msgid)

    @staticmethod
    def _portals(s: Session, gid: str, accepted: bool) -> None:
        warning = s.portal_warning(gid)
        if warning and not accepted:
            raise SessionError(warning)
        if warning:
            s.accept_portals(gid)

    def post(self, gid: str, data: dict) -> dict:
        s = self._ready()
        kind = _kind(data)
        if gid.startswith(CONTACT):
            return self.private({**data, "key": gid[len(CONTACT):]})
        if gid == FOR_YOU or gid == s.my_inbox:
            raise SessionError("write to a person or a group")
        body = str(data.get("body", "")).strip("\n")
        subject = "" if kind == KIND_CHAT else str(data.get("subject", "")).strip()
        refs = [str(r) for r in data.get("references", []) or []][:MAX_REFERENCES]
        if not body.strip():
            raise SessionError("nothing to send")
        if kind not in s.group_kinds(gid):
            raise SessionError("this group takes " + ("posts with a subject only"
                                                       if kind == KIND_CHAT else "chat lines only"))
        if kind == KIND_POST and not subject:
            raise SessionError("a post needs a subject")
        self._portals(s, gid, bool(data.get("publish_outside_tor")))
        if kind == KIND_POST and data.get("signature", True):
            sig = s.signature()
            body = body.rstrip("\n") + ("\n-- \n" + sig if sig else "")
        notify = data.get("notify")
        keys: list[str] = []
        if (s.notice_settings()["send"] if notify is None else bool(notify)) and s.may_notify(gid):
            keys = [k for _, k in s.mentioned(subject, body)][:MAX_MENTION_NOTICES]

        async def send() -> str:
            if kind == KIND_CHAT and not refs:
                return await s.send_chat(gid, body)
            return await s.post(gid, subject, body, references=refs or None, kind=kind)

        async def after(msgid: str) -> None:
            if keys:            # for a post sent to the moderators, the core waits for approval
                self.spawn(s.send_mention_notices(gid, msgid, subject, kind, keys))
            await s.fetch_group(gid)
        return {"job": self._new_job(gid, send, after)}

    def private(self, data: dict) -> dict:
        s = self._ready()
        key = _key(data.get("key"))
        if key == s.identity().key_text:
            raise SessionError("that is your own key")
        kind = _kind(data)
        body = str(data.get("body", "")).strip("\n")
        if not body.strip():
            raise SessionError("nothing to send")
        subject = "" if kind == KIND_CHAT else str(data.get("subject", "")).strip()
        if kind == KIND_POST and not subject:
            raise SessionError("a post needs a subject")
        owner = crypto.key_from_text(key)
        inbox, refs = personal_inbox_id(owner), []
        reply_to = data.get("reply_to")
        if reply_to:
            msg = next((m for m in s.private_messages() if m.message_id == reply_to), None)
            if msg is not None:
                inbox = s.reply_target(msg) or inbox
                refs = msg.references + [msg.message_id]
        group = CONTACT + key if kind == KIND_CHAT else s.my_inbox

        async def send() -> str:
            if kind == KIND_CHAT and not refs and inbox == personal_inbox_id(owner):
                return await s.send_chat(CONTACT + key, body)
            return await s.send_private(inbox, subject, body, owner_key=owner,
                                        references=refs or None, kind=kind)

        async def after(msgid: str) -> None:
            s.emit(ev.GroupUpdated(group))
        return {"job": self._new_job(group, send, after)}

    def edit(self, gid: str, data: dict) -> dict:
        s = self._ready()
        m = self._find(s, gid, str(data.get("id", "")))
        if not s.may_edit(m):
            raise SessionError("you can only edit your own posts")
        body = str(data.get("body", "")).strip("\n")
        if not body.strip():
            raise SessionError("nothing to send")
        subject = str(data.get("subject", m.subject)).strip()

        async def send() -> str:
            return await s.edit(m, subject, body)

        async def after(msgid: str) -> None:
            await s.fetch_group(m.group)
        return {"job": self._new_job(gid, send, after)}

    async def withdraw(self, gid: str, message_id: str) -> dict:
        s = self._ready()
        m = self._find(s, gid, message_id)
        if not s.may_cancel(m):
            raise SessionError("you may not withdraw that post")
        await s.cancel(m)
        await self._fetch(m.group)
        s.emit(ev.GroupUpdated(m.group))
        return {"ok": True}

    def mentioned(self, gid: str, subject: str, body: str) -> dict:
        s = self._ready()
        if not s.may_notify(gid):
            return {"may": False, "names": [], "max": MAX_MENTION_NOTICES}
        return {"may": True, "names": [n for n, _ in s.mentioned(subject, body)],
                "max": MAX_MENTION_NOTICES}

    # --- people and safety (section 4.6) --------------------------------------
    def contact(self, data: dict) -> dict:
        s = self._ready()
        key = _key(data.get("key"))
        if data.get("remove"):
            s.remove_contact(key)
        else:
            s.add_contact(key, str(data.get("name", "")).strip())
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    def ignored(self) -> dict:
        s = self._ready()
        return {"ignored": [{"key": k, "label": label or s.label_of(k)}
                            for k, label in s.ignored()]}

    def ignore(self, data: dict) -> dict:
        s = self._ready()
        key = _key(data.get("key"))
        if data.get("on", True):
            s.ignore(key, str(data.get("label", "")))
        else:
            s.unignore(key)
        self._redraw_all(s)
        return {"ok": True}

    @staticmethod
    def _redraw_all(s: Session) -> None:
        s.emit(ev.GroupsChanged())
        for gid in list(s.data["subscribed"]):
            s.emit(ev.GroupUpdated(gid))

    async def report_targets(self, gid: str, message_id: str) -> dict:
        s = self._ready()
        m = self._find(s, gid, message_id)
        return {"targets": [{"i": i, "who": who} for i, (who, _, _) in
                            enumerate(await s.report_targets(m))]}

    async def report(self, gid: str, data: dict) -> dict:
        s = self._ready()
        m = self._find(s, gid, str(data.get("id", "")))
        chosen = {int(i) for i in data.get("targets", [])}
        targets = [t for i, t in enumerate(await s.report_targets(m)) if i in chosen]
        if not targets:
            raise SessionError("report to whom?")
        sent = await s.report(m, targets, str(data.get("note", "")).strip(),
                              anonymous=bool(data.get("anonymous")))
        return {"sent": sent}

    async def block(self, gid: str, data: dict) -> dict:
        s = self._ready()
        where = await naming.block(s, gid, _key(data.get("key")),
                                   str(data.get("reason", "")).strip())
        s.emit(ev.GroupUpdated(gid))
        return {"hierarchy": str(where)}

    # --- groups you run (section 4.7) -------------------------------------------
    async def create_group(self, data: dict) -> dict:
        s = self._ready()
        gtype = str(data.get("type", "open"))
        if gtype not in GROUP_TYPES:
            raise SessionError("type is open, moderated, channel or closed")
        name = str(data.get("name", "")).strip().lower()
        if not name:
            raise SessionError("a group needs a name")
        kinds = str(data.get("kinds", "both"))
        if kinds not in KINDS:
            raise SessionError("kinds is both, post or chat")
        view = data.get("view")
        gid = await s.create_group(
            name, gtype, title=str(data.get("title", "")).strip(),
            description=str(data.get("description", "")).strip(),
            view=view if view in ("threads", "chat") else None,
            low_latency=bool(data.get("fast")), kinds=KINDS[kinds])
        await self._fetch(gid)
        s.emit(ev.GroupsChanged())
        return {"id": gid}

    async def group_settings(self, gid: str, data: dict) -> dict:
        s = self._ready()
        unknown = set(data) - set(SETTINGS_FIELDS)
        if unknown:
            raise SessionError(f"{sorted(unknown)[0]} cannot be changed here")
        changes = dict(data)
        if "kinds" in changes:
            if changes["kinds"] not in KINDS:
                raise SessionError("kinds is both, post or chat")
            changes["kinds"] = KINDS[changes["kinds"]] or [KIND_CHAT, KIND_POST]
        await s.update_group(gid, **changes)
        s.emit(ev.GroupUpdated(gid))
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    async def remove_group(self, gid: str, data: dict) -> dict:
        s = self._ready()
        if data.get("confirm") != "remove":
            raise SessionError('give "confirm": "remove"')
        await s.remove_group(gid, str(data.get("reason", "")).strip())
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    async def invite(self, gid: str, data: dict) -> dict:
        s = self._ready()
        await s.invite(gid, _key(data.get("key")))
        s.emit(ev.GroupUpdated(gid))
        return {"ok": True}

    async def remove_member(self, gid: str, data: dict) -> dict:
        s = self._ready()
        epoch = await s.remove_member(gid, _key(data.get("key")))
        s.emit(ev.GroupUpdated(gid))
        return {"epoch": epoch}

    async def role(self, gid: str, data: dict) -> dict:
        s = self._ready()
        role = str(data.get("role", ""))
        if role not in ("moderators", "posters"):
            raise SessionError("role is moderators or posters")
        await s.set_role(gid, role, _key(data.get("key")), bool(data.get("on", True)))
        s.emit(ev.GroupUpdated(gid))
        return {"ok": True}

    async def ban(self, gid: str, data: dict) -> dict:
        s = self._ready()
        key = _key(data.get("key"))
        if data.get("on", True):
            await s.ban(gid, key, str(data.get("reason", "")).strip())
        else:
            await s.unban(gid, key)
        s.emit(ev.GroupUpdated(gid))
        return {"ok": True}

    async def moderation(self) -> dict:
        s = self._ready()
        with contextlib.suppress(*NETWORK_ERRORS):
            await s.fetch_group(s.my_inbox)
        out = []
        for m, art in s.submissions():
            key = art.get("Author-Key", "")
            out.append({"id": m.message_id, "group": art.group,
                        "group_label": s.group_label(art.group),
                        "subject": art.get("Subject", ""),
                        "who": s.identity_label(key, art.get("From", "")), "key": key,
                        "content_type": art.get("Content-Type", ""),
                        "body": "" if art.get("Encrypted") else art.body,
                        "tree": [] if art.get("Encrypted") else markup.body(
                            art.body, art.get("Content-Type", ""), message_kind(art)),
                        "date": m.date.isoformat() if m.date else None})
        return {"waiting": out}

    async def moderate(self, data: dict) -> dict:
        s = self._ready()
        found = next(((m, a) for m, a in s.submissions() if m.message_id == data.get("id")), None)
        if found is None:
            raise NotFound("that post is not waiting any more")
        m, art = found
        if data.get("approve"):
            await s.approve_submission(m, art)
            await self._fetch(art.group)
        else:
            await s.reject_submission(m, str(data.get("reason", "")).strip())
        s.emit(ev.GroupsChanged())
        return {"ok": True}

    # --- who you are (section 4.8) ---------------------------------------------
    async def profile(self, key: str | None = None) -> dict:
        s = self._ready()
        if not key or key == s.identity().key_text:
            return self._profile(s.identity().key_text, s.my_profile())
        p = await s.profile_of(_key(key))
        return self._profile(key, None if p is None else (p.raw or {"about": p.about}))

    @staticmethod
    def _profile(key: str, obj: dict | None) -> dict:
        tree = markup.manifest_text(obj.get("about", ""), obj.get("about_type")) \
            if obj and obj.get("about") else []
        return {"key": key, "profile": obj, "about_tree": tree}

    async def publish_profile(self, profile) -> dict:
        s = self._ready()
        if profile is not None and not isinstance(profile, dict):
            raise SessionError("a profile is an object or null")
        if self.service and isinstance(profile, dict):
            profile = {**profile, "bot": True}             # a program says so (UN-RFC 0030, 6)
        await s.publish_profile(profile)
        return self._profile(s.identity().key_text, s.my_profile())

    async def names(self) -> dict:
        s = self._ready()
        with contextlib.suppress(*NETWORK_ERRORS, asyncio.TimeoutError):
            await asyncio.wait_for(s.refresh_naming(), 60)
        me = s.identity().key_text
        mine = naming.my_names(s)
        primary = naming.preferred(s, me, mine).name if mine else None
        held = {c.name for c in mine}
        return {
            "key": me, "dns_value": nm.dns_record_value(me),
            "mine": [{"name": c.name, "text": naming.name_text(c.name), "kind": c.kind,
                      "expires": c.expires.isoformat(), "primary": c.name == primary}
                     for c in mine],
            "pending": [{"name": n, "action": a, "sent": when}
                        for n, a, when in naming.pending(s) if n not in held],
            "parents": naming.parents_i_hold(s),
            "given": [{"name": c.name, "key": c.key, "who": s.label_of(c.key),
                       "expires": c.expires.isoformat()} for c in naming.names_given(s)],
            "requests": [{"id": m.message_id, "name": d.get("name", ""), "key": d.get("key", ""),
                          "who": s.identity_label(d.get("key", ""), m.from_name)}
                         for m, d in naming.name_requests(s)],
        }

    async def name_action(self, data: dict) -> dict:
        """claim, renew, release, transfer, primary, ask, give, revoke, approve, refuse."""
        s, action = self._ready(), str(data.get("action", ""))
        name = str(data.get("name", "")).strip().lower().lstrip("@")
        if action in ("claim", "renew", "release", "transfer"):
            nm.check_name(name)
            to = None
            if action == "transfer":
                to = _key(data.get("to"))
                if to == s.identity().key_text:
                    raise SessionError("that is your own key")
            await naming.claim(s, name, action, to)
            text = f"Sent your {action} of @{name} to the registrar. It decides after about an hour."
        elif action == "primary":
            naming.set_primary(s, name)
            text = f"Your posts show {naming.name_text(name)}"
        elif action == "ask":
            await naming.request_subname(s, name)
            text = f"Asked for {name}. The answer comes to your private posts."
        elif action == "give":
            key = _key(data.get("key"))
            years = max(1, min(int(data.get("years", 1) or 1), 10))
            await naming.give_subname(s, name, key, timedelta(days=365 * years))
            text = f"{name} given to {s.label_of(key)}"
        elif action == "revoke":
            await naming.revoke_subname(s, name)
            text = f"{name} taken back"
        elif action in ("approve", "refuse"):
            await s.fetch_group(s.my_inbox)
            found = next(((m, d) for m, d in naming.name_requests(s)
                          if m.message_id == data.get("id")), None)
            if found is None:
                raise NotFound("that request is not waiting any more")
            await naming.answer_request(s, found[0], found[1], approve=action == "approve")
            text = "Given." if action == "approve" else "Said no."
        else:
            raise SessionError(f"unknown action {action!r}")
        return {"text": text}

    def settings(self) -> dict:
        s = self._ready()
        return {"signature": s.signature_template(), "signature_preview": s.signature(),
                "markdown": markup.is_markdown(s.text_type()), "notices": s.notice_settings(),
                "private_min_ripe": s.private_min_ripe(),
                "show_blocked": bool(s.data.get("show_blocked")), "hide_bots": s.hide_bots()}

    def set_settings(self, data: dict) -> dict:
        s = self._ready()
        unknown = set(data) - {"signature", "markdown", "notices", "private_min_ripe",
                               "show_blocked", "hide_bots"}
        if unknown:
            raise SessionError(f"unknown setting {sorted(unknown)[0]}")
        level = data.get("private_min_ripe")
        if level is not None and (isinstance(level, bool) or not isinstance(level, int)
                                  or not 0 <= level <= 4):
            raise SessionError("private_min_ripe is a level 0-4 or null")
        if "signature" in data:
            s.set_signature(str(data["signature"]))
        if "markdown" in data:
            s.set_markdown(bool(data["markdown"]))
        if "notices" in data:
            n = data["notices"] or {}
            s.set_notice_settings(send=None if "send" not in n else bool(n["send"]),
                                  receive=None if "receive" not in n else bool(n["receive"]))
        if "private_min_ripe" in data:
            s.set_private_min_ripe(level)
        if "show_blocked" in data:
            s.set_show_blocked(bool(data["show_blocked"]))
        if "hide_bots" in data:
            s.set_hide_bots(bool(data["hide_bots"]))
        self._redraw_all(s)
        return self.settings()

    # --- articles from a program (section 4.9) ----------------------------------
    def article(self, data: dict) -> dict:
        s = self._ready()
        gid = str(data.get("group", ""))
        kind = _kind(data)
        body = str(data.get("body", ""))
        subject = "" if kind == KIND_CHAT else str(data.get("subject", "")).strip()
        if not body.strip():
            raise SessionError("nothing to send")
        if kind == KIND_POST and not subject:
            raise SessionError("a post needs a subject")
        extra = []
        for pair in data.get("headers", []) or []:
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                raise SessionError("headers are [name, value] pairs")
            name, value = str(pair[0]), str(pair[1])
            if (not name.lower().startswith(PROGRAM_HEADERS) or "\n" in value or "\r" in value
                    or not name.replace("-", "").isalnum()):
                raise SessionError(f"a program may not set {name}")
            extra.append((name, value))
        refs = [str(r) for r in data.get("references", []) or []][:MAX_REFERENCES]
        self._portals(s, gid, bool(data.get("publish_outside_tor")))
        content_type = str(data["content_type"]) if data.get("content_type") else None
        from_name = str(data["from"]) if data.get("from") else None

        async def send() -> str:
            return await s.post(gid, subject, body, references=refs or None, kind=kind,
                                content_type=content_type, extra=extra, from_name=from_name)

        async def after(msgid: str) -> None:
            await s.fetch_group(gid)
        return {"job": self._new_job(gid, send, after)}

    async def manifest(self, gid: str, data: dict) -> dict:
        """A whole new manifest for a group this key owns (a gateway's, a bot's channel)."""
        s = self._ready()
        entry = s.data["groups"].get(gid, {})
        if not entry.get("owner"):
            raise SessionError("only the owner can change a group")
        old = s.manifest_data(gid)
        if not old:
            raise SessionError("the group's manifest has not been fetched yet")
        for fixed in FIXED_FIELDS:
            if fixed in data and data[fixed] != old.get(fixed):
                raise SessionError(f"{fixed} can never change (UN-RFC 0004, 4)")
        new = {**data, **{k: old[k] for k in FIXED_FIELDS if k in old}}
        new["serial"] = int(old.get("serial", 1)) + 1
        art = manifest_article(s.identity(), gid, new, await s.required_pow(None))
        await s.post_article(art)
        entry.update({"manifest": new, "title": new.get("title", "")})
        s.save()
        s.emit(ev.GroupUpdated(gid))
        return {"ok": True, "serial": new["serial"]}
