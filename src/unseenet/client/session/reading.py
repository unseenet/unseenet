"""Reading: what you follow, and how a group is fetched, kept and shown.

Belongs here: subscribing (also the starter groups), the groups you follow with their
counts (``subscribed_groups``), fetching a group from its node (``fetch_group``),
decrypting closed groups, threads and views (``threads``, ``view_of``), the encrypted
offline cache (UN-RFC 0007), and read marks.

Not here: a group's manifest (groups.py), private posts (private.py).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class ReadingMixin:
    def subscribe(self, group_id: str, on: bool = True, node: str | None = None) -> None:
        """Follow a group (or stop, ``on=False``). It is read on ``node`` if given, else on
        the default node. Emits ``GroupsChanged`` when the list changed."""
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
        """Follow the project's starter groups (a new client has something to read):
        each version of the list once per vault, so groups added later reach those
        who started earlier too. A group left later is never added again - only the
        groups of versions this vault has not taken yet are. True if any were added."""
        from ...known_nodes import STARTER_GROUP_VERSIONS
        if not self.node:
            return False
        have = self.data.get("starter_groups")
        taken = 1 if have is True else int(have or 0)        # True: version 1, before #388
        if taken >= len(STARTER_GROUP_VERSIONS):
            return False
        added = False
        for version in STARTER_GROUP_VERSIONS[taken:]:
            for gid in version:
                if gid not in self.data["subscribed"]:
                    self.data["subscribed"].append(gid)
                    self.group_entry(gid).setdefault("node", self.node)
                    added = True
        self.data["starter_groups"] = len(STARTER_GROUP_VERSIONS)
        self.save()
        return added

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
        view and a contact's chat; newest first, flat, for "For you"; entries
        newest first with their comments for a feed (``feed_rows``). People you
        ignore are left out and an edited post shows its newest version.
        """
        if group_id == FOR_YOU:
            return [(m, 0) for m in self.for_you(unread_only=False)[:200]]
        if group_id == TIMELINE:                  # UN-RFC 0034 section 7
            return [(m, 0) for m in self.timeline(200)]
        if group_id.startswith(CONTACT):          # as everywhere: ignores, filters (0025, 3.5)
            return [(m, 0) for m in self.visible(self.conversation(group_id[len(CONTACT):],
                                                                   KIND_CHAT))]
        if group_id == self.my_inbox:
            return threaded(self.visible(self.private_posts()))   # what you sent, too
        if self.view_of(group_id) == "feed":
            return self.feed_rows(group_id)
        msgs = sorted(self.cache.get(group_id, {}).values(), key=lambda m: m.number)
        return threaded(self.visible(msgs))        # replies to ignored people stay

    def feed_rows(self, group_id: str) -> list[tuple["Message", int]]:
        """A group as a feed (UN-RFC 0034 section 4), whatever view you chose for it:
        every post or note that answers nothing is an entry, newest first by ``Date``,
        each followed by its comments in order, at most two levels deep - the same
        rows in every client. The timeline is entries only."""
        if group_id == TIMELINE:
            return self.threads(TIMELINE)
        msgs = sorted(self.cache.get(group_id, {}).values(), key=lambda m: m.number)
        return [(m, min(d, FEED_DEPTH)) for m, d in feed_threaded(self.visible(msgs))]

    def view_of(self, group_id: str | None) -> str:
        """``"threads"``, ``"chat"``, ``"feed"`` or ``"data"``: your own choice for the
        group, else its owner's (UN-RFC 0008 section 3.1), else threads. Private posts
        and "For you" are always threads, the timeline a feed, a contact's chat always
        starts as chat."""
        if group_id == TIMELINE:
            return "feed"
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
            raws[n] = raw
            if self._take_reaction(group_id, n, msg):          # UN-RFC 0048: not a post
                cache.pop(n, None)
                continue
            new += n not in cache
            cache[n] = msg
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
                    raws[n] = raw
                    if not self._take_reaction(gid, n, msg):   # UN-RFC 0048
                        cache[n] = msg
                    loaded += 1
            if entry.get("cancels"):
                self._apply_cancels(gid)
        return loaded

    def save_offline(self) -> None:
        """Write the offline cache - the newest articles of each group, encrypted with
        the vault's key - so the client can show them before it is connected."""
        groups = {}
        for gid, raws in self._raw.items():
            keep = sorted(raws)[-MAX_CACHED_PER_GROUP:]
            groups[gid] = {"node": self.node_for(gid), "high": self._high.get(gid, 0),
                           "articles": {str(n): base64.b64encode(raws[n]).decode() for n in keep}}
        payload = json.dumps({"v": 2, "groups": groups}).encode()
        self.vault.write_sidecar(CACHE_SIDECAR, payload)

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
        if ctl and ctl[0] in ("pin", "unpin") and len(ctl) == 2:
            # whose pins count is worked out from the manifest when shown (kept.py)
            try:
                when = int(parse_date(art["Date"]).timestamp())
                replaces = parse_supersedes(art, control_ok=True)   # pins name pins (0033, 3.1)
            except (ArticleError, TypeError, ValueError):
                return None
            entry.setdefault("markers", {})[art.message_id] = {
                "target": ctl[1], "action": ctl[0], "by": art["Author-Key"], "date": when,
                "supersedes": replaces, "note": art.body.strip()[:256]}
            return None
        if ctl:
            return None
        msg = Message(n, art.message_id, group_id, author_key=art["Author-Key"],
                      references=(art.get("References") or "").split())
        if art.get("Encrypted", "").strip() not in INBOX_SCHEMES:   # not in inboxes (0042, 2)
            try:
                msg.supersedes = parse_supersedes(art)
            except ArticleError:
                pass
        try:
            msg.date = parse_date(art["Date"])
        except (TypeError, ValueError):
            pass
        if art.get("Encrypted", "").strip() in INBOX_SCHEMES:
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
            msg.reaction = (art.get("Reaction") or "").strip()   # UN-RFC 0048
            msg.content_type = art.get("Content-Type", "")   # Markdown or plain (UN-RFC 0031)
            from ...core.origins import origin_of
            origin = origin_of(art.get, msg.date)              # UN-RFC 0049 section 4
            if origin is not None:
                msg.origin_network, msg.origin_date = origin.network, origin.date
                msg.origin_id, msg.origin_from = origin.id, origin.from_
            if art.get("Blobs"):                             # files it carries (UN-RFC 0027)
                from ...core import blobs as bl
                try:
                    msg.blobs = tuple(b for b, _ in bl.parse_blobs(art))
                except ArticleError:
                    msg.blobs = ()
                msg.attachments = tuple(a for a in bl.shown_attachments(art.headers)
                                        if a["blob"] in msg.blobs)
            if art.get("Page") is not None:                  # a site's page (UN-RFC 0035)
                msg.page = art["Page"].strip()
                msg.page_removed = (art.get("Page-Removed") or "").strip().lower() == "yes"
            naming.note_certificate(self, msg.author_key, art.get(names.HEADER))
        return msg

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
        msg.reaction = (inner.get("Reaction") or "").strip()     # UN-RFC 0048 section 8
        msg.content_type = inner.get("Content-Type", "")
        self._encrypted_files(msg, art, inner, msg.group)    # UN-RFC 0027, 3.3 and 4.4
        if msg.content_type.startswith(prof.PRIVATE_TYPE):  # shared with the group (0022, 6)
            self._keep_private_profile(msg, msg.group)

    def _encrypted_files(self, msg: Message, art: Article, inner: Article, group_id: str) -> None:
        """The files of an encrypted article, from its inner headers, checked against its
        outer ``Blobs`` and the group's types (UN-RFC 0027 sections 4.4, 5.2)."""
        if not art.get("Blobs"):
            return
        from ...core import blobs as bl
        att = self.manifest_data(group_id).get("attachments")
        shown, keys = bl.inner_attachments(art, inner.headers,
                                           att.get("types") if isinstance(att, dict) else None)
        msg.blobs = tuple(keys)
        msg.attachments = tuple(shown)
        msg.file_keys = keys

    def _redecrypt(self, group_id: str) -> None:
        entry = self.group_entry(group_id)
        cache = self.cache.get(group_id, {})
        for n, msg in list(cache.items()):
            if msg.encrypted and not msg.readable and msg.raw:
                self._decrypt_into(msg, Article.from_bytes(msg.raw), entry)
                if self._take_reaction(group_id, n, msg):      # it was a reaction (0048, 8)
                    del cache[n]

    # ------------------------------------------------------------------
    # read marks
    # ------------------------------------------------------------------
    def is_read(self, msg: Message) -> bool:
        """True when you have read this post, or an earlier version of it - an edit of a
        read post stays read (UN-RFC 0042)."""
        marks = self.data["read"].get(msg.group, [])
        # an edit of a post you read stays read (UN-RFC 0042): seeing it changed is
        # what "(edited)" is for, not a new post
        if msg.message_id in marks or any(v in marks for v in msg.versions):
            return True
        to = self.data.get("read_to", {}).get(msg.group)    # read up to a date, on any device
        return bool(to and msg.date and                     # (UN-RFC 0044 section 4.3)
                    msg.date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") <= to)

    def mark_read(self, msg: Message, save: bool = True) -> None:
        """Mark a post read. Each group keeps the newest marks only (``MAX_READ_MARKS``);
        ``save=False`` when marking many at once and saving after."""
        marks = self.data["read"].setdefault(msg.group, [])
        if msg.message_id not in marks:
            marks.append(msg.message_id)
            del marks[:-MAX_READ_MARKS]
            if save:
                self.save()

    def unread_count(self, group_id: str) -> int:
        """How many posts in the group you have not read, among those shown (not ignored
        or blocked), from what this client has fetched."""
        return sum(1 for m in self.visible(list(self.cache.get(group_id, {}).values()))
                   if not self.is_read(m) and not m.old_on_arrival)    # UN-RFC 0049 5.2
