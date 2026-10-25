"""Reactions (UN-RFC 0048): counting them under articles, and reacting.

Belongs here: the reactions a group holds - kept beside ``cache``, never in it, so no
view can show them as posts (``_take_reaction``) -, what a group takes
(``reaction_set``), whether you may react (``react_permission``), the counts under an
article (``reactions_on``), and reacting, changing and taking back (``react``).

Not here: the rules themselves (core/reactions.py), drawing the counts (the clients).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from ...core import reactions as rx


class ReactionsMixin:
    # --- the reactions a group holds ---
    def _reactions_of(self, group_id: str) -> dict[int, Message]:
        return self.reaction_msgs.setdefault(group_id, {})

    def _take_reaction(self, group_id: str, n: int, msg: Message) -> bool:
        """Keep a reaction apart from the posts; True if ``msg`` is one."""
        if msg.kind != rx.KIND_REACTION or not msg.readable:
            return False
        self._reactions_of(group_id)[n] = msg
        return True

    def _cancel_reactions(self, group_id: str, cancels: dict, privileged: set) -> bool:
        """Cancels of reactions (UN-RFC 0048 section 5): valid from the reaction's
        author, the owner or a moderator. True if anything changed."""
        held = self._reactions_of(group_id)
        by_id = {m.message_id: n for n, m in held.items()}
        changed = False
        for target, c in list(cancels.items()):
            n = by_id.get(target)
            if n is None:
                continue
            if c.get("by") == held[n].author_key or c.get("by") in privileged:
                gone = held.pop(n)
                self._raw.get(group_id, {}).pop(n, None)
                # the reactions it replaced go too, or they would count again (as for
                # edits, UN-RFC 0042 section 4.2)
                for v in gone.supersedes:
                    vn = by_id.get(v)
                    if vn in held and held[vn].author_key == gone.author_key:
                        del held[vn]
                        self._raw.get(group_id, {}).pop(vn, None)
                changed = True
            del cancels[target]
            changed = True
        return changed

    # --- what a group takes (section 4) ---
    def reaction_set(self, group_id: str) -> rx.ReactionSet:
        """The emoji a group takes, from its cached manifest (none if unknown)."""
        entry = self.data["groups"].get(group_id, {})
        data = dict(self.manifest_data(group_id) or {})
        data.setdefault("type", entry.get("type"))
        if not data.get("type"):
            return rx.NONE
        return rx.reaction_set(data)      # the owner's view decides the default, not ours

    def react_permission(self, group_id: str, msg: Message | None = None) -> "Permission":
        """Whether you may react here (to ``msg``), and if not why - so that clients
        offer no reaction controls where reacting is impossible (section 7.3)."""
        if group_id == self.my_inbox or (msg is not None and msg.private):
            return Permission(False, "Reactions to private posts come in a later version",
                              "private")
        if msg is not None and (msg.kind == rx.KIND_REACTION or not msg.readable):
            return Permission(False, "You cannot react to that", "target")
        if msg is not None and msg.author_key and msg.author_key == self._my_key_text():
            # your own post, comment or chat line: a like from yourself says nothing
            # to anyone and only inflates the count (#524)
            return Permission(False, "You cannot react to your own post", "own")
        if not self.reaction_set(group_id):
            return Permission(False, "This group takes no reactions", "no_reactions")
        entry = self.data["groups"].get(group_id, {})
        data = entry.get("manifest") or {}
        gtype = data.get("type") or entry.get("type")
        if gtype == "channel":            # not a comment: only bans, blocks and comment_days
            base = self.write_permission(group_id, kind=None)
            if not base and base.code not in ("channel", "channel_thread"):
                return base
            days = data.get("comment_days")
            root = self.find_message(group_id, msg.thread_root) if msg is not None else None
            if (isinstance(days, int) and root is not None and root.date is not None
                    and datetime.now(timezone.utc) > root.date + timedelta(days=days)):
                return Permission(False, "Reactions on this thread have closed",
                                  "comments_closed")
            return Permission(True)
        base = self.write_permission(group_id, kind=None)
        return base

    def _my_key_text(self) -> str | None:
        """Your key, or None before a vault is open."""
        try:
            return self.identity().key_text
        except Exception:
            return None

    # --- counting (sections 5 and 7.1) ---
    def all_reactions(self, group_id: str) -> dict[str, rx.Counts]:
        """{Message-ID of an article: its reactions}. A reaction to an earlier version
        of an edited post counts for the version shown (UN-RFC 0042)."""
        alias = {v: m.message_id for m in self.cache.get(group_id, {}).values()
                 for v in m.versions}
        # who wrote each article: a reaction from its own author is not counted
        # (UN-RFC 0048 section 3.3)
        author = {m.message_id: m.author_key for m in self.cache.get(group_id, {}).values()}
        held = self._reactions_of(group_id).values()
        # a changed reaction names the one it replaces (section 5): that one is gone,
        # even before the cancel-like withdrawal reaches us (Dates are rounded)
        replaced = {v for m in held for v in m.supersedes}
        items, seen = [], set(replaced)
        for m in held:
            if m.message_id in seen or not m.references:
                continue
            seen.add(m.message_id)
            tgt = m.references[-1]
            if m.author_key and author.get(alias.get(tgt, tgt)) == m.author_key:
                continue
            when = int(m.date.timestamp()) if m.date else 0
            items.append((m.message_id, m.author_key, when, alias.get(tgt, tgt), m.reaction))
        return rx.count(items)

    def reactions_on(self, msg: Message) -> rx.Counts:
        """The reactions under one article (empty Counts if none)."""
        return self.all_reactions(msg.group).get(msg.message_id) or rx.Counts()

    def who_reacted(self, msg: Message, emoji: str) -> list[str]:
        """Who gave ``emoji`` to ``msg``: names or fingerprints (section 7.2)."""
        counts = self.reactions_on(msg)
        keys = next((v for e, v in counts.by_emoji.items() if rx.same_emoji(e, emoji)), [])
        names = {m.author_key: m.from_name for m in self._reactions_of(msg.group).values()}
        return [self.identity_label(k, names.get(k, "")) for k in keys]

    # --- reacting (section 7.3) ---
    async def react(self, msg: Message, emoji: str) -> str | None:
        """React to ``msg`` with ``emoji``; the emoji you already gave takes it back,
        another one changes it (section 5). Answers the new reaction's Message-ID,
        or None when it was taken back."""
        group_id = msg.group
        allowed = self.react_permission(group_id, msg)
        if not allowed:
            raise SessionError(allowed.reason)
        if not self.reaction_set(group_id).takes(emoji):
            raise SessionError("this group does not take that reaction")
        me = self.identity()
        mine = self.reactions_on(msg).by_key.get(me.key_text)
        if mine and rx.same_emoji(mine[0], emoji):
            await self._withdraw_reaction(group_id, mine[1])
            return None
        entry = self.group_entry(group_id)
        refs = [*msg.references, msg.message_id]
        extra = [("Supersedes", mine[1])] if mine else []
        if entry.get("type") == "closed":
            if not entry.get("keys"):
                raise SessionError("you are not a member of this closed group")
            epoch = max(int(e) for e in entry["keys"])
            keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))

            def build(bits):
                return encrypted_article(
                    group_id, epoch, keys, me, from_name=self.display_name(), subject="",
                    body=emoji + "\n", references=refs, kind=rx.KIND_REACTION,
                    pow_bits=bits, extra=extra, inner_extra=[(rx.HEADER, emoji)])
        else:
            def build(bits):
                return rx.build(group_id, msg.references, msg.message_id, emoji,
                                from_name=self.display_name(),
                                supersedes=mine[1] if mine else None).finalize(me, bits)
        art = await self._post_with_postage(group_id, build)
        self._remember_mine(art.message_id)
        held = self._reactions_of(group_id)
        if mine:                                 # the edit withdraws the old one
            for n in [n for n, m in held.items() if m.message_id == mine[1]]:
                del held[n]
        local = -1 - len(held)
        while local in held:
            local -= 1
        held[local] = Message(local, art.message_id, group_id, author_key=me.key_text,
                              references=refs, date=parse_date(art["Date"]),
                              kind=rx.KIND_REACTION, reaction=emoji,
                              supersedes=[mine[1]] if mine else [])
        self.emit(ev.GroupUpdated(group_id, 0))
        return art.message_id

    async def _withdraw_reaction(self, group_id: str, message_id: str) -> None:
        me = self.identity()
        await self._post_with_postage(group_id, lambda bits: new_article(
            group_id, None, "", extra=[("Control", f"cancel {message_id}")]).finalize(me, bits))
        held = self._reactions_of(group_id)
        gone = {message_id}
        for m in list(held.values()):
            if m.message_id == message_id:
                gone.update(m.supersedes)          # what it replaced goes with it
        for n in [n for n, m in held.items() if m.message_id in gone]:
            del held[n]
            self._raw.get(group_id, {}).pop(n, None)
        self.emit(ev.GroupUpdated(group_id, 0))
