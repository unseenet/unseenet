"""Sharing (UN-RFC 0060): sharing, fetching what a share refers to, and share notices.

Belongs here: what a message shares (``_take_share``), whether it can be shared and
where (``share_permission``, ``share_into_permission``, ``share_destinations``),
sharing into your feed or a group and taking it back (``share``, ``unshare``),
sending a share to one person (``send_share``), fetching and checking the article a
share refers to (``fetch_share_target``, section 6.3), share notices (section 8), the
reader's ``hide_shares`` (section 5.4) and the timeline's "each target once"
(``_merge_shares``).

Not here: the rules (core/shares.py), drawing a share (the clients).
"""

from __future__ import annotations

import logging
import random

from . import *  # noqa: F403  - the module's names, as when this was one file
from ...core import shares as sh

TARGET_TTL = 300.0             # how long a fetched target is kept in memory (seconds)
FETCH_RETRY = 3.0              # section 6.3: on 436, again after a few seconds ...
FETCH_PATIENCE = 60.0          # ... for at most a minute

log = logging.getLogger("unseenet.shares")


class SharesMixin:
    # --- what a message shares ---------------------------------------------------
    @staticmethod
    def _take_share(msg: Message, get) -> None:
        """Read ``Share-Of``/``Share-Group``, ``Sharing`` and, in a share notice,
        ``Shared-As``/``Shared-In`` (UN-RFC 0060 sections 4.1, 4.4, 8)."""
        of, grp = (get(sh.SHARE_OF) or "").strip(), (get(sh.SHARE_GROUP) or "").strip()
        if of and grp:
            msg.share_of, msg.share_group = of, grp
        msg.sharing_no = (get(sh.SHARING) or "").strip().lower() == "no"
        if (msg.content_type or "").split(";")[0].strip().lower() == sh.NOTICE_TYPE:
            msg.shared_as = (get(sh.SHARED_AS) or "").strip() or None
            msg.shared_in = (get(sh.SHARED_IN) or "").strip() or None

    def share_target(self, msg: Message) -> tuple[str, str]:
        """``(Message-ID, group)`` of what sharing ``msg`` shares: the original of a
        plain share (section 4.2), else the message itself."""
        if msg.kind == sh.KIND_SHARE and msg.share_of and msg.share_group:
            return msg.share_of, msg.share_group
        return msg.message_id, msg.group

    # --- may it be shared, and where (sections 4.2, 4.4, 5.5, 7.2) -------------------
    def share_permission(self, msg: Message | None) -> Permission:
        """Whether ``msg`` can be shared at all, and if not why - so that clients offer
        no Share where it cannot be done (section 5.5)."""
        if msg is None:
            return Permission(False, "Nothing to share", "target")
        if msg.private or msg.encrypted or not msg.readable:
            return Permission(False, "Closed things are not shared", "closed")
        if msg.kind == "reaction" or msg.page is not None:
            return Permission(False, "That cannot be shared", "target")
        if msg.kind == sh.KIND_SHARE:
            return Permission(True)                   # shares the original (section 4.2)
        data = self.manifest_data(msg.group)
        gtype = data.get("type") or self.group_entry(msg.group).get("type")
        if gtype in ("closed", "inbox", "state"):
            return Permission(False, "Closed things are not shared", "closed")
        if msg.sharing_no or data.get("share_from") is False:
            return Permission(False, "The author asked not to share this", "asked_not")
        return Permission(True)

    def share_into_permission(self, group_id: str, plain: bool = True) -> Permission:
        """Whether you may share into ``group_id``: your own feed always; another group
        if it takes shares, a discussion group only with a comment (section 7.2), and
        if you may start a thread or entry there (UN-RFC 0030)."""
        if group_id == self.personal_group("feed"):
            if not self.has_personal_group("feed"):
                return Permission(False, "Start your feed first", "no_feed")
            return Permission(True)
        data = self.manifest_data(group_id)
        if data.get("type") in ("closed", "inbox", "state") or group_id == self.my_inbox:
            return Permission(False, "Shares go to open groups - use Send to… for one person",
                              "closed")
        if data and not sh.share_into(data):
            return Permission(False, "This group takes no shares", "no_shares")
        if plain and data and not sh.takes_plain(data):
            return Permission(False, "A share into a discussion group needs a comment",
                              "needs_comment")
        base = self.write_permission(group_id, kind=None)
        if not base:
            return base
        return Permission(True)

    def my_shares(self, target_id: str) -> dict[str, str]:
        """Where you have shared ``target_id``: ``{group: your share's Message-ID}``."""
        return dict(self.data.get("shares", {}).get(target_id, {}))

    def share_destinations(self, msg: Message) -> list[dict]:
        """The groups you could share ``msg`` into (section 5.5): your feed, then the
        groups you follow that take shares, each with whether a plain share is allowed
        and whether you already shared it there. Only offered when the limit of section
        7.2 leaves room, or where it is already shared (sharing again replaces it)."""
        tgt_id, tgt_group = self.share_target(msg)
        mine = self.my_shares(tgt_id)
        feed = self.personal_group("feed")
        used = {g for g in mine if g != feed}
        out = []
        for gid in [feed] + sorted(self.data["subscribed"]):
            if gid == tgt_group or any(d["group"] == gid for d in out):
                continue
            plain = self.share_into_permission(gid, plain=True)
            commented = plain if plain else self.share_into_permission(gid, plain=False)
            if not commented and not (gid == feed and commented.code == "no_feed"):
                continue
            if gid != feed and gid not in used and len(used) >= sh.MAX_INTO:
                continue
            out.append({"group": gid, "label": self.group_label(gid), "own_feed": gid == feed,
                        "plain": bool(plain), "allowed": bool(commented),
                        "reason": "" if commented else commented.reason,
                        "shared": gid in mine})
        return out

    # --- sharing (sections 4.3, 4.5, 7) --------------------------------------------
    async def share(self, msg: Message, comment: str = "", *, into: str | None = None,
                    subject: str = "", kind: str | None = None, files=None, card=None,
                    tags=None, languages=None, comment_days: int | None = None) -> str:
        """Share ``msg`` - into your feed, or ``into`` another group - plainly, or with
        ``comment`` (a chat line, or a post when ``subject`` is given or the group takes
        posts only). A plain share of a plain share shares its original (section 4.2);
        sharing again into the same group replaces your earlier share there (4.5).
        Answers the share's Message-ID. Send a notice afterwards with
        ``send_share_notice`` (section 8)."""
        allowed = self.share_permission(msg)
        if not allowed:
            raise SessionError(allowed.reason)
        tgt_id, tgt_group = self.share_target(msg)
        dest = into or self.personal_group("feed")
        comment = (comment or "").strip()
        plain = not comment
        ok = self.share_into_permission(dest, plain=plain)
        if not ok:
            raise SessionError(ok.reason)
        if dest == tgt_group:
            raise SessionError("It is in that group already")
        mine = self.my_shares(tgt_id)
        feed = self.personal_group("feed")
        others = {g for g in mine if g not in (feed, dest)}
        if dest != feed and len(others) >= sh.MAX_INTO:
            raise SessionError(f"You have shared this into {sh.MAX_INTO} groups already - "
                               "undo one of those first")
        earlier = mine.get(dest)
        kinds_of = self.data.setdefault("share_kinds", {})
        # a plain share again: a new version of the earlier one (UN-RFC 0042), which
        # withdraws it - and differs from it, though Dates are rounded to 10 minutes
        replaces = earlier if plain and earlier and kinds_of.get(earlier) == "plain" else None
        me = self.identity()
        if plain:
            try:
                art = await self._post_with_postage(dest, lambda bits: sh.build_plain(
                    dest, tgt_id, tgt_group, from_name=self.display_name(),
                    supersedes=replaces).finalize(me, bits))
            except SessionError as exc:
                if "duplicate" in str(exc):
                    raise SessionError("You took this share back a moment ago - you can "
                                       "share it again in a few minutes") from None
                raise
            new_id = art.message_id
            self._remember_mine(new_id)
        else:
            kinds = self.group_kinds(dest)
            if kind is None:
                kind = KIND_POST if (subject or KIND_CHAT not in kinds) else KIND_CHAT
            if kind == KIND_POST and not subject.strip():
                subject = (msg.subject or "").strip() or "Shared"
            new_id = await self.post(dest, subject if kind == KIND_POST else "", comment + "\n",
                                     kind=kind, extra=sh.headers(tgt_id, tgt_group),
                                     files=files, card=card, tags=tags, languages=languages,
                                     comment_days=comment_days)
        self.data.setdefault("shares", {}).setdefault(tgt_id, {})[dest] = new_id
        kinds_of[new_id] = "plain" if plain else "comment"
        if earlier:
            kinds_of.pop(earlier, None)
        for k in list(kinds_of)[:-1000]:
            kinds_of.pop(k)
        self._note_share(new_id, tgt_id, tgt_group, dest, msg)
        self.save()
        if earlier and earlier != new_id and not replaces:  # one share per group (4.5)
            try:
                await self.withdraw(dest, earlier)
            except (SessionError, NNTPError, OSError, ConnectionError):
                pass
        self.emit(ev.GroupUpdated(dest, 0))
        return new_id

    def _note_share(self, share_id: str, tgt_id: str, tgt_group: str, dest: str,
                    msg: Message) -> None:
        """Remember what a notice for this share needs (section 8), until it is sent."""
        author = msg.author_key if msg.kind != sh.KIND_SHARE else ""
        pending = self.data.setdefault("share_notices_to_send", {})
        pending[share_id] = {"of": tgt_id, "group": tgt_group, "in": dest, "author": author,
                             "subject": msg.subject if msg.kind == KIND_POST else ""}
        for k in list(pending)[:-200]:
            pending.pop(k)

    async def unshare(self, target_id: str, group_id: str | None = None) -> list[str]:
        """Undo your share of ``target_id`` in ``group_id`` (default: everywhere you
        shared it). Answers the groups it was taken back from."""
        mine = self.data.get("shares", {}).get(target_id, {})
        groups = [group_id] if group_id else list(mine)
        done = []
        for gid in groups:
            mid = mine.get(gid)
            if not mid:
                continue
            try:
                await self.withdraw(gid, mid)
            except SessionError:
                pass
            mine.pop(gid, None)
            done.append(gid)
            self.emit(ev.GroupUpdated(gid, 0))
        if not mine:
            self.data.get("shares", {}).pop(target_id, None)
        self.save()
        return done

    async def send_share(self, msg: Message, to: str, comment: str = "",
                         chat: bool = True, *, subject: str = "", files=None,
                         card=None) -> str:
        """Send ``msg`` to one person (section 7.4): a private chat line (or post, with
        ``subject``, ``files`` and ``card`` as any private post) with ``Share-Of``/
        ``Share-Group`` inside the encryption. No notice, no limit."""
        allowed = self.share_permission(msg)
        if not allowed:
            raise SessionError(allowed.reason)
        tgt_id, tgt_group = self.share_target(msg)
        try:
            owner = crypto.key_from_text(to)
        except crypto.CryptoError:
            raise SessionError("send to whom? a key, like ed25519:...") from None
        body = (comment or "").strip() or sh.address(tgt_group, tgt_id)
        subject = "" if chat else (subject.strip() or msg.subject or "Shared")
        return await self.send_private(
            personal_inbox_id(owner), subject, body + "\n",
            owner_key=owner, kind=KIND_CHAT if chat else KIND_POST,
            extra=sh.headers(tgt_id, tgt_group), files=files, card=card)

    # --- fetching the original (section 6.3) ---------------------------------------
    def _share_cache(self) -> dict:
        if not hasattr(self, "_share_targets"):
            self._share_targets: dict[tuple[str, str], tuple[float, dict]] = {}
        return self._share_targets

    def _check_target(self, raw: bytes, share_of: str, share_group: str) -> Article | None:
        """Section 6.3 step 3: signature, the group, and the article or a newer version
        of it - a node is not trusted for this."""
        try:
            raw = strip_reader_headers(raw)
            art = Article.from_bytes(raw)
            validate_structure(art, raw_size=len(raw))
        except (ArticleError, ValueError):
            return None
        if (art.get("Newsgroups") or "").strip() != share_group or art.control is not None:
            return None
        if "Encrypted" in art:
            return None
        if art.message_id == share_of:
            return art
        try:
            return art if share_of in parse_supersedes(art) else None
        except ArticleError:
            return None

    def _held_target(self, share_of: str, share_group: str) -> Message | None:
        """The original from what this client already has, its newest version."""
        msgs = list(self.cache.get(share_group, {}).values())
        for m in msgs:
            if m.message_id == share_of or share_of in m.supersedes or share_of in m.versions:
                newer = [x for x in msgs if m.message_id in x.supersedes]
                return newer[-1] if newer else m
        return None

    def _withdrawn_here(self, share_of: str, share_group: str) -> bool:
        return share_of in self.group_entry(share_group).get("cancels", {}) \
            if share_group in self.data["groups"] else False

    def share_target_state(self, share_of: str, share_group: str) -> dict | None:
        """What is known already, without asking a node: the dict
        ``fetch_share_target`` would answer, or None."""
        held = self._held_target(share_of, share_group)
        if held is not None:
            return {"state": "ok", "message": held}
        if self._withdrawn_here(share_of, share_group):
            return {"state": "withdrawn", "message": None}
        hit = self._share_cache().get((share_of, share_group))
        if hit is not None and hit[0] > time.monotonic():
            return hit[1]
        return None

    async def fetch_share_target(self, share_of: str, share_group: str,
                                 patience: float | None = None) -> dict:
        """The article a share refers to (section 6.3), checked by this client:
        ``{"state": "ok", "message": Message}``, or a state with no message -
        ``"withdrawn"`` (by its author), ``"gone"`` (no longer in the network) or
        ``"unavailable"`` (not right now). ``"fetching"`` while a node is still at it
        and ``patience`` (seconds, default a minute) ran out."""
        known = self.share_target_state(share_of, share_group)
        if known is not None:
            return known
        patience = FETCH_PATIENCE if patience is None else patience
        first = self.node_for(share_group) if share_group in self.data["subscribed"] else self.node
        nodes = [first] + [n for n in self.nodes if n != first]
        result: dict = {"state": "unavailable", "message": None}

        async def ask(address: str) -> tuple[int, bytes | None]:
            async def run(c: Client):
                return await c.fetch(share_of, share_group)
            return await self._call(run, address)

        deadline = time.monotonic() + patience
        for address in [n for n in nodes if n]:
            while True:
                try:
                    code, raw = await ask(address)
                except (SessionError, NNTPError, OSError, ConnectionError,
                        asyncio.IncompleteReadError, asyncio.TimeoutError):
                    code, raw = 0, None
                if code == 436 and time.monotonic() + FETCH_RETRY < deadline:
                    await asyncio.sleep(FETCH_RETRY)
                    continue
                break
            if code == 220 and raw is not None:
                art = self._check_target(raw, share_of, share_group)
                if art is None:
                    continue                          # a node that lies: try another
                entry = {"type": None, "owner": False, "keys": {}}
                msg = self._parse(0, strip_reader_headers(raw), share_group, entry,
                                  self.identity())
                if msg is None or msg.encrypted:
                    continue
                result = {"state": "ok", "message": msg}
                break
            if code == 436:
                result = {"state": "fetching", "message": None}
                continue
            if code == 430 and share_group in self.data["subscribed"] \
                    and address == self.node_for(share_group):
                result = {"state": "gone", "message": None}      # it carries it: final
                break
            if code == 430:
                result = {"state": "gone", "message": None}
        if result["state"] in ("ok", "gone"):
            self._share_cache()[(share_of, share_group)] = (time.monotonic() + TARGET_TTL, result)
        return result

    def edited_after_shared(self, share: Message, target: Message | None) -> bool:
        """Section 5.1: the original shown is a version newer than the share."""
        if target is None or share.share_of is None or target.message_id == share.share_of:
            return False
        stamp = target.edited or target.date
        return bool(stamp and share.date and stamp > share.date)

    # --- share notices (section 8) ---------------------------------------------------
    def share_notices_on(self) -> bool:
        """Whether you take share notices (on by default, UN-RFC 0044 ``share_notices``)."""
        return bool(self.data.get("share_notices", True))

    def set_share_notices(self, on: bool) -> None:
        """Take share notices or not (section 8); kept in your state (UN-RFC 0044)."""
        self.data["share_notices"] = bool(on)
        self.save()

    async def send_share_notice(self, share_id: str, delay: float | None = None) -> bool:
        """Tell the author of what you shared (section 8): one notice per share into a
        feed or group, none for your own post or an author whose inbox is unknown.
        Waits a random time first unless ``delay`` is given."""
        pending = self.data.get("share_notices_to_send", {})
        info = pending.get(share_id)
        if not info:
            return False
        author = info.get("author") or ""
        if not author:
            got = await self.fetch_share_target(info["of"], info["group"])
            m = got.get("message")
            if m is None:
                return False
            author = m.author_key
            info["subject"] = m.subject if m.kind == KIND_POST else ""
        pending.pop(share_id, None)
        self.save()
        if not author or author == self.identity().key_text or not self.may_notify(info["group"]):
            return False
        if delay is None:
            delay = random.uniform(5, 120)
        if delay:
            await asyncio.sleep(delay)
        try:
            owner = crypto.key_from_text(author)
        except crypto.CryptoError:
            return False
        where = "in their feed" if info["in"] == self.personal_group("feed") else \
            f"in !{self.group_label(info['in'])}"
        subject = (info.get("subject") or "").strip()
        try:
            await self.send_private(
                personal_inbox_id(owner), subject or "Share",
                sh.notice_line(self.display_name(), where, subject) + "\n", owner_key=owner,
                content_type=sh.NOTICE_TYPE + "; charset=utf-8", remember=False,
                extra=sh.notice_headers(info["of"], info["group"], share_id, info["in"])[1:])
        except (SessionError, OSError, ConnectionError, crypto.CryptoError, ValueError) as exc:
            log.debug("share notice not sent: %s", exc)
            return False
        return True

    @staticmethod
    def is_share_notice(m: Message) -> bool:
        """True when a private post is a share notice (section 8): it names the share,
        where it is, and what it shares."""
        return bool(m.private and m.shared_as and m.shared_in and m.share_of)

    async def check_share_notices(self) -> int:
        """Check new share notices (section 8): fetch the share and keep the notice
        only if it is by the notice's sender and shares one of your articles."""
        if not self.share_notices_on() or not self.my_inbox:
            return 0
        states = self.data.setdefault("share_notice_states", {})
        mine = {self.identity(n).key_text for n in self.data["identities"]}
        good = 0
        for m in list(self.cache.get(self.my_inbox, {}).values()):
            if not self.is_share_notice(m):
                continue
            st = states.get(m.message_id, {})
            if st.get("state") in ("ok", "bad") or st.get("tries", 0) >= 5:
                continue
            if not m.sender_key or self.is_ignored(m.sender_key):
                states[m.message_id] = {"state": "bad"}
                continue
            share = await self._fetch_by_id(m.shared_in, m.shared_as)
            if share is None:
                states[m.message_id] = {"state": "pending", "tries": st.get("tries", 0) + 1}
                continue
            target = None
            if share.share_of == m.share_of and share.share_group == m.share_group:
                target = self._held_target(m.share_of, m.share_group)
                if target is None:
                    got = await self.fetch_share_target(m.share_of, m.share_group)
                    target = got.get("message")
            ok = (share.author_key == m.sender_key and target is not None
                  and target.author_key in mine)
            states[m.message_id] = ({"state": "ok", "share": share.message_id,
                                     "in": m.shared_in, "of": m.share_of,
                                     "group": m.share_group, "from": share.from_name,
                                     "subject": target.subject if target else ""}
                                    if ok else {"state": "bad"})
            good += ok
        if len(states) > 2000:
            for k in list(states)[:-2000]:
                states.pop(k)
        self.save()
        return good

    def share_notices(self) -> list[Message]:
        """Checked share notices in your inbox, for For you (never a count)."""
        if not self.share_notices_on():
            return []
        states = self.data.get("share_notice_states", {})
        return [m for m in self.visible(list(self.cache.get(self.my_inbox, {}).values()))
                if self.is_share_notice(m) and states.get(m.message_id, {}).get("state") == "ok"
                and not self.is_ignored(m.sender_key or "")]

    # --- hiding plain shares, and the timeline (section 5.4) -------------------------
    def hidden_shares(self) -> dict:
        """``{"all": bool, "groups": [...]}`` - where you hide plain shares
        (UN-RFC 0044 ``hide_shares``)."""
        h = self.data.get("hide_shares") or {}
        return {"all": bool(h.get("all", False)), "groups": list(h.get("groups", []))}

    def set_hide_shares(self, group_id: str | None = None, hide: bool = True) -> dict:
        """Hide plain shares in one feed (``group_id``) or everywhere (None)."""
        h = self.hidden_shares()
        if group_id is None:
            h["all"] = bool(hide)
        elif hide and group_id not in h["groups"]:
            h["groups"].append(group_id)
        elif not hide and group_id in h["groups"]:
            h["groups"].remove(group_id)
        self.data["hide_shares"] = h
        self.save()
        return h

    def hides_shares(self, group_id: str) -> bool:
        """Whether plain shares in ``group_id`` are hidden from you (section 5.4)."""
        h = self.hidden_shares()
        return h["all"] or group_id in h["groups"]

    def _merge_shares(self, rows: list[Message]) -> list[Message]:
        """Section 5.4: each original once, at the newest time it came in - from its own
        group or as plain shares -, naming the sharers whose groups are in the timeline.
        A share with a comment is the sharer's own entry and stays as it is. Plain
        shares you hide, and those whose original is known gone, are left out."""
        by_target: dict[str, list[Message]] = {}
        for m in rows:
            if m.kind == sh.KIND_SHARE and m.share_of:
                if self.hides_shares(m.group):
                    continue
                state = self.share_target_state(m.share_of, m.share_group or "")
                if state is not None and state["state"] in ("withdrawn", "gone"):
                    continue
                by_target.setdefault(m.share_of, []).append(m)
        out = []
        for m in rows:
            if m.kind == sh.KIND_SHARE:
                shares = by_target.get(m.share_of or "")
                if not shares or m is not shares[0]:
                    continue                      # hidden, gone, or not the newest share
                names = []
                for x in shares:
                    label = x.from_name or self.identity_label(x.author_key, x.from_name)
                    if label not in names:
                        names.append(label)
                m.shared_by = names
                out.append(m)
            elif m.message_id in by_target:
                continue                          # shown once, where it was shared last
            else:
                out.append(m)
        return out
