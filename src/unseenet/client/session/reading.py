"""Reading, laying out a group, the offline cache, read marks. Part of Session (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class ReadingMixin:
    # --- how a client lays out a group (unseenet #139) ---
    def subscribed_groups(self, available: dict[str, GroupInfo] | None = None, *,
                          counts: bool = True) -> list[GroupInfo]:
        """The groups you follow, in your order, as every client lists them.

        ``available`` is what your nodes list (``list_groups()``), when you
        have it: a group missing from it gets ``listed=False``. Key-bound groups
        such as your inbox are never listed, so they always count as listed
        (UN-RFC 0040 section 3). ``counts`` fills in unread posts, replies and
        mentions; leave it off when the client counts in its own time.
        """
        return [self.group_info(gid, available, counts=counts)
                for gid in self.data["subscribed"]]

    def group_info(self, group_id: str, available: dict[str, GroupInfo] | None = None, *,
                   counts: bool = True) -> GroupInfo:
        """One group as every client shows it, followed or not (a group being
        browsed, say): type, title, view, what it takes, and with ``counts`` the
        unread posts, replies and mentions. ``available`` as for
        ``subscribed_groups()``. Nothing is stored for a group you don't follow."""
        entry = self.data["groups"].get(group_id, {})
        data = self.manifest_data(group_id)
        g = available[group_id] if available is not None and group_id in available \
            else GroupInfo(group_id, entry.get("title", "") or data.get("description", ""))
        g.subscribed = group_id in self.data["subscribed"]
        g.type = entry.get("type") or g.type or data.get("type")
        g.title = data.get("title") or entry.get("title", "")
        g.owner = bool(entry.get("owner"))
        g.view, g.owner_view = self.view_of(group_id), data.get("view", "threads")
        g.kinds = tuple(self.group_kinds(group_id))
        g.local, g.low_latency = bool(data.get("local")), bool(data.get("low_latency"))
        if available is not None:
            g.listed = group_id in available or is_key_bound(group_id)
        if counts:
            c = self.for_you_counts(group_id)
            g.unread, g.replies, g.mentions = self.unread_count(group_id), c.replies, c.mentions
        return g

    def threads(self, group_id: str) -> list[tuple["Message", int]]:
        """A group's posts as every client shows them: ``(message, depth)`` rows.

        Threads newest first for a post view; oldest first, flat, for a chat
        view and a contact's chat; newest first, flat, for "For you". People
        you ignore are left out and an edited post shows its newest version.
        """
        if group_id == FOR_YOU:
            return [(m, 0) for m in self.for_you(unread_only=False)[:200]]
        if group_id.startswith(CONTACT):          # as everywhere: ignores, filters (0025, 3.5)
            return [(m, 0) for m in self.visible(self.conversation(group_id[len(CONTACT):],
                                                                   KIND_CHAT))]
        if group_id == self.my_inbox:
            return threaded(self.visible(self.private_posts()))   # what you sent, too
        msgs = sorted(self.cache.get(group_id, {}).values(), key=lambda m: m.number)
        return threaded(self.visible(msgs))        # replies to ignored people stay

    def view_of(self, group_id: str | None) -> str:
        """``"threads"``, ``"chat"`` or ``"data"``: your own choice for the group,
        else its owner's (UN-RFC 0008 section 3.1), else threads. Private posts
        and "For you" are always threads, a contact's chat always starts as chat."""
        if not group_id or group_id == self.my_inbox or group_id == FOR_YOU:
            return "threads"
        views = self.data.get("views", {})
        if group_id in views:
            return views[group_id]
        if group_id.startswith(CONTACT):
            return "chat"
        return self.manifest_data(group_id).get("view", "threads")

    def set_view(self, group_id: str, view: str, *, save: bool = True) -> None:
        """Remember how you want to see a group; ``None`` goes back to the owner's."""
        if view is not None and view not in VIEWS:
            raise ValueError(f"unknown view {view!r}, expected one of {', '.join(VIEWS)}")
        if group_id == self.my_inbox or group_id == FOR_YOU:
            raise SessionError("private posts and \"For you\" are always shown as threads")
        views = self.data.setdefault("views", {})
        if view is None:
            views.pop(group_id, None)
        else:
            views[group_id] = view
        if save:
            self.save()

    async def send_chat(self, group_id: str, text: str) -> str:
        """Send a chat line (UN-RFC 0028): to a group, or to one person when
        ``group_id`` is ``contact:<key>``. No subject and no signature, unlike
        a post. Returns the Message-ID. Portals and mention notices are the
        client's to ask about first, as for ``post()``."""
        if group_id.startswith(CONTACT):
            owner = crypto.key_from_text(group_id[len(CONTACT):])
            return await self.send_private(personal_inbox_id(owner), "", text,
                                           owner_key=owner, kind=KIND_CHAT)
        return await self.post(group_id, "", text, kind=KIND_CHAT)

    def private_posts(self) -> list["Message"]:
        """What the "Private posts" view shows (UN-RFC 0028 section 6.2), oldest first."""
        return [m for m in self.private_messages() if self._in_private_posts(m)]

    def unread_private_posts(self) -> int:
        return sum(1 for m in self.visible(list(self.cache.get(self.my_inbox, {}).values()))
                   if self._in_private_posts(m) and not self.is_read(m))

    def chat_partners(self) -> list[str]:
        """Everyone you have a chat with: your contacts, and anyone else you have
        chatted with (so no chat ever goes missing, UN-RFC 0028 section 6.2).

        Contacts first, by name; then the others, the most recent chat first."""
        contacts = [k for k, _ in self.contacts()]
        last: dict[str, int] = {}
        for m in self.visible(list(self.cache.get(self.my_inbox, {}).values())):
            if m.kind == KIND_CHAT and m.sender_key:
                last[m.sender_key] = max(last.get(m.sender_key, -1), m.number)
        for i, e in enumerate(self.sent):
            if e.get("kind") == KIND_CHAT and e.get("to"):
                last[e["to"]] = max(last.get(e["to"], -1), e.get("after", 0))
        me = self.identity().key_text
        others = sorted((k for k in last if k not in contacts and k != me),
                        key=lambda k: last[k], reverse=True)
        return contacts + others

    def _load_sent(self) -> list[dict]:
        """Copies of private posts you sent (they are sealed to others, so only these
        copies let you read them again). They are kept in the vault itself, so the one
        file is your whole identity in every client - terminal, graphical, web.
        Older vaults kept them in a sidecar file; they move into the vault here."""
        sent = self.data.get("sent")
        if isinstance(sent, list):
            return sent
        try:
            payload = self.vault.read_sidecar(SENT_SIDECAR)
        except Exception:  # noqa: BLE001  damaged: nothing to move
            payload = None
        self.data["sent"] = json.loads(payload).get("sent", []) if payload else []
        if payload:
            self.save()
            try:
                self.vault.sidecar_path(SENT_SIDECAR).unlink()
            except OSError:
                pass
        return self.data["sent"]

    def _remember_sent(self, entry: dict) -> None:
        self.sent.append(entry)
        self.save()

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------
    async def fetch_group(self, group_id: str) -> list[Message]:
        """Fetch new articles in a group; returns all cached messages, oldest first."""
        cache = self.cache.setdefault(group_id, {})
        raws = self._raw.setdefault(group_id, {})
        me = self.identity()
        entry = self.group_entry(group_id)

        def reader(since: int):
            async def run(c: Client):
                try:
                    _, low, high = await c.group(group_id)
                except NNTPError as exc:
                    if "removed by its owner" in exc.text:
                        raise SessionError("removed by its owner") from exc
                    raise SessionError("group not carried by this node") from exc
                start = max(low, since + 1)
                if not entry.get("manifest") and not entry.get("manifest_rescanned"):
                    # Joined before manifests were kept (or never seen it): read the group
                    # once from the start so title, rules, view and postage are known.
                    start = low
                    entry["manifest_rescanned"] = True
                fetched = []
                for n in range(start, high + 1):
                    raw = await c.article(str(n))
                    if raw is not None:
                        fetched.append((n, raw))
                return fetched, high
            return run

        home = self.node_for(group_id)
        try:
            fetched, high = await self._call(reader(self._high.get(group_id, 0)), home)
        except (SessionError, OSError, ConnectionError, asyncio.IncompleteReadError) as first:
            if "removed by its owner" in str(first):
                raise
            for other in (n for n in self.nodes if n != home):   # another node may carry it
                try:
                    fetched, high = await self._call(reader(0), other)
                except (SessionError, OSError, ConnectionError, asyncio.IncompleteReadError):
                    continue
                self.say(f"{short_group_id(group_id)} is now read from {other}")
                self.pin_group(group_id, other)
                cache = self.cache.setdefault(group_id, {})
                raws = self._raw.setdefault(group_id, {})
                break
            else:
                raise first
        changed, new = False, 0
        for n, raw in fetched:
            raw = strip_reader_headers(raw)
            msg = self._parse(n, raw, group_id, entry, me)
            if msg is None:
                changed = True     # control article updated group state
                continue
            new += n not in cache
            cache[n] = msg
            raws[n] = raw
        if high > self._high.get(group_id, 0):
            self._high[group_id] = high
        if entry.get("cancels") and self._apply_cancels(group_id):
            changed = True
        if changed:
            self.save()
        if fetched or changed:
            self.save_offline()
            self.emit(ev.GroupUpdated(group_id, new))        # new posts, not control articles
        if group_id == self.my_inbox:
            await self.check_private_senders()     # UN-RFC 0025, section 3.5 (if wanted)
            await self.check_notices()             # UN-RFC 0032, section 5
        if group_id == self.my_inbox:
            self._schedule_notice_posting()        # approved notices still to go (4.3)
        return sorted(cache.values(), key=lambda m: m.number)

    # ------------------------------------------------------------------
    # offline cache (UN-RFC 0007: encrypted with the vault key)
    # ------------------------------------------------------------------
    def load_offline(self) -> int:
        """Load cached articles so groups can be read without a connection.

        Article numbers are local to a node, so the cache is only used for the
        node it was made with. Returns the number of articles loaded.
        """
        try:
            payload = self.vault.read_sidecar(CACHE_SIDECAR)
        except Exception:  # noqa: BLE001  damaged cache: start over, the node has it all
            return 0
        if not payload:
            return 0
        data = json.loads(payload)
        if data.get("v") not in (1, 2):
            return 0
        me = self.identity()
        loaded = 0
        for gid, g in data.get("groups", {}).items():
            # numbers only mean something on the node they came from
            if g.get("node", data.get("node")) != self.node_for(gid):
                continue
            entry = self.group_entry(gid)
            self._high[gid] = max(self._high.get(gid, 0), int(g.get("high", 0)))
            cache = self.cache.setdefault(gid, {})
            raws = self._raw.setdefault(gid, {})
            for n_text, b64raw in g.get("articles", {}).items():
                n, raw = int(n_text), base64.b64decode(b64raw)
                msg = self._parse(n, raw, gid, entry, me)
                if msg is not None:
                    cache[n], raws[n] = msg, raw
                    loaded += 1
            if entry.get("cancels"):
                self._apply_cancels(gid)
        return loaded

    def save_offline(self) -> None:
        groups = {}
        for gid, raws in self._raw.items():
            keep = sorted(raws)[-MAX_CACHED_PER_GROUP:]
            groups[gid] = {"node": self.node_for(gid), "high": self._high.get(gid, 0),
                           "articles": {str(n): base64.b64encode(raws[n]).decode() for n in keep}}
        payload = json.dumps({"v": 2, "groups": groups}).encode()
        self.vault.write_sidecar(CACHE_SIDECAR, payload)

    def may_cancel(self, msg: Message) -> bool:
        """Your own post, or any post in a group you own or moderate (UN-RFC 0004, 7.1)."""
        if msg is None or msg.private or msg.group not in self.data["groups"]:
            return False
        me = self.identity().key_text
        manifest = self.manifest_data(msg.group)
        return msg.author_key == me or manifest.get("owner") == me \
            or me in manifest.get("moderators", [])

    def moderates_or_owns(self, group_id: str) -> bool:
        me = self.identity().key_text
        manifest = self.manifest_data(group_id)
        return manifest.get("owner") == me or me in manifest.get("moderators", [])

    async def withdraw(self, group_id: str, message_id: str, reason: str = "") -> str:
        """Withdraw a post by its Message-ID (UN-RFC 0004 section 7): any post in a
        group you own or moderate, else your own. The node has the last word."""
        mid = message_id if message_id.startswith("<") else f"<{message_id}>"
        if not self.moderates_or_owns(group_id):
            msg = next((m for m in self.cache.get(group_id, {}).values() if m.message_id == mid), None)
            if msg is None or msg.author_key != self.identity().key_text:
                raise SessionError("you can only withdraw your own posts, or posts in a group "
                                   "you own or moderate")
        if self.group_entry(group_id).get("type") == "closed":
            reason = ""                     # the nodes could read it (section 7.5)
        me = self.identity()
        art = await self._post_with_postage(group_id, lambda bits: new_article(
            group_id, None, reason, extra=[("Control", f"cancel {mid}")]).finalize(me, bits))
        self.group_entry(group_id).setdefault("cancels", {})[mid] = {"by": me.key_text, "date": art["Date"]}
        self._apply_cancels(group_id)
        self.save()
        self.save_offline()
        return art.message_id

    async def withdraw_all(self, group_id: str, keep=(), reason: str = "") -> list[str]:
        """Owner or moderator: withdraw every post in the group but those in ``keep``
        (for example a demo's weekly reset). Returns the Message-IDs withdrawn."""
        if not self.moderates_or_owns(group_id):
            raise SessionError("only the owner or a moderator can withdraw all posts")
        await self.fetch_group(group_id)
        done = []
        for msg in list(self.cache.get(group_id, {}).values()):
            if msg.message_id in keep:
                continue
            await self.withdraw(group_id, msg.message_id, reason)
            done.append(msg.message_id)
        return done

    async def cancel(self, msg: Message, reason: str = "") -> str:
        """Withdraw a post from the network (UN-RFC 0004, section 7). Best effort:
        people who read it already, and nodes that ignore cancels, may keep it."""
        if not self.may_cancel(msg):
            raise SessionError("you can only withdraw your own posts, or posts in a group "
                               "you own or moderate")
        group_id = msg.group
        if self.group_entry(group_id).get("type") == "closed":
            reason = ""                     # the nodes could read it (section 7.5)
        me = self.identity()
        art = await self._post_with_postage(group_id, lambda bits: new_article(
            group_id, None, reason, extra=[("Control", f"cancel {msg.message_id}")]
        ).finalize(me, bits))
        entry = self.group_entry(group_id)
        entry.setdefault("cancels", {})[msg.message_id] = {"by": me.key_text, "date": art["Date"]}
        self._apply_cancels(group_id)
        self.save()
        self.save_offline()
        return art.message_id

    def _apply_cancels(self, group_id: str) -> bool:
        """Drop posts withdrawn by a valid cancel (UN-RFC 0004, 7.1 and 7.3).

        The client checks each cancel itself: signed (checked in _parse) by the
        target's author, or by the group's owner or a moderator. Cancels whose
        target has not arrived are kept for the group's retention, then dropped.
        True if anything changed."""
        entry = self.group_entry(group_id)
        cancels = entry.get("cancels") or {}
        cache = self.cache.get(group_id, {})
        raws = self._raw.get(group_id, {})
        manifest = self.manifest_data(group_id)
        privileged = {manifest.get("owner")} | set(manifest.get("moderators", []))
        by_id = {m.message_id: n for n, m in cache.items()}
        keep_days = int(manifest.get("retention_days", 90))
        now = datetime.now(timezone.utc)
        changed = False
        for target, c in list(cancels.items()):
            n = by_id.get(target)
            if n is None:
                try:
                    old = (now - parse_date(c.get("date", ""))).days > keep_days
                except (TypeError, ValueError):
                    old = True
                if old:                     # pending too long (section 7.2)
                    del cancels[target]
                    changed = True
                continue
            try:                            # the target's signer, also for private messages
                target_author = Article.from_bytes(raws[n])["Author-Key"] if n in raws \
                    else cache[n].author_key
            except (ArticleError, KeyError, ValueError):
                target_author = cache[n].author_key
            if c.get("by") == target_author or c.get("by") in privileged:
                gone = cache.pop(n)
                raws.pop(n, None)
                changed = True
                # withdrawing an edit withdraws the post: its earlier versions by the
                # same author go too, or they would show again (UN-RFC 0042, 4.2)
                for v in gone.supersedes:
                    vn = by_id.get(v)
                    if vn in cache and cache[vn].author_key == gone.author_key:
                        del cache[vn]
                        raws.pop(vn, None)
            else:                           # not valid for this target: forget it
                del cancels[target]
                changed = True
        return changed

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

    def _parse(self, n: int, raw: bytes, group_id: str, entry: dict, me) -> Message | None:
        try:
            art = Article.from_bytes(raw)
            validate_structure(art, raw_size=len(raw))
        except ArticleError as err:
            return Message(n, f"<invalid-{n}>", group_id, subject="(invalid article)",
                           readable=False, error=str(err))
        ctl = art.control
        if ctl and ctl[0] == "manifest":
            self._take_manifest(art, group_id, entry)
            return None
        if ctl and ctl[0] in ("key-update", "key-grant"):
            try:
                if ctl[0] == "key-update" and json.loads(art.body).get("closes_previous") is True:
                    closed = entry.setdefault("closed", {})        # epoch -> article number
                    closed.setdefault(ctl[1], n)
            except (ValueError, AttributeError):
                pass
            opened = open_envelope(art, me)
            if opened:
                epoch, keys = opened
                entry["keys"][str(epoch)] = keys.secret.hex()
                self._redecrypt(group_id)
            return None
        if ctl and ctl[0] == "cancel" and len(ctl) == 2:
            # checked against the target in _apply_cancels (UN-RFC 0004, 7.3)
            entry.setdefault("cancels", {}).setdefault(ctl[1], {
                "by": art["Author-Key"], "date": art.get("Date", "")})
            return None
        if ctl:
            return None
        msg = Message(n, art.message_id, group_id, author_key=art["Author-Key"],
                      references=(art.get("References") or "").split())
        if art.get("Encrypted", "").strip() != INBOX_SCHEME:   # not in inboxes (0042, 2)
            try:
                msg.supersedes = parse_supersedes(art)
            except ArticleError:
                pass
        try:
            msg.date = parse_date(art["Date"])
        except (TypeError, ValueError):
            pass
        if art.get("Encrypted", "").strip() == INBOX_SCHEME:
            msg.encrypted = msg.private = True
            self._open_private(msg, art, group_id)
        elif "Encrypted" in art:
            # posted with an old key after a member was removed (UN-RFC 0004, 6.5)
            try:
                epoch = encryption_epoch(art)
            except (ArticleError, ValueError):
                epoch = 0
            if any(int(e) > epoch and n > at for e, at in entry.get("closed", {}).items()):
                return None
            msg.encrypted = True
            msg.raw = raw
            self._decrypt_into(msg, art, entry)
        else:
            msg.subject, msg.from_name, msg.body = art.get("Subject", ""), art["From"], art.body
            msg.kind = message_kind(art)                     # UN-RFC 0028
            msg.content_type = art.get("Content-Type", "")   # Markdown or plain (UN-RFC 0031)
            naming.note_certificate(self, msg.author_key, art.get(names.HEADER))
        return msg

    def _open_private(self, msg: Message, art: Article, group_id: str) -> None:
        owner = self._identity_for_fingerprint(split_group_id(group_id)[1])
        if owner is None:
            msg.readable = False
            msg.subject = "(private message for the inbox owner)"
            return
        try:
            inner, sender = open_inbox_article(art, owner)
        except ArticleError as err:
            msg.readable, msg.error, msg.subject = False, str(err), "(unreadable private message)"
            return
        msg.subject, msg.body = inner.get("Subject", ""), inner.body
        msg.content_type = inner.get("Content-Type", "")
        msg.kind = message_kind(inner)
        msg.reply_inbox = inner.get("Reply-Inbox")
        if msg.content_type.startswith(MENTION_TYPE):          # UN-RFC 0032
            msg.mention_group = (inner.get("Mention-Group") or "").strip() or None
            msg.mention_of = (inner.get("Mention-Of") or "").strip() or None
        elif msg.content_type.startswith(NOTICES_TYPE):
            msg.notices_for = (inner.get("Notices-For") or "").strip() or None
        if sender is None:
            msg.from_name, msg.author_key = "anonymous", ""
        else:
            msg.sender_key = crypto.key_to_text(sender)
            msg.author_key = msg.sender_key          # show the real sender, not the one-time key
            msg.sender_ripening = (inner.get("Key-Ripening") or "").strip() or None
            msg.from_name = inner.get("From", "")
            naming.note_certificate(self, msg.sender_key, inner.get(names.HEADER))

    def _decrypt_into(self, msg: Message, art: Article, entry: dict) -> None:
        key_hex = entry["keys"].get(str(encryption_epoch(art)))
        if not key_hex:
            msg.readable = False
            msg.subject = "(encrypted - you are not a member)"
            return
        inner = decrypt_article(art, crypto.GroupKeys(bytes.fromhex(key_hex)))
        msg.readable = True
        msg.subject, msg.from_name, msg.body = inner.get("Subject", ""), inner["From"], inner.body
        msg.kind = message_kind(inner)                       # inside the encryption (UN-RFC 0028)
        msg.content_type = inner.get("Content-Type", "")

    def _redecrypt(self, group_id: str) -> None:
        entry = self.group_entry(group_id)
        for msg in self.cache.get(group_id, {}).values():
            if msg.encrypted and not msg.readable and msg.raw:
                self._decrypt_into(msg, Article.from_bytes(msg.raw), entry)

    # ------------------------------------------------------------------
    # read marks
    # ------------------------------------------------------------------
    def is_read(self, msg: Message) -> bool:
        marks = self.data["read"].get(msg.group, [])
        # an edit of a post you read stays read (UN-RFC 0042): seeing it changed is
        # what "(edited)" is for, not a new post
        return msg.message_id in marks or any(v in marks for v in msg.versions)

    def mark_read(self, msg: Message, save: bool = True) -> None:
        marks = self.data["read"].setdefault(msg.group, [])
        if msg.message_id not in marks:
            marks.append(msg.message_id)
            del marks[:-MAX_READ_MARKS]
            if save:
                self.save()

    def unread_count(self, group_id: str) -> int:
        return sum(1 for m in self.visible(list(self.cache.get(group_id, {}).values()))
                   if not self.is_read(m))
