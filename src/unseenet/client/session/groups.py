"""Groups: creating and changing them, moderation, portals, bans. Part of Session (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class GroupsMixin:
    # ------------------------------------------------------------------
    # groups
    # ------------------------------------------------------------------
    def group_entry(self, group_id: str) -> dict:
        return self.data["groups"].setdefault(group_id, {"type": None, "owner": False, "keys": {}})

    async def list_groups(self, pattern: str = "*", node: str | None = None) -> list[GroupInfo]:
        """Groups on one node, or on all your nodes (merged; unreachable ones skipped)."""
        targets = [node] if node else self.nodes
        results = await asyncio.gather(
            *(self._call(lambda c: c.multiline(f"LIST NEWSGROUPS {pattern}", 215), n)
              for n in targets), return_exceptions=True)
        failed = [r for r in results if isinstance(r, BaseException)]
        for r in failed:
            if not isinstance(r, (OSError, ConnectionError, SessionError, NNTPError,
                                  asyncio.IncompleteReadError)):
                raise r
        if failed and len(failed) == len(results):
            raise failed[0]
        self.unreachable = [n for n, r in zip(targets, results) if isinstance(r, BaseException)]
        out: dict[str, GroupInfo] = {}
        subscribed = set(self.data["subscribed"])
        for address, lines in zip(targets, results):
            if isinstance(lines, BaseException):
                continue
            for line in lines:
                gid, _, desc = line.partition("\t")
                try:
                    split_group_id(gid)
                except ValueError:
                    continue
                if gid in out:
                    out[gid].nodes.append(address)
                    continue
                entry = self.data["groups"].get(gid, {})
                if gid in subscribed and desc and entry.get("title") != desc:
                    self.group_entry(gid)["title"] = desc       # remembered for offline use
                out[gid] = GroupInfo(gid, desc, entry.get("type"), subscribed=gid in subscribed,
                                     nodes=[address])
        for g in out.values():           # the node it is read from first
            home = self.node_for(g.group_id)
            if home in g.nodes:
                g.nodes.remove(home)
                g.nodes.insert(0, home)
        return list(out.values())

    async def find_group_ref(self, ref: "GroupRef") -> list[GroupInfo]:
        """The groups a #reference (#172) can mean: from your nodes, plus groups you
        already know of. Groups you follow come first, then the one the name stands
        for on its own (endorsed or the only one, UN-RFC 0018), then the rest."""
        try:
            found = [g for g in await self.list_groups(f"{ref.name}@*") if ref.matches(g.group_id)]
        except (SessionError, OSError, ConnectionError, NNTPError, asyncio.IncompleteReadError):
            found = []
        have = {g.group_id for g in found}
        subscribed = set(self.data["subscribed"])
        for gid in [*self.data["subscribed"], *self.data["groups"]]:
            if gid not in have and ref.matches(gid):
                have.add(gid)
                found.append(GroupInfo(gid, self.data["groups"].get(gid, {}).get("title", ""),
                                       self.data["groups"].get(gid, {}).get("type"),
                                       subscribed=gid in subscribed))
        also = {g.group_id for g in found}
        return sorted(found, key=lambda g: (not g.subscribed,
                                            self.group_label(g.group_id, also) != ref.name,
                                            g.group_id))

    def subscribe(self, group_id: str, on: bool = True, node: str | None = None) -> None:
        split_group_id(group_id)
        subs = self.data["subscribed"]
        if on and node:
            self.pin_group(group_id, node)
        elif on and self.node:
            self.group_entry(group_id).setdefault("node", self.node)
        changed = (on and group_id not in subs) or (not on and group_id in subs)
        if on and group_id not in subs:
            subs.append(group_id)
        elif not on and group_id in subs:
            subs.remove(group_id)
        self.save()
        if changed:
            self.emit(ev.GroupsChanged())

    async def peek_group(self, group_id: str, node: str | None = None,
                         max_heads: int = 300) -> tuple[dict, int]:
        """(manifest, number of posts) of a group you may not follow, for browsing.

        Reads only headers, and the manifest articles themselves; the manifest must be
        signed by the owner named in the group ID. Nothing is cached or subscribed.
        """
        from ...core.groups import Manifest

        async def run(c: Client) -> tuple[dict, int]:
            count, low, high = await c.group(group_id)
            best: dict = {}
            for n in range(low, min(high, low + max_heads - 1) + 1):
                try:
                    head = await c.multiline(f"HEAD {n}", 221)
                except NNTPError:
                    continue
                if not any(h.lower().replace(" ", "") == "control:manifest" for h in head):
                    continue
                raw = await c.article(str(n))
                try:
                    m = Manifest.from_article(Article.from_bytes(raw))
                except (ArticleError, ValueError, TypeError):
                    continue
                if m.group_id == group_id and m.serial >= int(best.get("serial", 0)):
                    best = dict(m.raw)
            return best, count

        cached = self.manifest_data(group_id)
        data, count = await self._call(run, node or self.node_for(group_id))
        return (cached if int(cached.get("serial", 0)) > int(data.get("serial", 0)) else data), count

    def subscribe_starter_groups(self) -> bool:
        """Subscribe to the project's groups once per vault (a new client has
        something to read). Groups unsubscribed later are not added again."""
        if self.data.get("starter_groups") or not self.node:
            return False
        from ...known_nodes import STARTER_GROUPS
        for gid in STARTER_GROUPS:
            if gid not in self.data["subscribed"]:
                self.data["subscribed"].append(gid)
                self.group_entry(gid).setdefault("node", self.node)
        self.data["starter_groups"] = True
        self.save()
        return True

    async def create_group(self, name: str, gtype: str, title: str = "", description: str = "",
                           min_pow: int = _s.DEFAULT_POW, local: bool = False,
                           retention_days: int | None = None, rules: str = "",
                           view: str | None = None, low_latency: bool = False,
                           kinds: list[str] | None = None, node: str | None = None,
                           comments: str | None = None, comment_days: int | None = None,
                           rules_type: str | None = None, moderators=(), posters=(),
                           extra: dict | None = None) -> str:
        """``moderators``/``posters``: keys as text; ``extra``: attachments, max_pins,
        max_pages, home (see groups.EXTRA_FIELDS)."""
        owner = self.identity()
        node = node or self.node
        self.mark_in_use()               # making a group is using the identity (#270)
        if retention_days is None:
            retention_days = 30 if gtype == "inbox" else 90
        art = make_manifest(owner, name, gtype, title=title, description=description,
                            min_pow=min_pow, local=local, retention_days=retention_days,
                            rules=rules, view=view, low_latency=low_latency, kinds=kinds,
                            rules_type=rules_type, moderators=list(moderators),
                            posters=list(posters) if gtype == "channel" else (),
                            comments=comments if gtype == "channel" else None,
                            comment_days=comment_days if gtype == "channel" else None,
                            extra=extra,
                            pow_bits=await self.required_pow(None, node=node))
        await self._post_article(art, node)
        entry = {"type": gtype, "owner": True, "keys": {}, "manifest": json.loads(art.body),
                 "owner_key": owner.key_text, "node": node}
        if gtype == "closed":
            keys = crypto.GroupKeys.generate()
            await self._post_article(make_key_update(
                owner, art.group, 1, keys, [],
                pow_bits=await self.required_pow(art.group, min_pow, node=node)), node)
            entry["keys"]["1"] = keys.secret.hex()
        self.data["groups"][art.group] = entry
        self.subscribe(art.group)
        return art.group

    def write_permission(self, group_id: str, reply_to: "Message | None" = None,
                         kind: str | None = KIND_POST, now: datetime | None = None
                         ) -> "Permission":
        """Whether you may write here, and if not, why - to tell people *before* they
        write (#181). Checks, from the cached manifest: the kinds a group takes
        (UN-RFC 0028), the ban list (0004 section 5.1) and maintainers' blocks (0018),
        type and posters, closed-group membership, and comments in channels with
        their ``comment_days`` (0030). ``reply_to``: the post you would answer;
        ``kind`` None: any kind. An unknown group is allowed: the node has the last
        word, and this only spares surprises."""
        if group_id == self.my_inbox:
            return Permission(False, "Nobody posts to their own inbox - write to a contact",
                              "own_inbox")
        entry = self.data["groups"].get(group_id, {})
        data = entry.get("manifest") or {}
        gtype = data.get("type") or entry.get("type")
        if not gtype:
            return Permission(True)
        if kind is not None and kind not in self.group_kinds(group_id):
            return Permission(False, "This group takes chat lines only" if kind == KIND_POST
                              else "This group takes posts with a subject only - n writes one",
                              "kind")
        if gtype == "inbox":
            return Permission(True)
        me = self.identity().key_text
        for key, reason in self.banned(group_id):
            if key == me:
                return Permission(False, "You are banned from this group"
                                  + (f": {reason}" if reason else ""), "banned")
        blocked = self.hierarchy_blocks(group_id).get(me)
        if blocked:
            hierarchy, reason = blocked
            return Permission(False, f"The maintainers of {hierarchy} block you"
                              + (f": {reason}" if reason else ""), "blocked")
        if entry.get("owner") or data.get("owner") == me or me in data.get("moderators", []):
            return Permission(True)
        if gtype == "closed":
            return (Permission(True) if entry.get("keys") else
                    Permission(False, "You are not a member of this closed group", "not_member"))
        if gtype != "channel":
            return Permission(True)          # open, moderated (goes to approval)
        if me in data.get("posters", []):
            return Permission(True)
        if data.get("comments") != "open":
            return Permission(False, "Channel: only the owner and posters write", "channel")
        if reply_to is None:
            return Permission(False, "Channel: only the owner and posters start threads - "
                              "you may comment on one", "channel_thread")
        days = data.get("comment_days")
        root = self.find_message(group_id, reply_to.thread_root)
        if isinstance(days, int) and root is not None and root.date is not None:
            if (now or datetime.now(timezone.utc)) > root.date + timedelta(days=days):
                return Permission(False, "Comments on this thread have closed",
                                  "comments_closed")
        return Permission(True)

    def find_message(self, group_id: str, message_id: str) -> "Message | None":
        """A message of a group this client has read, by Message-ID."""
        for m in self.cache.get(group_id, {}).values():
            if m.message_id == message_id:
                return m
        return None

    def may_post(self, group_id: str) -> bool:
        """Whether a new post of yours would be accepted here (any kind)."""
        return self.write_permission(group_id, kind=None).allowed

    def may_reply(self, group_id: str, reply_to: "Message | None" = None) -> bool:
        """Whether a reply of yours would be accepted, comments in channels included."""
        if reply_to is None:                 # without the post: is a comment possible at all
            data = self.manifest_data(group_id)
            if data.get("type") == "channel" and data.get("comments") == "open":
                p = self.write_permission(group_id, kind=None)
                return p.allowed or p.code == "channel_thread"
        return self.write_permission(group_id, reply_to, kind=None).allowed

    # --- moderation (UN-RFC 0004 section 5, UN-RFC 0009 section 3) ---
    def moderates(self, group_id: str) -> bool:
        me = self.identity().key_text
        data = self.manifest_data(group_id)
        return bool(self.data["groups"].get(group_id, {}).get("owner")) \
            or data.get("owner") == me or me in data.get("moderators", [])

    def submission_targets(self, group_id: str) -> list[tuple[str, bytes | None]]:
        """(inbox, owner key or None) to send a submission to (UN-RFC 0009, 3)."""
        data = self.manifest_data(group_id)
        if data.get("submissions"):
            return [(data["submissions"], None)]
        keys = [data["owner"]] if data.get("owner") else []
        keys += [k for k in data.get("moderators", []) if k not in keys]
        return [(personal_inbox_id(crypto.key_from_text(k)), crypto.key_from_text(k)) for k in keys]

    async def _submit(self, group_id: str, subject: str, build) -> str:
        self.mark_in_use()               # writing anything is using the identity (#270)
        bits = await self.required_pow(group_id)
        art = await self._compute(lambda: build(bits))
        raw = art.to_bytes().decode("utf-8")
        delivered, errors = 0, []
        for inbox, owner_key in self.submission_targets(group_id):
            try:
                await self.send_private(inbox, f"Submission to {short_group_id(group_id)}: {subject}",
                                        raw, owner_key=owner_key, content_type=SUBMISSION_TYPE,
                                        remember=False)
                delivered += 1
            except (SessionError, OSError, ConnectionError) as exc:
                errors.append(str(exc))
        if not delivered:
            raise SessionError("could not reach the moderators: " + "; ".join(errors or ["no inbox"]))
        entry = self.group_entry(group_id)
        entry.setdefault("submitted", []).append(art.message_id)
        del entry["submitted"][:-200]
        self.data["read"].setdefault(group_id, []).append(art.message_id)
        self.save()
        return art.message_id

    def was_submitted(self, group_id: str, message_id: str) -> bool:
        return message_id in self.group_entry(group_id).get("submitted", [])

    def submissions(self) -> list[tuple["Message", Article]]:
        """Submissions waiting in your inbox for groups you moderate, oldest first."""
        done = set(self.data.get("moderation_done", []))
        out = []
        for m in self.private_messages():
            if not m.content_type.startswith(SUBMISSION_TYPE) or m.message_id in done:
                continue
            try:
                raw = m.body.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
                art = Article.from_bytes(raw)
                validate_structure(art, raw_size=len(raw))
            except (ArticleError, ValueError, UnicodeError):
                continue
            gid = art.group
            data = self.manifest_data(gid)
            if data.get("type") != "moderated" or not self.moderates(gid) \
                    or self.is_banned(gid, art["Author-Key"]):
                continue
            if any(x.message_id == art.message_id for x in self.cache.get(gid, {}).values()):
                continue                    # another moderator approved it already
            out.append((m, art))
        return out

    def _moderation_done(self, msg: "Message") -> None:
        done = self.data.setdefault("moderation_done", [])
        done.append(msg.message_id)
        del done[:-500]
        self.save()

    async def approve_submission(self, msg: "Message", art: Article) -> None:
        """Approve and post a submitted article; its Message-ID stays the same."""
        from ...core.groups import approve
        if not self.moderates(art.group):
            raise SessionError("you do not moderate this group")
        approve(art, self.identity())
        try:
            await self._post_article(art)
        except SessionError as exc:
            if "duplicate" not in str(exc).lower():
                raise                       # a duplicate: someone else approved it first
        self._queue_notices(self.notice_bundle(art))     # UN-RFC 0032 section 4.3
        self._moderation_done(msg)

    async def reject_submission(self, msg: "Message", reason: str = "") -> None:
        if reason.strip() and (msg.reply_inbox or msg.sender_key):
            target = self.reply_target(msg)
            if target:
                await self.send_private(target, "Not approved: " + msg.subject.split(": ", 1)[-1],
                                        reason.strip() + "\n", references=[msg.message_id])
        self._moderation_done(msg)

    def is_data_group(self, group_id: str) -> bool:
        """A group for programs, not people (UN-RFC 0008 section 3.1.1)."""
        from ...known_nodes import DATA_GROUPS
        return group_id in DATA_GROUPS or self.manifest_data(group_id).get("view") == "data"

    def manifest_data(self, group_id: str) -> dict:
        """The newest manifest seen for a group ({} if none yet)."""
        return dict(self.data["groups"].get(group_id, {}).get("manifest", {}))

    # --- portals (UN-RFC 0023 section 3.5) ---
    def group_portals(self, group_id: str) -> list[tuple[str, str]]:
        """(network, source) of the group's portals: where its posts are also published."""
        from ...core import portals
        return portals.portals(self.manifest_data(group_id))

    def portal_warning(self, group_id: str) -> str | None:
        """The warning to show before posting, or None if there are no portals or the
        user has accepted this set of them. A new or changed portal asks again."""
        from ...core import portals
        found = self.group_portals(group_id)
        if not found:
            return None
        if self.data["groups"].get(group_id, {}).get("portals_ok") == portals.fingerprint(found):
            return None
        name = self.manifest_data(group_id).get("name") or group_id.rpartition("@")[0]
        return portals.warning(name, found)

    def accept_portals(self, group_id: str) -> None:
        from ...core import portals
        self.group_entry(group_id)["portals_ok"] = portals.fingerprint(self.group_portals(group_id))
        self.save()

    def text_type(self) -> str:
        """The Content-Type your posts get: Markdown, unless you turned it off (UN-RFC 0031)."""
        from ...core.markup import MARKDOWN_TYPE, PLAIN_TYPE
        return PLAIN_TYPE if self.data.get("plain_text") else MARKDOWN_TYPE

    def set_markdown(self, on: bool) -> None:
        self.data["plain_text"] = not on
        self.save()

    def group_kinds(self, group_id: str) -> tuple[str, ...]:
        """What a group takes: chat lines, posts with a subject, or both (UN-RFC 0028, 4.1)."""
        data = self.manifest_data(group_id)
        if data.get("type") == "inbox" or group_id == self.my_inbox:
            return (KIND_CHAT, KIND_POST)
        kinds = data.get("kinds")
        if isinstance(kinds, list) and kinds and all(k in (KIND_CHAT, KIND_POST) for k in kinds):
            return tuple(kinds)
        return (KIND_CHAT, KIND_POST)

    async def update_group(self, group_id: str, **changes) -> dict:
        """Publish a new manifest with a higher serial (owner only).

        Allowed changes: title, description, rules, rules_type (UN-RFC 0014 2.1), view,
        kinds, low_latency, min_pow, retention_days. Type, owner and locality can never change (UN-RFC 0004, 4).
        """
        entry = self.data["groups"].get(group_id, {})
        if not entry.get("owner"):
            raise SessionError("only the owner can change a group")
        data = self.manifest_data(group_id)
        if not data:
            raise SessionError("the group's manifest has not been fetched yet")
        allowed = {"title", "description", "rules", "rules_type", "view", "low_latency", "min_pow",
                   "retention_days", "banned", "moderators", "posters", "kinds",
                   "comments", "comment_days", *EXTRA_FIELDS}
        if ("comments" in changes or "comment_days" in changes) and data.get("type") != "channel":
            raise SessionError("only channels take comments")
        if changes.get("comments") == "none":
            changes["comments"] = None            # the default is left out (UN-RFC 0030)
        if "kinds" in changes and changes["kinds"] is not None:
            kinds = list(dict.fromkeys(changes["kinds"]))
            if not kinds or any(k not in (KIND_CHAT, KIND_POST) for k in kinds):
                raise SessionError('kinds must be "chat", "post" or both')
            # both is the default and is left out of the manifest (UN-RFC 0028, 4.1)
            changes["kinds"] = None if set(kinds) == {KIND_CHAT, KIND_POST} else kinds
        for key, value in changes.items():
            if key not in allowed:
                raise SessionError(f"{key} cannot be changed")
            if value in (None, "", False, []) and key in ("title", "description", "rules",
                                                         "rules_type",
                                                         "low_latency", "banned", "moderators",
                                                         "posters", "kinds", "comments",
                                                         "comment_days", *EXTRA_FIELDS):
                data.pop(key, None)
            else:
                data[key] = value
        if len(data.get("rules", "")) > MAX_RULES:
            raise SessionError(f"rules are limited to {MAX_RULES} characters")
        if not data.get("rules"):
            data.pop("rules_type", None)          # no text, no type
        if data.get("view", "threads") not in VIEWS:
            raise SessionError("view must be one of " + ", ".join(VIEWS))
        try:
            _comments(data)
            check_extra_fields(data)
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        data["serial"] = int(data.get("serial", 1)) + 1
        art = manifest_article(self.identity(), group_id, data, await self.required_pow(None))
        await self._post_article(art)
        entry.update({"manifest": data, "title": data.get("title", "")})
        self.save()
        return data

    # --- bans (UN-RFC 0004, section 5.1) ---
    def banned(self, group_id: str) -> list[tuple[str, str]]:
        """(key, reason) of the keys the group's current manifest bans."""
        return [(b.get("key", ""), b.get("reason", ""))
                for b in self.manifest_data(group_id).get("banned", []) if isinstance(b, dict)]

    def is_banned(self, group_id: str, key_text: str | None) -> bool:
        return bool(key_text) and any(k == key_text for k, _ in self.banned(group_id))

    async def ban(self, group_id: str, key_text: str, reason: str = "") -> None:
        """Owner: ban a key from posting in the group (a new manifest)."""
        crypto.key_from_text(key_text)
        if key_text == self.identity().key_text:
            raise SessionError("you cannot ban yourself")
        if len(reason) > 200:
            raise SessionError("a reason is at most 200 characters")
        current = [b for b in self.manifest_data(group_id).get("banned", [])
                   if isinstance(b, dict) and b.get("key") != key_text]
        entry = {"key": key_text,
                 "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if reason.strip():
            entry["reason"] = reason.strip()
        await self.update_group(group_id, banned=current + [entry])

    async def unban(self, group_id: str, key_text: str) -> None:
        current = [b for b in self.manifest_data(group_id).get("banned", [])
                   if isinstance(b, dict) and b.get("key") != key_text]
        await self.update_group(group_id, banned=current)

    def rules_unseen(self, group_id: str) -> bool:
        """True if the group has rules the reader has not seen in this version."""
        data = self.manifest_data(group_id)
        if not data.get("rules"):
            return False
        return self.data.setdefault("rules_seen", {}).get(group_id, 0) < int(data.get("serial", 1))

    def mark_rules_seen(self, group_id: str) -> None:
        self.data.setdefault("rules_seen", {})[group_id] = int(self.manifest_data(group_id).get("serial", 1))
        self.save()

    async def required_pow(self, group_id: str | None, group_min: int | None = None,
                           node: str | None = None) -> int:
        """Postage to attach: max(node minimum, group minimum) - UN-RFC 0008 section 4."""
        async def node_min(c: Client) -> tuple[int, bool]:
            value = c.capability("UNSEENET-MINPOW")
            ripening = c.capability("UNSEENET-MINRIPE") is not None
            return (int(value) if value and value.strip().isdigit() else _s.DEFAULT_POW), ripening
        try:
            node_pow, ripening = await self._call(node_min, node or self.node_for(group_id))
        except (OSError, ConnectionError, SessionError):
            node_pow, ripening = _s.DEFAULT_POW, True
        if group_min is None and group_id:
            manifest = self.manifest_data(group_id)
            # A group joined before manifests were kept has none cached yet; the
            # network default is the safe guess (the node will say if it wants more).
            group_min = int(manifest.get("min_pow", 0)) if manifest else _s.DEFAULT_POW
        # UN-RFC 0025 section 5: the key's level adds to it or takes from it. A sealed
        # post to someone's inbox is signed by a one-time key: it pays as unripe (3.5).
        sealed = bool(group_id) and group_id.split("@", 1)[0] == INBOX_NAME \
            and group_id != self.my_inbox
        if not ripening:                         # a node from before UN-RFC 0025
            return max(node_pow, group_min or 0)
        lv = None if sealed or not self.has_identity() else self.published_level()
        return rp.required_pow(node_pow, group_min or 0, lv, allow_unripe=True)

    async def _post_with_postage(self, group_id: str, build) -> Article:
        """Build with ``build(bits)`` and post; if the node asks for more postage
        ("need N bits"), rebuild once with N and post again. Returns the posted article."""
        bits = await self.required_pow(group_id)
        art = await self._compute(lambda: build(bits))
        try:
            await self._post_article(art)
            return art
        except SessionError as exc:
            m = re.search(r"need (\d+) bits", str(exc))
            if not m or int(m.group(1)) <= bits or int(m.group(1)) > 28:
                raise
            need = int(m.group(1))
        self.say(f"Node wants {need} bits of postage, computing again ...")
        art = await self._compute(lambda: build(need))
        await self._post_article(art)
        entry = self.data["groups"].get(group_id)
        if entry is not None:                      # remember it for next time
            entry.setdefault("manifest", {})
            if int(entry["manifest"].get("min_pow", 0)) < need:
                entry["manifest"]["min_pow"] = need
        return art

    async def remove_group(self, group_id: str, reason: str = "") -> None:
        """UN-RFC 0013: remove a group you own from the whole network. Final."""
        entry = self.data["groups"].get(group_id, {})
        if not entry.get("owner"):
            raise SessionError("only the owner can remove a group")
        if group_id == self.my_inbox:
            raise SessionError("your personal inbox cannot be removed")
        art = new_article(group_id, None, reason or "Removed by its owner.\n",
                          extra=[("Control", "rmgroup")])
        bits = await self.required_pow(None)
        await self._compute(lambda: art.finalize(self.identity(), bits))
        await self._post_article(art)
        self.forget_group(group_id)

    def forget_group(self, group_id: str) -> None:
        """Unsubscribe and delete everything stored locally about a group."""
        if group_id in self.data["subscribed"]:
            self.data["subscribed"].remove(group_id)
        for store in (self.data["groups"], self.data["read"], self.cache, self._raw, self._high):
            store.pop(group_id, None)
        self.save()
        self.save_offline()
        self.emit(ev.GroupsChanged())

    async def invite(self, group_id: str, member_key: str) -> None:
        entry = self.data["groups"].get(group_id)
        if not entry or not entry.get("owner") or entry.get("type") != "closed":
            raise SessionError("you can only invite to closed groups you own")
        epoch = max(int(e) for e in entry["keys"])
        keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))
        art = make_key_update(self.identity(), group_id, epoch, keys,
                              [crypto.key_from_text(member_key)], grant_only=True,
                              pow_bits=await self.required_pow(group_id))
        await self._post_article(art)
        members = entry.setdefault("members", [])
        if member_key not in members:
            members.append(member_key)
        self.save()

    def members(self, group_id: str) -> list[str]:
        """Owner: the keys you invited to a closed group (envelopes do not say whom
        they are for, so this record is the list). Members invited from another
        device, or before this was recorded, are missing."""
        return list(self.data["groups"].get(group_id, {}).get("members", []))

    async def remove_member(self, group_id: str, member_key: str) -> int:
        """Owner: start a new epoch without the member (UN-RFC 0004, 6.1-6.2).
        The others get the new key; the removed member keeps what they read.
        Returns the new epoch."""
        entry = self.data["groups"].get(group_id)
        if not entry or not entry.get("owner") or entry.get("type") != "closed":
            raise SessionError("you can only remove members from closed groups you own")
        keep = [k for k in entry.get("members", []) if k != member_key]
        epoch = max(int(e) for e in entry["keys"]) + 1
        keys = crypto.GroupKeys.generate()
        art = make_key_update(self.identity(), group_id, epoch, keys,
                              [crypto.key_from_text(k) for k in keep], closes_previous=True,
                              pow_bits=await self.required_pow(group_id))
        await self._post_article(art)
        entry["keys"][str(epoch)] = keys.secret.hex()
        entry["members"] = keep
        self.save()
        return epoch

    async def set_role(self, group_id: str, role: str, key_text: str, on: bool = True) -> None:
        """Owner: add or remove a moderator or a poster (UN-RFC 0004, 3.1 and 5)."""
        if role not in ("moderators", "posters"):
            raise SessionError(f"unknown role {role}")
        crypto.key_from_text(key_text)
        if role == "posters" and self.group_entry(group_id).get("type") != "channel":
            raise SessionError("posters are for channels; other groups have moderators")
        current = [k for k in self.manifest_data(group_id).get(role, []) if k != key_text]
        if on:
            current.append(key_text)
        await self.update_group(group_id, **{role: current})
