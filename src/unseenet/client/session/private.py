"""Private posts and the key-bound groups that are yours (UN-RFC 0009, 0029).

Belongs here: the personal inbox (``my_inbox``, ``ensure_inbox``), sending and reading
private posts and chats (``send_private``, ``send_chat``, ``conversation``,
``private_messages``), the sent copies, a new identity's first lifetime (0029 section
4.1, #270), and renewing the key-bound groups of an identity together (0029 section 4).

Not here: contacts and who you ignore (people.py), profiles (profiles.py).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class PrivateMixin:
    # --- a new identity's first lifetime (UN-RFC 0029 section 4, unseenet #270) ---
    IN_USE_DAYS = 3                 # opened on this many different days: in use
    # ------------------------------------------------------------------
    # inboxes and private messages (UN-RFC 0009)
    # ------------------------------------------------------------------
    @property
    def my_inbox(self) -> str:
        return personal_inbox_id(self.identity().public_key)

    async def ensure_inbox(self) -> str:
        """Make sure this identity's personal inbox exists on the node and is subscribed,
        and renew its key-bound groups if due (every client opens with this)."""
        self.note_opened()
        gid = self.my_inbox
        entry = self.group_entry(gid)
        entry.setdefault("node", self.node)
        if not entry.get("owner"):
            async def exists(c: Client) -> bool:
                try:
                    await c.group(gid)
                    return True
                except NNTPError:
                    return False
            if not await self._call(exists, self.node_for(gid)):
                # a serial above any we used before: the inbox may have expired (UN-RFC 0029, 8)
                serial = int(self.manifest_data(gid).get("serial", 0)) + 1
                art = make_manifest(self.identity(), "inbox", "inbox", retention_days=30,
                                    min_pow=_s.DEFAULT_POW, serial=serial,
                                    pow_bits=await self.required_pow(gid),
                                    lifetime=self.key_bound_lifetime())
                await self._post_article(art)
                entry["manifest"] = json.loads(art.body)
            entry.update({"type": "inbox", "owner": True})
        if gid not in self.data["subscribed"]:
            self.data["subscribed"].insert(0, gid)
        self.save()
        try:
            await self.renew_key_bound()
        except (SessionError, OSError, ConnectionError, NNTPError) as exc:
            log.warning("could not renew key-bound groups: %s", exc)
        return gid

    def _ident_entry(self, name: str | None = None) -> dict:
        return self.data["identities"][name or self.default_identity_name()]

    def in_use(self, name: str | None = None, now: datetime | None = None) -> bool:
        """Has this identity been used, so that its key-bound groups get the full
        lifetime? Until then a visitor's inbox lives FIRST_LIFETIME."""
        entry = self._ident_entry(name)
        if entry.get("in_use"):
            return True
        dates = [stored_expires(self.manifest_data(g)) for g in self.key_bound_groups(name)]
        now = now or datetime.now(timezone.utc)
        # already has a long lifetime, or is from before UN-RFC 0029: in use
        if any(d is None or d - now > FIRST_LIFETIME + timedelta(days=1) for d in dates):
            entry["in_use"] = True
            entry.pop("days_opened", None)
            self.save()
            return True
        return False

    def key_bound_lifetime(self, name: str | None = None) -> timedelta:
        return MAX_LIFETIME if self.in_use(name) else FIRST_LIFETIME

    def note_opened(self, today: date | None = None) -> None:
        """Count a day this identity was opened; on IN_USE_DAYS different days it is in use."""
        try:
            entry = self._ident_entry()
        except SessionError:
            return
        if entry.get("in_use"):
            return
        day = (today or datetime.now(timezone.utc).date()).isoformat()
        days = entry.setdefault("days_opened", [])
        if day in days:
            return
        days.append(day)
        del days[:-self.IN_USE_DAYS]
        if len(days) >= self.IN_USE_DAYS:
            self.mark_in_use()
        else:
            self.save()

    def mark_in_use(self, name: str | None = None) -> None:
        """The identity is used (posted, wrote, added a contact, made a group, ...):
        its key-bound groups are renewed with the full lifetime at the next renewal,
        which comes at once since a first lifetime is short."""
        try:
            entry = self._ident_entry(name)
        except SessionError:
            return
        if entry.get("in_use"):
            return
        entry["in_use"] = True
        entry.pop("days_opened", None)
        self.save()

    async def inbox_owner(self, group_id: str) -> bytes:
        """The owner key of an inbox, from its manifest on the node."""
        entry = self.group_entry(group_id)
        if not entry.get("owner_key"):
            subscribed = group_id in self.data["subscribed"]
            await self.fetch_group(group_id)        # reads the manifest
            if not subscribed:                      # do not keep someone else's inbox around
                self.cache.pop(group_id, None)
                self._raw.pop(group_id, None)
                self._high.pop(group_id, None)
        if not entry.get("owner_key"):
            raise SessionError("that inbox does not exist on this node")
        if entry.get("type") != "inbox":
            raise SessionError("that group is not an inbox")
        return crypto.key_from_text(entry["owner_key"])

    def _expired(self, group_id: str, now: datetime | None = None) -> bool:
        """A key-bound group whose last seen manifest has run out (UN-RFC 0029, 5)."""
        exp = stored_expires(self.manifest_data(group_id))
        return (is_key_bound(group_id) and bool(self.manifest_data(group_id))
                and (exp is None or (now or datetime.now(timezone.utc)) >= exp))

    # ------------------------------------------------------------------
    # renewal of key-bound groups (UN-RFC 0029 section 4)
    # ------------------------------------------------------------------
    def key_bound_groups(self, name: str | None = None) -> list[str]:
        """The key-bound groups this identity owns and has a manifest for."""
        fp = self.identity(name).fingerprint
        out = []
        for gid, entry in self.data["groups"].items():
            if entry.get("owner") and entry.get("manifest") and is_key_bound(gid):
                try:
                    if split_group_id(gid)[1] == fp:
                        out.append(gid)
                except ValueError:
                    continue
        return sorted(out)

    def key_bound_expiry(self, name: str | None = None) -> datetime | None:
        """When this identity's key-bound groups run out, if not renewed (the earliest)."""
        dates = [stored_expires(self.manifest_data(g)) for g in self.key_bound_groups(name)]
        if not dates:
            return None
        if any(d is None for d in dates):
            return datetime.fromtimestamp(0, timezone.utc)   # from before UN-RFC 0029
        return min(dates)

    async def renew_key_bound(self, now: datetime | None = None,
                              rng: random.Random | None = None) -> list[str]:
        """Renew key-bound groups that are due, without asking (UN-RFC 0029 section 4).

        Each identity is renewed at a random moment, chosen on its own, within 30 days
        of becoming due, and all of its key-bound groups together at that moment. If
        expiry is near (or the manifest has no ``expires``), it renews at once.
        Returns the groups renewed."""
        now = now or datetime.now(timezone.utc)
        rng = rng or random.SystemRandom()
        renewed: list[str] = []
        self.note_opened(now.date())
        for name, ident_entry in self.data["identities"].items():
            groups = self.key_bound_groups(name)
            expiry = self.key_bound_expiry(name)
            in_use = self.in_use(name, now)
            when_left = RENEW_WHEN_LEFT if in_use else FIRST_RENEW_WHEN_LEFT
            if not groups or expiry is None or expiry - now >= when_left:
                ident_entry.pop("renew_at", None)
                continue
            urgent = expiry - now < RENEW_WINDOW * 2
            at = ident_entry.get("renew_at")
            if at is None and not urgent:
                at = (now + timedelta(seconds=rng.uniform(0, RENEW_WINDOW.total_seconds()))
                      ).timestamp()
                ident_entry["renew_at"] = at
                self.save()
            if not urgent and now.timestamp() < at:
                continue
            owner = self.identity(name)
            for gid in groups:
                data = self.manifest_data(gid)
                data["serial"] = int(data.get("serial", 1)) + 1     # the vault remembers it
                art = manifest_article(owner, gid, data, await self.required_pow(None), now=now,
                                       lifetime=MAX_LIFETIME if in_use else FIRST_LIFETIME)
                await self._post_article(art)
                self.group_entry(gid)["manifest"] = data
                renewed.append(gid)
            ident_entry.pop("renew_at", None)
            self.save()
        return renewed

    async def send_private(self, group_id: str, subject: str, body: str, *,
                           owner_key: bytes | None = None, references: list[str] | None = None,
                           anonymous: bool = False, content_type: str | None = None,
                           kind: str = KIND_POST, remember: bool = True,
                           extra: list[tuple[str, str]] | None = None) -> str:
        """Send a message to an inbox. Only its owner can read it.

        ``kind`` is ``"post"`` (a subject, read on its own, answered with a quote)
        or ``"chat"`` (a line in a running conversation, no subject) - UN-RFC 0028.
        """
        if kind == KIND_CHAT:
            subject = ""
        content_type = content_type or self.text_type()      # Markdown by default (UN-RFC 0031)
        if self._expired(group_id):          # UN-RFC 0029 section 6: look again first
            self.data["groups"].get(group_id, {}).pop("manifest", None)
            self.data["groups"].get(group_id, {}).pop("owner_key", None)
        if not self.manifest_data(group_id):
            try:
                owner_from_manifest = await self.inbox_owner(group_id)   # also learns its min_pow
            except SessionError as exc:
                raise SessionError("the receiver has no inbox you can reach") from exc
            owner_key = owner_key or owner_from_manifest
        owner_key = owner_key or await self.inbox_owner(group_id)
        sender = None if anonymous else self.identity()
        inner = extra if anonymous else self._with_inner_ripening(extra)
        art = await self._post_with_postage(group_id, lambda bits: inbox_article(
            group_id, owner_key, from_name="" if anonymous else self.display_name(),
            subject=subject, body=body, sender=sender,
            reply_inbox=None if anonymous else self.my_inbox,
            references=references, content_type=content_type, kind=kind, pow_bits=bits,
            extra=inner))
        msgid = art.message_id
        if not remember:
            return msgid
        # The message is sealed to the recipient, so keep our own copy (encrypted, local only).
        self._remember_sent({"to": crypto.key_to_text(owner_key), "group": group_id, "msgid": msgid,
                             # where it falls among received messages: dates are rounded to
                             # 10 minutes for privacy, so they cannot order a conversation
                             "after": self._high.get(self.my_inbox, 0),
                             "subject": subject, "body": art_body_text(body), "kind": kind,
                             "references": references or [],
                             "date": datetime.now(timezone.utc).isoformat()})
        self.data["read"].setdefault(self.my_inbox, []).append(msgid)
        self.save()
        return msgid

    def reply_target(self, msg: "Message") -> str | None:
        """Where a reply to a private message goes."""
        if msg.reply_inbox:
            return msg.reply_inbox
        if msg.sender_key:
            return personal_inbox_id(crypto.key_from_text(msg.sender_key))
        return None

    def sent_messages(self, to: str | None = None) -> list["Message"]:
        """Your copies of the private messages you sent (to one key, or all).

        They are sealed to their recipients, so the node's copies are unreadable to
        you; these come from the encrypted ``sent`` sidecar of the vault.
        """
        mine = self.identity().key_text
        out = []
        for i, e in enumerate(self.sent):
            if to is not None and e.get("to") != to:
                continue
            msg = Message(-1 - i, e["msgid"], self.my_inbox, subject=e["subject"],
                          from_name="You", author_key=mine, body=e["body"],
                          references=e.get("references", []), encrypted=True, private=True,
                          sender_key=mine, reply_inbox=e.get("group"), to_key=e.get("to"),
                          kind=KIND_CHAT if e.get("kind") == KIND_CHAT else KIND_POST)
            try:
                msg.date = datetime.fromisoformat(e["date"])
            except (KeyError, ValueError):
                pass
            out.append(msg)
        return out

    def _in_order(self, received: list["Message"], sent: list["Message"]) -> list["Message"]:
        """Received and sent private messages together, oldest first. Inbox dates are
        rounded to 10 minutes for privacy, so a sent message is placed after the
        received messages that had arrived when it was written."""
        after = {e["msgid"]: e.get("after", 0) for e in self.sent}
        order = {m.message_id: (m.number, 0, 0) for m in received}
        for i, m in enumerate(sent):
            order[m.message_id] = (after.get(m.message_id, 0), 1, i)
        return sorted(received + sent, key=lambda m: order[m.message_id])

    def conversation(self, key_text: str, kind: str | None = None) -> list["Message"]:
        """Private messages between you and a key, both directions, oldest first.

        ``kind`` keeps only chats or only posts (UN-RFC 0028); None keeps both.
        """
        received = [m for m in self.cache.get(self.my_inbox, {}).values()
                    if m.sender_key == key_text and (kind is None or m.kind == kind)]
        sent = [m for m in self.sent_messages(key_text) if kind is None or m.kind == kind]
        return self._in_order(received, sent)

    def private_messages(self, kind: str | None = None) -> list["Message"]:
        """Your inbox and what you sent privately, oldest first; only one ``kind`` if given."""
        return self._in_order(
            [m for m in self.cache.get(self.my_inbox, {}).values() if kind is None or m.kind == kind],
            [m for m in self.sent_messages() if kind is None or m.kind == kind])

    def unread_from(self, key_text: str, kind: str | None = None) -> int:
        return sum(1 for m in self.cache.get(self.my_inbox, {}).values()
                   if m.sender_key == key_text and (kind is None or m.kind == kind)
                   and not self.is_read(m))

    def unread_private(self, kind: str | None = None) -> int:
        """Unread private messages of one kind (or all), from anyone."""
        return sum(1 for m in self.visible(list(self.cache.get(self.my_inbox, {}).values()))
                   if (kind is None or m.kind == kind) and not self.is_read(m))

    def _in_private_posts(self, m: "Message") -> bool:
        """Private posts; chats live in a conversation per person (chat_partners). An
        anonymous chat has no person to belong to, so it stays here. Mention notices
        are shown in For you instead (UN-RFC 0032, section 5)."""
        if self.is_notice(m) or m.content_type.startswith(NOTICES_TYPE):
            return False
        return m.kind != KIND_CHAT or not (m.sender_key or m.to_key)

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
