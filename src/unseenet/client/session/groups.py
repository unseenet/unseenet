"""Groups: what they are, and the owner's and moderators' side of them.

Belongs here: a group's manifest (fetching and checking it, ``manifest_data``, UN-RFC
0004), creating and changing groups (``create_group``, ``update_group`` with the fields
of 0004, 0014, 0027-0035), may you write here (``write_permission``, #181), moderated
groups and submissions (0004 section 5, 0009 section 3), roles, bans and members,
portals to other networks (0023), removing a group (0013), and finding groups
(``filter_groups``, ``find_group_ref``).

Not here: following and reading groups (reading.py), posting to them (posting.py).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class GroupsMixin:
    def filter_groups(self, groups: list["GroupInfo"], query: str,
                      known: dict | None = None) -> list["GroupInfo"]:
        """The groups that match a search (#13, ``client.groupfilter``), locally.
        ``known``: manifest data fetched for groups you do not follow."""
        from .. import groupfilter
        f = groupfilter.parse(query)
        if not f:
            return list(groups)
        mine, known = self.my_fingerprints(), known or {}
        return [g for g in groups if groupfilter.matches(
            f, g.group_id, description=g.description, gtype=g.type,
            data=known.get(g.group_id) or self.manifest_data(g.group_id),
            subscribed=g.subscribed, my_fingerprints=mine)]

    async def group_manifests(self, groups: list["GroupInfo"], known: dict) -> int:
        """Fetch the manifests of listed groups whose type is not known yet, from the
        node that carries each, in a few requests (UN-RFC 0041), into ``known``
        (Group ID -> manifest data) and each GroupInfo's type. Asking for all of them
        tells a node nothing about what you search for. Returns how many were asked."""
        todo: dict[str | None, list[GroupInfo]] = {}
        for g in groups:
            if g.type or g.group_id in known or self.manifest_data(g.group_id):
                continue
            todo.setdefault(g.nodes[0] if g.nodes else None, []).append(g)
        asked = 0
        for node, items in todo.items():
            found = await self.fetch_manifests([g.group_id for g in items], node,
                                               fallback=False)
            for g in items:
                m = found.get(g.group_id)
                known[g.group_id] = dict(m.raw) if m else {}
                if m:
                    g.type = m.type
            asked += len(items)
        return asked

    # ------------------------------------------------------------------
    # groups
    # ------------------------------------------------------------------
    def group_entry(self, group_id: str) -> dict:
        """The vault's entry for a group (created empty if missing): type, ownership,
        keys of closed groups, the node it is read on, and what the client remembers."""
        return self.data["groups"].setdefault(group_id, {"type": None, "owner": False, "keys": {}})

    async def list_groups(self, pattern: str = "*", node: str | None = None,
                          budget: float | None = None) -> list[GroupInfo]:
        """Groups on one node, or on all your nodes (merged; unreachable ones skipped).

        ``budget``: seconds to wait for each node's first answer (#704). A node slower
        than that does not hold up the others: what the rest list comes back at once,
        the slow one is in ``slow`` - its answer still awaited in the background (a
        task the caller can wait on, ``late_answers``) - and its groups come with the
        next listing. Without a budget every node is waited for, as before."""
        targets = [node] if node else self.nodes
        def ask(n):                             # a node still slow: wait on its first answer
            late = self.slow.get(n)
            if late is not None and not late.done():
                return late
            return asyncio.ensure_future(self._call(
                lambda c: c.multiline(f"LIST NEWSGROUPS {pattern}", 215), n))
        tasks = [ask(n) for n in targets]
        if budget is not None and tasks:
            await asyncio.wait(tasks, timeout=budget)
        else:
            await asyncio.gather(*tasks, return_exceptions=True)
        results: list = []
        for n, t in zip(targets, tasks):
            if not t.done():                    # still asking: carry on without it (#704)
                if n not in self.slow:
                    self.slow[n] = t
                    t.add_done_callback(lambda _t, n=n: self._answered_late(n, _t))
                    self.say(f"{self.node_label(n)} is not answering yet - the others are shown")
                results.append(asyncio.TimeoutError(f"{n} is not answering yet"))
            elif self.slow.get(n) is t:         # the slow one's first answer, come now:
                results.append(asyncio.TimeoutError(f"{n} answered late"))   # listed next time
            else:
                results.append(t.exception() or t.result())
        failed = [r for r in results if isinstance(r, BaseException)]
        for r in failed:
            if not isinstance(r, (OSError, ConnectionError, SessionError, NNTPError,
                                  asyncio.IncompleteReadError)):
                raise r
        if failed and len(failed) == len(results):
            raise failed[0]
        self.unreachable = [n for n, r in zip(targets, results)
                            if isinstance(r, BaseException) and n not in self.slow]
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

    def _answered_late(self, node: str, task: asyncio.Task) -> None:
        """A slow node's answer came (or its failure): no longer slow (#704). Its
        groups come with the next listing; NodeState tells the clients."""
        if self.slow.get(node) is task:
            del self.slow[node]
        failed = task.cancelled() or task.exception() is not None
        if failed and node not in self.unreachable:
            self.unreachable.append(node)
        self.emit(ev.NodeState(node, not failed, None if not failed else "did not answer"))

    def late_answers(self) -> list[asyncio.Task]:
        """The listings still awaited from slow nodes (#704), to act when they come."""
        return list(self.slow.values())

    def is_slow(self, node: str | None) -> bool:
        """Whether a node was asked and has not answered yet (#704)."""
        return node in self.slow

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

    async def create_group(self, name: str, gtype: str, title: str = "", description: str = "",
                           min_pow: int = _s.DEFAULT_POW, local: bool = False,
                           retention_days: int | None = None, charter: str = "",
                           view: str | None = None, low_latency: bool = False,
                           kinds: list[str] | None = None, node: str | None = None,
                           comments: str | None = None, comment_days: int | None = None,
                           charter_type: str | None = None, moderators=(), posters=(),
                           extra: dict | None = None) -> str:
        """``charter``: the group's charter, what it is for and asks of those who write
        (UN-RFC 0014), with ``charter_type`` for Markdown; ``moderators``/``posters``: keys
        as text; ``extra``: attachments, max_pins, max_pages, home (see groups.EXTRA_FIELDS)."""
        from ...core import group_emoji as _ge
        if _ge.is_emoji_name(name):      # reserved for a group's emoji (UN-RFC 0056 3.1)
            raise SessionError("a name ending in .emoji is kept for a group's emoji")
        owner = self.identity()
        if node is None:                 # the default, or the next node that answers (#605)
            node = await self._reachable(None)
            if node is not None and node != self.node:
                self.say(f"{self.node_label(self.node)} does not answer - the group is "
                         f"made on {self.node_label(node)}")
        self.mark_in_use()               # making a group is using the identity (#270)
        if retention_days is None:
            retention_days = 30 if gtype == "inbox" else 90
        if gtype == "inbox" and "attachments" not in (extra or {}):
            from ...core import blobs as bl          # an inbox takes pictures and PDFs (#637)
            extra = {**(extra or {}), "attachments": bl.PICTURES_AND_PDF}
        art = make_manifest(owner, name, gtype, title=title, description=description,
                            min_pow=min_pow, local=local, retention_days=retention_days,
                            charter=charter, view=view, low_latency=low_latency, kinds=kinds,
                            charter_type=charter_type, moderators=list(moderators),
                            posters=list(posters) if gtype == "channel" else (),
                            comments=comments if gtype == "channel" else None,
                            comment_days=comment_days if gtype in ("channel", "open", "moderated",
                                                                   "closed") and not local else None,
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
        if gtype in ("open", "moderated", "closed"):        # replies too (UN-RFC 0030 4.2)
            closed = self._thread_open(group_id, reply_to, now)
            if closed is not None:
                return closed
        if entry.get("owner") or data.get("owner") == me or me in data.get("moderators", []):
            return Permission(True)
        gw = data.get("gateway")
        if gtype == "moderated" and isinstance(gw, dict) and gw.get("direction") == "import":
            # gatewayed one way (UN-RFC 0023 section 9): nothing written here reaches the
            # other network, so clients do not offer to post
            network = str(gw.get("network") or "another network")
            return Permission(False, f"Read only: brought in from {network}, nothing goes back",
                              "gateway_import")
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
        closed = self._thread_open(group_id, reply_to, now)
        return Permission(True) if closed is None else closed

    def _thread_open(self, group_id: str, reply_to: "Message | None",
                     now: datetime | None = None) -> "Permission | None":
        """A reply into a thread whose comments closed - its deadline passed or it was
        closed (UN-RFC 0030 sections 3.1, 3.2): the Permission saying so, with the
        close's note; None when the reply may go."""
        if reply_to is None:
            return None
        try:
            state = self.comments_state(group_id, reply_to.thread_root, now)
        except SessionError:
            return None
        if state["open"]:
            return None
        if state["reason"] == "deadline":
            return Permission(False, "Comments on this thread have closed", "comments_closed")
        note = state.get("note") or ""
        return Permission(False, "Comments on this thread were closed"
                          + (f": {note}" if note else ""), "comments_closed")

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
        """True when you own or moderate the group, by the manifest or because the vault
        says you own it - the client's view, for showing moderation tools."""
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

    async def _submit(self, group_id: str, subject: str, build, files=None) -> str:
        """Send a post to a moderated group's moderators (UN-RFC 0009 section 3). Its
        ``files`` go with it as encrypted blobs of the inbox article, while the post
        names them as the plain blobs it will carry once approved (UN-RFC 0027, 5.3)."""
        self.mark_in_use()               # writing anything is using the identity (#270)
        bits = await self.required_pow(group_id)
        art = await self._compute(lambda: build(bits))
        raw = art.to_bytes().decode("utf-8")
        delivered, errors = 0, []
        for inbox, owner_key in self.submission_targets(group_id):
            try:
                await self.send_private(inbox, f"Submission to {short_group_id(group_id)}: {subject}",
                                        raw, owner_key=owner_key, content_type=SUBMISSION_TYPE,
                                        remember=False, files=files or None)
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
        """True when you sent this post to the group's moderators and it waits for them
        (UN-RFC 0009 section 3)."""
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
        blobs = await self._submitted_files(msg, art)
        approve(art, self.identity())
        try:
            await self._post_article(art, blobs=blobs)
        except SessionError as exc:
            if "duplicate" not in str(exc).lower():
                raise                       # a duplicate: someone else approved it first
        self._queue_notices(self.notice_bundle(art))     # UN-RFC 0032 section 4.3
        self._moderation_done(msg)

    async def _submitted_files(self, msg: "Message", art: Article) -> list[tuple[str, bytes]]:
        """The plain blobs of a submitted post with files (UN-RFC 0027 section 5.3): the
        files sent with the submission, decrypted, each matching a blob the post names
        - checked before approving, uploaded with the approved post."""
        from ...core import blobs as bl
        try:
            named = dict(bl.parse_blobs(art))
        except ArticleError as exc:
            raise SessionError(f"the submission names its files wrongly: {exc}") from exc
        if not named:
            return []
        plain = {}
        for a in msg.attachments:
            octets = await self.fetch_blob(msg.group, a["blob"])
            plain[bl.blob_id(octets)] = octets
        if set(plain) != set(named) or any(len(plain[b]) != n for b, n in named.items()):
            raise SessionError("the files sent with this submission are not the ones it names "
                               "- not approved")
        return list(plain.items())

    async def reject_submission(self, msg: "Message", reason: str = "") -> None:
        """Moderator: turn a submission down (UN-RFC 0009 section 3). With a ``reason``,
        the author gets it as a private post, if they can be answered."""
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
        """The newest manifest seen for a group ({} if none yet), with its charter under
        the current names also when it was signed with the earlier ones (UN-RFC 0014 2.2)."""
        return with_charter(self.data["groups"].get(group_id, {}).get("manifest", {}))

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
        """Accept the group's current portals (UN-RFC 0023 section 3.5): the client stops
        warning that posts here also reach other networks, until the portals change."""
        from ...core import portals
        self.group_entry(group_id)["portals_ok"] = portals.fingerprint(self.group_portals(group_id))
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

        Allowed changes: title, description, charter, charter_type (UN-RFC 0014 2.1), view,
        kinds, low_latency, min_pow, retention_days. Type, owner and locality can never change (UN-RFC 0004, 4).
        """
        entry = self.data["groups"].get(group_id, {})
        if not entry.get("owner"):
            raise SessionError("only the owner can change a group")
        data = self.manifest_data(group_id)
        if not data:
            raise SessionError("the group's manifest has not been fetched yet")
        allowed = {"title", "description", "charter", "charter_type", "view", "low_latency", "min_pow",
                   "retention_days", "banned", "moderators", "posters", "kinds",
                   "comments", "comment_days", *EXTRA_FIELDS}
        if "comments" in changes and data.get("type") != "channel":
            raise SessionError("only channels choose whether readers comment")
        if "comment_days" in changes and (data.get("type") not in ("channel", "open", "moderated",
                                                                   "closed") or data.get("local")):
            raise SessionError("inboxes and local groups have no time for comments")
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
            if key == "reactions":                # [] is none, None the default (0048, 4)
                if value is None:
                    data.pop(key, None)
                else:
                    data[key] = value
                continue
            if value in (None, "", False, []) and key in ("title", "description", "charter",
                                                         "charter_type",
                                                         "low_latency", "banned", "moderators",
                                                         "posters", "kinds", "comments",
                                                         "comment_days", *EXTRA_FIELDS):
                data.pop(key, None)
            else:
                data[key] = value
        if len(data.get("charter", "")) > MAX_CHARTER:
            raise SessionError(f"a charter is limited to {MAX_CHARTER} characters")
        if not data.get("charter"):
            data.pop("charter_type", None)        # no text, no type
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
        """True when the group's current manifest bans this key (UN-RFC 0004 section 5.1)."""
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
        """Owner: lift a ban (a new manifest without that key)."""
        current = [b for b in self.manifest_data(group_id).get("banned", [])
                   if isinstance(b, dict) and b.get("key") != key_text]
        await self.update_group(group_id, banned=current)

    def _charter_seen(self) -> dict:
        """Group ID -> the manifest serial whose charter the user last saw (kept in the
        vault; a vault from before #726 kept it as ``rules_seen``)."""
        seen = self.data.setdefault("charter_seen", {})
        for gid, serial in self.data.pop("rules_seen", {}).items():
            seen.setdefault(gid, serial)
        return seen

    def charter_unseen(self, group_id: str) -> bool:
        """True if the group has a charter the reader has not seen in this version, so the
        client shows it before they read or write there (UN-RFC 0014 section 3)."""
        data = self.manifest_data(group_id)
        if not data.get("charter"):
            return False
        return self._charter_seen().get(group_id, 0) < int(data.get("serial", 1))

    def mark_charter_seen(self, group_id: str) -> None:
        """Note that the user has seen the group's charter in its current version, so the
        client stops showing it until the owner changes it."""
        self._charter_seen()[group_id] = int(self.manifest_data(group_id).get("serial", 1))
        self.save()

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
        """Owner of a closed group: give ``member_key`` the group's current key (a key
        update granting access, UN-RFC 0004 section 6) and note them as a member."""
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

    @staticmethod
    def _checked_manifest(raw: bytes | None, group_id: str):
        """A manifest from a node, checked as UN-RFC 0004 section 4 and 0041 section
        3.1 ask: a valid signed article, by the owner in the Group ID, for this group,
        not expired. None otherwise - a node is not trusted for any of it."""
        from ...core.groups import Manifest
        if not raw:
            return None
        try:
            raw = strip_reader_headers(raw)
            art = Article.from_bytes(raw)
            validate_structure(art, raw_size=len(raw))
            m = Manifest.from_article(art)
        except (ArticleError, ValueError, TypeError):
            return None
        return m if m.group_id == group_id and not m.expired() else None

    async def _manifest_by_group(self, c: Client, group_id: str):
        """The newest valid manifest in a small group of manifests only (profile@,
        avatar@), read with GROUP, HDR Control and ARTICLE: for nodes without
        XUN-MANIFESTS (UN-RFC 0041 section 1)."""
        try:
            _, low, high = await c.group(group_id)
        except NNTPError:
            return None
        if high < low:
            return None
        best = None
        for line in await c.multiline(f"HDR Control {low}-{high}", 225):
            number, _, value = line.partition(" ")
            if value.strip().lower() != "manifest":
                continue
            m = self._checked_manifest(await c.article(number), group_id)
            if m is not None and m.supersedes(best):
                best = m
        return best

    async def fetch_manifests(self, group_ids: list[str], node: str | None = None,
                              fallback: bool = True) -> dict:
        """The current manifests of many groups, Group ID -> Manifest or None.

        With XUN-MANIFESTS (UN-RFC 0041) in requests of up to 256 groups; else one
        group at a time. Cached Message-IDs are not named (section 3.3), so a node
        cannot recognise this client by what it holds. ``fallback`` False: on a node
        without the command, ask nothing (single lookups read whole groups, fine for
        profile groups but not for ordinary ones) and return None for each."""
        wanted = list(dict.fromkeys(group_ids))
        by_node: dict[str | None, list[str]] = {}
        for gid in wanted:
            by_node.setdefault(node or self.node_for(gid), []).append(gid)
        out: dict = {}
        for address, gids in by_node.items():
            async def run(c: Client, gids=gids):
                if c.capability("UNSEENET-MANIFESTS") is None:
                    if not fallback:
                        return {g: None for g in gids}
                    return {g: await self._manifest_by_group(c, g) for g in gids}
                answers = await c.manifests_all([(g, None) for g in gids])
                return {g: self._checked_manifest(answers[g].raw, g) if g in answers else None
                        for g in gids}
            # a node that cannot be reached: ask your others, unless one was named
            tries = [address] + ([] if node else [n for n in self.nodes if n != address])
            for i, at in enumerate(tries):
                try:
                    out.update(await self._call(run, at))
                    break
                except (OSError, ConnectionError, asyncio.IncompleteReadError):
                    if i == len(tries) - 1:
                        raise
        return out

    async def fetch_manifest(self, group_id: str, node: str | None = None):
        """The current valid, unexpired manifest of one group; None if there is none."""
        return (await self.fetch_manifests([group_id], node)).get(group_id)

    def moderates_or_owns(self, group_id: str) -> bool:
        """True when the group's current manifest names you as owner or moderator: who
        may withdraw others' posts (UN-RFC 0004 section 7)."""
        me = self.identity().key_text
        manifest = self.manifest_data(group_id)
        return manifest.get("owner") == me or me in manifest.get("moderators", [])

    @staticmethod
    def _take_manifest(art: Article, group_id: str, entry: dict) -> bool:
        """Keep a manifest from a node only if it is valid (UN-RFC 0004, section 4):
        signed by the owner whose fingerprint is in the group ID, for this group,
        and of the same type as before. A client does not trust its node for this:
        a hostile node could otherwise serve a manifest signed by its own key, e.g.
        adding itself to the posters of unseenet.nodes or unseenet.names (#41).
        Of the valid ones the newest wins (section 3.2). True if it was taken."""
        from ...core.groups import Manifest
        try:
            # our own inbox from before UN-RFC 0029 has no expires: take it, to renew it
            m = Manifest.from_article(art, stored=bool(entry.get("owner")))
        except (ArticleError, ValueError, TypeError):
            return False
        if m.group_id != group_id:
            return False
        old = entry.get("manifest") or {}
        if old:
            if old.get("type") != m.type or old.get("owner") != m.raw.get("owner") \
                    or bool(old.get("local")) != m.local:
                return False                # type, owner and locality never change
            # Newer serial wins; on a tie the lower Message-ID (as Manifest.supersedes)
            if (m.serial, entry.get("manifest_id", "")) <= (int(old.get("serial", 0)), m.message_id):
                return False
        entry["manifest"] = dict(m.raw)
        entry["manifest_id"] = m.message_id
        entry["type"] = m.type
        entry["owner_key"] = m.raw.get("owner")
        if m.title:
            entry["title"] = m.title
        return True
