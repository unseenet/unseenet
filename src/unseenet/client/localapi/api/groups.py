"""Groups (UN-RFC 0046 section 4.3): the groups you follow, one group's posts, finding more.

Belongs here: the group list as a tree with roles and name requests, one group's
threads or chat with write permission per row (``group``), read marks and views,
subscribing, browsing a node's groups, refreshing, known nodes, and opening a
``#group@fp`` reference.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class Groups:
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
               "portal_warning": s.portal_warning(gid),
               # may you write here, and if not, why - before you write (#181, #320)
               "write": {"post": _perm(s.write_permission(gid, kind=KIND_POST)),
                         "chat": _perm(s.write_permission(gid, kind=KIND_CHAT))}}
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
               "moderates": s.moderates(gid), "maintainer": _a.LocalAPI._maintains(s, gid)}
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
        out = [self._row(s, m, d, mine, patterns, keys) for m, d in rows]
        if "write" in head:                     # a real group: may you answer each post?
            for row, (m, _) in zip(out, rows):
                row["reply"] = _perm(s.write_permission(gid, reply_to=m, kind=KIND_POST))
        return {"group": head, "rows": out}

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
        s = self._unlocked()            # also during setup: that is where a node is chosen
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
