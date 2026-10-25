"""People: contacts, who you ignore, what is for you, and reporting.

Belongs here: contacts and the address book (UN-RFC 0028 section 6.2), ignoring keys
(the reader's own killfile, never sent), replies and mentions for you (#109, #170) and
mention notices (UN-RFC 0032), hierarchy blocks (0018 section 8.2), bots (0030 section
6), and reporting a post to those who can act on it (#74).

Not here: private posts themselves (private.py), profiles (profiles.py).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class PeopleMixin:
    # ------------------------------------------------------------------
    # contacts and conversations (client side only)
    # ------------------------------------------------------------------
    def add_contact(self, key_text: str, name: str) -> None:
        """Give a key a name of your own (a "petname"). Others cannot fake it."""
        crypto.key_from_text(key_text)
        if not name.strip():
            raise SessionError("a contact needs a name")
        if key_text == self.identity().key_text:
            raise SessionError("that is your own key")
        self.data["contacts"][key_text] = {"name": name.strip()}
        self.mark_in_use()
        self.save()

    def remove_contact(self, key_text: str) -> None:
        """Remove a key from your contacts."""
        self.data["contacts"].pop(key_text, None)
        self.save()

    # --- closing a chat (UN-RFC 0044 section 4.2, closed_chats) ---
    def close_chat(self, key_text: str) -> None:
        """Take a chat with a person off the list of chats, on every device (it is in
        your state). The messages stay; it opens again by itself with the next chat
        line from or to them, so no new message is ever hidden (UN-RFC 0028, 6.2)."""
        crypto.key_from_text(key_text)
        self.data.setdefault("closed_chats", {})[key_text] = \
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.save()

    def open_chat(self, key_text: str) -> None:
        """Put a closed chat back on the list."""
        if self.data.setdefault("closed_chats", {}).pop(key_text, None) is not None:
            self.save()

    def chat_closed(self, key_text: str) -> bool:
        """Whether a chat is closed: closed, and no chat line from or to them since."""
        since = self.data.get("closed_chats", {}).get(key_text)
        if not since:
            return False
        try:
            when = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            return False
        for m in self.cache.get(self.my_inbox, {}).values():
            if m.kind == KIND_CHAT and m.sender_key == key_text and m.date and m.date > when:
                return False
        for e in self.sent:
            if e.get("kind") == KIND_CHAT and e.get("to") == key_text and e.get("date"):
                try:
                    if datetime.fromisoformat(e["date"]) > when:
                        return False
                except ValueError:
                    continue
        return True

    def contact_name(self, key_text: str | None) -> str | None:
        """The name the user gave this key in their contacts, or None."""
        entry = self.data["contacts"].get(key_text or "")
        return entry["name"] if entry else None

    # --- ignoring people: the reader's own killfile, never sent anywhere (#72) ---
    def ignore(self, key_text: str, label: str = "") -> None:
        """Ignore a key: its posts are hidden from you everywhere. Only this vault knows;
        nothing is sent (#72). ``label`` is how the list shows it."""
        crypto.key_from_text(key_text)
        if key_text == self.identity().key_text:
            raise SessionError("that is your own key")
        self.data["ignored"][key_text] = {
            "label": label.strip() or self.identity_label(key_text),
            "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.save()

    def unignore(self, key_text: str) -> None:
        """Stop ignoring a key."""
        self.data["ignored"].pop(key_text, None)
        self.save()

    def is_ignored(self, key_text: str | None) -> bool:
        """True when you ignore this key (see ``ignore``)."""
        return bool(key_text) and key_text in self.data["ignored"]

    def ignored(self) -> list[tuple[str, str]]:
        """(key, label) of the people you ignore, sorted by label."""
        return sorted(((k, v.get("label", k)) for k, v in self.data["ignored"].items()),
                      key=lambda kv: kv[1].lower())

    # --- replies to you and mentions of your names (#109); computed here, never sent ---
    def _remember_mine(self, msgid: str) -> None:
        mine = self.data.setdefault("mine", [])
        mine.append(msgid)
        del mine[:-2000]

    def my_message_ids(self) -> set[str]:
        """The Message-IDs of posts by any identity in this vault, for finding replies
        to you (#109)."""
        keys = {self.identity(n).key_text for n in self.data["identities"]}
        ids = set(self.data.get("mine", []))
        for msgs in self.cache.values():
            ids.update(m.message_id for m in msgs.values() if m.author_key in keys)
        return ids

    def _mention_patterns(self) -> list["re.Pattern"]:
        """Your certified names, as they would be written in a post (UN-RFC 0019).
        Display names do not count: anyone can call themselves Andreas."""
        out = []
        for c in naming.my_names(self):
            text = naming.name_text(c.name)
            out.append(re.compile(r"(?<![a-z0-9@.-])" + re.escape(text) + r"(?![a-z0-9-]|\.[a-z0-9])",
                                  re.IGNORECASE))
        return out

    def for_me(self, msg: "Message", mine: set[str] | None = None,
               patterns: list | None = None) -> str | None:
        """'reply' if the post answers one of yours, 'mention' if it names you, else None.
        A checked mention notice (UN-RFC 0032) is a 'mention' too."""
        if msg.private:
            return "mention" if self.notice_ok(msg) else None
        if not msg.readable:
            return None
        keys = {self.identity(n).key_text for n in self.data["identities"]}
        if msg.author_key in keys:
            return None
        mine = self.my_message_ids() if mine is None else mine
        if any(r in mine for r in msg.references):
            return "reply"
        patterns = self._mention_patterns() if patterns is None else patterns
        text = f"{msg.subject}\n{msg.body}"
        if any(p.search(text) for p in patterns):
            return "mention"
        return None

    def for_you(self, unread_only: bool = True) -> list["Message"]:
        """Replies to you and mentions of you in the groups you follow, newest first."""
        mine, patterns = self.my_message_ids(), self._mention_patterns()
        out = []
        for gid in self.data["subscribed"]:
            if gid == self.my_inbox:
                continue
            for m in self.visible(list(self.cache.get(gid, {}).values())):
                if (not unread_only or not self.is_read(m)) and self.for_me(m, mine, patterns):
                    out.append(m)
        out += [m for m in self.notices() if not unread_only or not self.is_read(m)]
        return sorted(out, key=lambda m: m.date or datetime.min.replace(tzinfo=timezone.utc),
                      reverse=True)

    def for_you_count(self, group_id: str) -> int:
        """How many posts in the group are for you - replies to you and mentions - and
        not read yet (the total of ``for_you_counts``)."""
        return self.for_you_counts(group_id).total

    def for_you_counts(self, group_id: str | None = None) -> "ForYouCount":
        """Unread replies to you and unread mentions of you, counted apart (#170):
        in one group, or in all the groups you follow when group_id is None."""
        mine, patterns = self.my_message_ids(), self._mention_patterns()
        gids = ([group_id] if group_id is not None
                else [g for g in self.data["subscribed"] if g != self.my_inbox])
        replies = 0
        mentions = (sum(1 for m in self.notices() if not self.is_read(m))   # UN-RFC 0032
                    if group_id is None else 0)
        for gid in gids:
            for m in self.visible(list(self.cache.get(gid, {}).values())):
                if self.is_read(m):
                    continue
                why = self.for_me(m, mine, patterns)
                if why == "reply":
                    replies += 1
                elif why == "mention":
                    mentions += 1
        return ForYouCount(replies, mentions)

    # --- mention notices (UN-RFC 0032) ------------------------------------------------
    def notice_settings(self) -> dict:
        """Whether you send notices to people you mention, and accept them (both on)."""
        return {"send": True, "receive": True, **self.data.get("mention_notices", {})}

    def set_notice_settings(self, send: bool | None = None, receive: bool | None = None) -> None:
        """Whether you send mention notices, and whether you take them (UN-RFC 0032).
        ``None`` leaves a setting as it is."""
        st = self.data.setdefault("mention_notices", {})
        if send is not None:
            st["send"] = bool(send)
        if receive is not None:
            st["receive"] = bool(receive)
        self.save()

    def mentioned(self, subject: str, body: str) -> list[tuple[str, str]]:
        """(name as written, key) of the people a text names by a certified name that
        this client can resolve, in order, without you, each key once (section 4.1)."""
        mine = {self.identity(n).key_text for n in self.data["identities"]}
        out: list[tuple[str, str]] = []
        text = split_signature(f"{subject}\n{body}")[0]
        # quoted lines are someone else's words: quoting a mention tells nobody again
        text = "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith(">"))
        for m in NAME_MENTION_RE.finditer(text):
            local, parent = m.group(1), m.group(2).lower()
            name = f"{local.lower()}@{parent}" if local else parent
            try:
                names.check_name(name)
            except names.NameProblem:
                continue
            key = naming.key_for_name(self, name)
            if key and key not in mine and all(k != key for _, k in out):
                out.append((naming.name_text(name), key))
        return out

    def may_notify(self, group_id: str) -> bool:
        """Notices are for posts in open, moderated and channel groups (section 4.1)."""
        try:
            if group_id == self.my_inbox or split_group_id(group_id)[0] == INBOX_NAME:
                return False
        except ValueError:
            return False
        gtype = self.manifest_data(group_id).get("type") or self.group_entry(group_id).get("type")
        return gtype not in ("closed", "inbox")

    async def send_mention_notices(self, group_id: str, msgid: str, subject: str, kind: str,
                                   keys: list[str], delay: float | None = None) -> int:
        """Tell up to 5 people that a post of yours names them (section 4). Waits a
        random time first unless ``delay`` is given. Returns how many were sent.

        A post sent to the moderators is not in the group yet: the notices are built
        now and go to the moderators with it, who post them when they approve it
        (section 4.3) - so it does not matter when you are online again."""
        if not self.may_notify(group_id) or not keys:
            return 0
        if self.was_submitted(group_id, msgid) and not any(
                m.message_id == msgid for m in self.cache.get(group_id, {}).values()):
            return await self._send_notice_bundle(group_id, msgid, subject, kind,
                                                  keys[:MAX_MENTION_NOTICES])
        if delay is None:
            delay = random.uniform(5, 120)
        if delay:
            await asyncio.sleep(delay)
        sent_before = self.data.setdefault("notices_sent", [])
        sent = 0
        for key in keys[:MAX_MENTION_NOTICES]:
            mark = f"{msgid} {key}"
            if mark in sent_before:
                continue
            try:
                owner = crypto.key_from_text(key)
                title, body, extra = self._notice_content(group_id, msgid, subject, kind)
                await self.send_private(
                    personal_inbox_id(owner), title, body, owner_key=owner,
                    content_type=MENTION_TYPE + "; charset=utf-8", remember=False, extra=extra)
            except (SessionError, OSError, ConnectionError, crypto.CryptoError, ValueError):
                continue
            sent_before.append(mark)
            del sent_before[:-500]
            sent += 1
        self.save()
        return sent

    def _notice_content(self, group_id: str, msgid: str, subject: str,
                        kind: str) -> tuple[str, str, list[tuple[str, str]]]:
        """Subject, one-line body and inner headers of a notice (section 3)."""
        label = self.group_label(group_id)
        try:
            ref = "#" + (label if "@" in label else f"{label}@{split_group_id(group_id)[1][:4]}")
        except ValueError:
            ref = group_id
        title = subject if kind != KIND_CHAT and subject else "Mention"
        return (title, f"{self.display_name()} mentioned you in {ref}: {title}\n",
                [("Mention-Group", group_id), ("Mention-Of", msgid)])

    async def _send_notice_bundle(self, group_id: str, msgid: str, subject: str, kind: str,
                                  keys: list[str]) -> int:
        """Section 4.3: build the notices of a submitted post (sealed to each person,
        signed, with postage) and send them to the moderators with the submission."""
        title, body, extra = self._notice_content(group_id, msgid, subject, kind)
        loop = asyncio.get_running_loop()
        built = []
        for key in keys:
            try:
                owner = crypto.key_from_text(key)
                inbox = personal_inbox_id(owner)
                if not self.manifest_data(inbox):
                    await self.inbox_owner(inbox)               # learns its postage
                bits = await self.required_pow(inbox)
                art = await self._compute(lambda: inbox_article(
                    inbox, owner, from_name=self.display_name(), subject=title, body=body,
                    sender=self.identity(), reply_inbox=self.my_inbox,
                    content_type=MENTION_TYPE + "; charset=utf-8", kind=KIND_POST,
                    pow_bits=bits, extra=self._with_inner_ripening(extra)))
            except (SessionError, OSError, ConnectionError, crypto.CryptoError, ValueError):
                continue
            built.append(art)
        if not built:
            return 0
        bundle = "\n".join("\n".join(textwrap.wrap(base64.b64encode(a.to_bytes()).decode(), 76))
                           + "\n" for a in built)
        delivered = 0
        for inbox, owner_key in self.submission_targets(group_id):
            try:
                await self.send_private(inbox, f"Mention notices for {msgid}", bundle,
                                        owner_key=owner_key, content_type=NOTICES_TYPE,
                                        remember=False, extra=[("Notices-For", msgid)])
                delivered += 1
            except (SessionError, OSError, ConnectionError):
                continue
        if not delivered:
            return 0
        marks = self.data.setdefault("notices_sent", [])
        marks.extend(f"{msgid} {k}" for k in keys)
        del marks[:-500]
        self.save()
        return len(built)

    # --- the moderator's side (section 4.3) ---------------------------------------
    def notice_bundle(self, art: Article) -> list[Article]:
        """The notices the author sent with a submission: inbox articles to personal
        inboxes, from a bundle the author signed. At most 5."""
        author = art.get("Author-Key", "")
        for m in self.private_messages():
            if not (m.content_type.startswith(NOTICES_TYPE) and m.notices_for == art.message_id
                    and m.sender_key and m.sender_key == author):
                continue
            out = []
            for block in re.split(r"\n\s*\n", m.body.strip()):
                try:
                    raw = base64.b64decode("".join(block.split()), validate=True)
                    notice = Article.from_bytes(raw)
                    validate_structure(notice, raw_size=len(raw))
                except (ValueError, ArticleError):
                    continue
                if (notice.get("Encrypted", "").strip() in INBOX_SCHEMES
                        and split_group_id(notice.group)[0] == INBOX_NAME):
                    out.append(notice)
            return out[:MAX_MENTION_NOTICES]
        return []

    def _queue_notices(self, notices: list[Article]) -> None:
        """Keep approved notices to post after a random wait (persisted: a moderator
        who quits before then posts them next time)."""
        if not notices:
            return
        due = datetime.now(timezone.utc) + timedelta(seconds=random.uniform(5, 120))
        q = self.data.setdefault("notices_to_post", [])
        q.extend({"raw": base64.b64encode(a.to_bytes()).decode(), "due": due.isoformat()}
                 for a in notices)
        del q[:-200]
        self.save()
        self._schedule_notice_posting()

    def _schedule_notice_posting(self) -> None:
        if self.data.get("notices_to_post") and not self._notice_tasks.get("post"):
            self._notice_tasks["post"] = asyncio.get_running_loop().create_task(
                self._post_queued_notices())

    async def _post_queued_notices(self) -> None:
        try:
            while self.data.get("notices_to_post"):
                q = self.data["notices_to_post"]
                now = datetime.now(timezone.utc)
                item = min(q, key=lambda x: x["due"])
                wait = (datetime.fromisoformat(item["due"]) - now).total_seconds()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    raw = base64.b64decode(item["raw"])
                    await self._post_article(Article.from_bytes(raw))
                except SessionError as exc:
                    if "duplicate" not in str(exc).lower():
                        item["tries"] = item.get("tries", 0) + 1
                        if item["tries"] < 5:
                            item["due"] = (now + timedelta(minutes=10)).isoformat()
                            self.save()
                            continue
                except (OSError, ConnectionError, asyncio.IncompleteReadError):
                    return                       # offline: try again on the next refresh
                except (ValueError, ArticleError):
                    pass
                q.remove(item)
                self.save()
        finally:
            self._notice_tasks.pop("post", None)

    @staticmethod
    def is_notice(m: "Message") -> bool:
        """True when a private post is a mention notice (UN-RFC 0032): it names the post
        and group that mention you."""
        return bool(m.private and m.mention_of and m.mention_group)

    def _notice_states(self) -> dict:
        return self.data.setdefault("notices", {})

    def notice_ok(self, m: "Message") -> bool:
        """A notice to show: checked, wanted, and not already marked in a followed
        group (section 5, rules 1-2)."""
        if not self.is_notice(m) or not self.notice_settings()["receive"]:
            return False
        if self._notice_states().get(m.message_id, {}).get("state") != "ok":
            return False
        if m.mention_group in self.data["subscribed"] and any(
                x.message_id == m.mention_of for x in self.cache.get(m.mention_group, {}).values()):
            return False
        return not self.is_ignored(m.sender_key or "")

    def notices(self) -> list["Message"]:
        """Checked mention notices in your inbox, for For you."""
        return [m for m in self.visible(list(self.cache.get(self.my_inbox, {}).values()))
                if self.notice_ok(m)]

    def notice_post(self, m: "Message") -> dict:
        """What the check found about the mentioned post: group, id, subject, from."""
        return dict(self._notice_states().get(m.message_id, {}))

    async def check_notices(self) -> int:
        """Check new mention notices against their posts (section 5, rule 3). Returns
        how many were found good."""
        states = self._notice_states()
        if not self.notice_settings()["receive"] or not self.my_inbox:
            return 0
        patterns = self._mention_patterns()
        good = 0
        changed = False
        for m in list(self.cache.get(self.my_inbox, {}).values()):
            if not self.is_notice(m):
                continue
            st = states.get(m.message_id, {})
            if st.get("state") in ("ok", "bad") or st.get("tries", 0) >= 5:
                continue
            if not m.sender_key or self.is_ignored(m.sender_key):
                states[m.message_id] = {"state": "bad"}
                changed = True
                continue
            try:
                post = await self._fetch_by_id(m.mention_group, m.mention_of)
            except (SessionError, OSError, ConnectionError, NNTPError,
                    asyncio.IncompleteReadError):
                post = None
            if post is None:
                states[m.message_id] = {"state": "pending", "tries": st.get("tries", 0) + 1}
                changed = True
                continue
            text = f"{post.subject}\n{post.body}"
            ok = (post.readable and post.author_key == m.sender_key
                  and any(p.search(text) for p in patterns))
            states[m.message_id] = ({"state": "ok", "group": m.mention_group, "id": m.mention_of,
                                     "subject": post.subject, "from": post.from_name}
                                    if ok else {"state": "bad"})
            changed = True
            good += ok
        if changed:
            if len(states) > 2000:
                for k in list(states)[:-2000]:
                    states.pop(k)
            self.save()
        return good

    async def _fetch_by_id(self, group_id: str, message_id: str) -> "Message | None":
        """One article by Message-ID from a node that carries the group, read but not
        kept: the check of a mention notice must not make you follow anything."""
        if not message_id.startswith("<"):
            return None

        async def run(c: Client):
            return await c.article(message_id)

        targets = [self.node_for(group_id)] + [n for n in self.nodes if n != self.node_for(group_id)]
        for node in [n for n in targets if n]:
            try:
                raw = await self._call(run, node)
            except (SessionError, NNTPError, OSError, ConnectionError, asyncio.IncompleteReadError):
                continue
            if raw is None:
                continue
            raw = strip_reader_headers(raw)
            try:
                art = Article.from_bytes(raw)
            except ArticleError:
                return None
            if (art.get("Newsgroups") or "").strip() != group_id or art.message_id != message_id:
                return None
            entry = {"type": None, "owner": False, "keys": {}}
            msg = self._parse(0, raw, group_id, entry, self.identity())
            return msg if msg is not None and not msg.encrypted else None
        return None

    def visible(self, msgs: list["Message"]) -> list["Message"]:
        """Leave out messages from people you ignore (your own are always shown), and
        show only the newest version of an edited post (UN-RFC 0042). With
        private_min_ripe set, private posts from unripe strangers are left out too."""
        msgs = [m for m in resolve_edits(msgs) if not m.private_profile]   # not posts (0022, 6)
        if self.private_min_ripe() is not None:
            msgs = [m for m in msgs if self.sender_shown(m)]
        if self.hide_bots():                            # bots out of sight (UN-RFC 0030, 6)
            msgs = [m for m in msgs if m.private or m.to_key is not None
                    or not self.is_bot(m.author_key)]
        groups = {m.group for m in msgs}
        banned = {gid: {k for k, _ in self.banned(gid)} for gid in groups}
        if not self.data.get("show_blocked"):          # maintainers' blocks (UN-RFC 0018, 5.4)
            for gid in groups:
                banned[gid] |= set(self.hierarchy_blocks(gid))
        if not self.data["ignored"] and not any(banned.values()):
            return list(msgs)
        return [m for m in msgs if m.to_key is not None
                or not (self.is_ignored(m.sender_key or m.author_key)
                        or (not m.private and m.author_key in banned.get(m.group, ())))]

    def hierarchy_blocks(self, group_id: str) -> dict[str, tuple[str, str]]:
        """{key: (hierarchy, reason)} that maintainers block for this group."""
        if group_id.startswith("inbox@") or group_id not in self.data["groups"]:
            return {}
        try:
            return naming.blocks(self, group_id)
        except Exception:  # noqa: BLE001  lists that cannot be read block nothing
            return {}

    def hidden_by_blocks(self, group_id: str) -> list[tuple[str, str, int]]:
        """(hierarchy, reason, posts) hidden in a group by maintainers' blocks."""
        if self.data.get("show_blocked"):
            return []
        blocked = self.hierarchy_blocks(group_id)
        count: dict[str, int] = {}
        for m in self.cache.get(group_id, {}).values():
            if m.author_key in blocked:
                count[m.author_key] = count.get(m.author_key, 0) + 1
        return [(blocked[k][0], blocked[k][1], n) for k, n in count.items()]

    def set_show_blocked(self, on: bool) -> None:
        """Whether posts by keys a hierarchy's maintainers block are shown anyway
        (UN-RFC 0018 section 8.2)."""
        self.data["show_blocked"] = bool(on)
        self.save()

    # --- bots (UN-RFC 0022 section 4, UN-RFC 0030 section 6) ---
    def is_bot(self, key_text: str | None) -> bool:
        """Whether the key's profile says it posts automatically (``bot: true``), from
        the cached profiles only (no network; the client runtime keeps them fresh).
        A statement by the key's holder: a missing flag proves nothing (0030, 6)."""
        if not key_text:
            return False
        if self.has_identity() and key_text == self.identity().key_text:
            return bool((self.my_profile() or {}).get("bot") is True)
        hit = self._profile_cache().get(key_text) or {}
        return bool((hit.get("profile") or {}).get("bot") is True)

    def client_setting(self, client: str, key: str, default=None):
        """A setting of one kind of client - ``client_setting("tui", "theme")`` - kept in
        the vault and, with your state, in the network (UN-RFC 0044 section 4.2), so it
        follows you from device to device. Clients choose their own keys."""
        return self.data.get("clients", {}).get(client, {}).get(key, default)

    def set_client_setting(self, client: str, key: str, value) -> None:
        """Change one of a client's settings (None removes it), and save."""
        mine = self.data.setdefault("clients", {}).setdefault(client, {})
        if value is None:
            mine.pop(key, None)
        else:
            mine[key] = value
        self.save()

    def hide_bots(self) -> bool:
        """True when the user chose to hide posts by bots (UN-RFC 0022 section 4)."""
        return bool(self.data.get("hide_bots"))

    def set_hide_bots(self, on: bool) -> None:
        """Leave out posts by keys whose profile says ``bot`` (UN-RFC 0030 section 6)."""
        self.data["hide_bots"] = bool(on)
        self.save()

    def authors(self, limit: int = 500) -> list[str]:
        """The keys that wrote what you can read in your groups, the newest first:
        whose profiles to read in one batch (UN-RFC 0041 section 3.2)."""
        seen: dict[str, float] = {}
        for gid in self.data["subscribed"]:
            for m in self.cache.get(gid, {}).values():
                if m.author_key and not m.private:
                    at = m.date.timestamp() if m.date else 0.0
                    seen[m.author_key] = max(seen.get(m.author_key, 0.0), at)
        return sorted(seen, key=seen.get, reverse=True)[:limit]

    def contacts(self, query: str = "") -> list[tuple[str, str]]:
        """(key, name) sorted by name; with ``query``, only those it finds (#523):
        any part of the name you gave them, of their key or of a name they hold
        (``sonia@lorensen``), case-insensitive - so a long address book is quick to
        search, and a pasted key finds its contact."""
        out = sorted(((k, v["name"]) for k, v in self.data["contacts"].items()),
                     key=lambda kv: kv[1].lower())
        q = query.strip().lower()
        if not q:
            return out
        return [(k, n) for k, n in out if any(q in t for t in self.contact_words(k, n))]

    def contact_words(self, key: str, name: str = "") -> list[str]:
        """What a search for a contact looks at, lower-cased: the name you gave them,
        their key (with and without its ``ed25519:``) and the names they hold."""
        return [name.lower(), key.lower(), key.split(":", 1)[-1].lower(),
                *(n.lower() for n in self.held_names(key))]

    def held_names(self, key: str) -> list[str]:
        """The names a key holds (``sonia@lorensen``), as shown; [] if none known."""
        try:
            return [naming.name_text(c.name) for c in naming.names_of(self, key)]
        except Exception:                 # no names known yet: nothing to show
            return []

    # --- reporting a post (#74): private messages to those who can act on it ---
    async def report_targets(self, msg: "Message") -> list[tuple[str, str, str]]:
        """(who, inbox, key) of the people who can act on a post: the group's owner,
        its moderators, the maintainers of its hierarchy and the operator of the
        node it was read from."""
        out: list[tuple[str, str, str]] = []
        data = self.manifest_data(msg.group)
        me = self.identity().key_text

        def add(who: str, key: str | None, inbox: str | None = None) -> None:
            if not key or key == me or any(k == key for _, _, k in out):
                return
            try:
                inbox = inbox or personal_inbox_id(crypto.key_from_text(key))
            except crypto.CryptoError:
                return
            out.append((who, inbox, key))

        if data.get("owner"):
            add(f"The group's owner ({self.identity_label(data['owner'])})", data["owner"])
        for k in data.get("moderators", []):
            add(f"Moderator {self.identity_label(k)}", k)
        for h in naming.governing(self, msg.group):
            add(f"Maintainer of {h.name}.* ({self.identity_label(h.maintainer)})", h.maintainer)
        try:
            info = await self.node_info(self.node_for(msg.group))
        except (SessionError, OSError, ConnectionError, ValueError):
            info = {}
        if info.get("operator") and info.get("contact"):
            add(f"The operator of {info.get('name', 'the node')}", info["operator"], info["contact"])
        return out

    async def report(self, msg: "Message", targets: list[tuple[str, str, str]], note: str = "",
                     anonymous: bool = False) -> int:
        """Send a report of a post to the chosen people. Returns how many got it."""
        if not targets:
            raise SessionError("choose at least one person to report to")
        quote = "\n".join("> " + line for line in (msg.body or "").rstrip("\n").splitlines()[:40])
        body = (f"Report of a post\n\nGroup: {msg.group}\nMessage-ID: {msg.message_id}\n"
                f"Author key: {msg.author_key}\n"
                + (f"\nNote from the reporter:\n{note.strip()}\n" if note.strip() else "")
                + f"\nThe post, as the reporter saw it:\nFrom: {msg.from_name}\n"
                f"Subject: {msg.subject}\n\n{quote}\n")
        sent, errors = 0, []
        for _, inbox, key in targets:
            try:
                await self.send_private(inbox, f"Report: {msg.subject or '(no subject)'}", body,
                                        owner_key=crypto.key_from_text(key),
                                        content_type=REPORT_TYPE + "; charset=utf-8",
                                        anonymous=anonymous,
                                        remember=False)
                sent += 1
            except (SessionError, OSError, ConnectionError) as exc:
                errors.append(str(exc))
        if not sent:
            raise SessionError("the report could not be sent: " + "; ".join(errors))
        return sent

    @staticmethod
    def reported_post(msg: "Message") -> tuple[str, str] | None:
        """(group, Message-ID) named in a report you received."""
        if not msg.content_type.startswith(REPORT_TYPE):
            return None
        found = dict(re.findall(r"^(Group|Message-ID): (\S+)$", msg.body or "", re.M))
        if "Group" in found and "Message-ID" in found:
            return found["Group"], found["Message-ID"]
        return None
