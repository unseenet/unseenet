"""Posting and postage. Part of Session (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class PostingMixin:
    # ------------------------------------------------------------------
    # posting
    # ------------------------------------------------------------------
    async def _post_article(self, art: Article, node: str | None = None) -> str:
        name = self._identity_named_by(art.author_key)
        # a node from before UN-RFC 0025 gets no header: it would break the signature
        minimum = await self.node_min_ripe(node or self.node_for(art.group)) \
            if name is not None else None
        if minimum is None:
            art.remove("Key-Ripening")
        elif art.group == self.ripe_group(name):
            if not art.get("Key-Ripening"):            # e.g. a renewal: name its own chain's end
                obj = json.loads(art.body).get("ripening")
                if obj:
                    art.set("Key-Ripening", rp.Chain.from_manifest(obj).header())
        else:
            if minimum != "-":
                await self.ensure_ripe(name)           # level 0 and ripe@ first (UN-RFC 0025)
            header = self.ripening_header(name)
            if header:                                 # outside the canonical form: signing holds
                art.set("Key-Ripening", header)
        try:
            return await self._send_article(art, node)
        except SessionError as exc:
            if name is None or "ripening: unknown" not in str(exc) \
                    or art.group == self.ripe_group(name):
                raise
            await self.publish_ripening(name, node)    # this node lacks our chain: send it
            return await self._send_article(art, node)

    async def post_article(self, art: Article, node: str | None = None,
                           sign_with: crypto.Identity | None = None) -> str:
        """Post an article built elsewhere (a gateway's imports, a registrar's
        answers, a bot's posts), as everything else is posted: ripening first where
        the node asks for it, Key-Ripening set, our chain sent to a node that lacks
        it. Returns the Message-ID; raises SessionError if refused.

        With ``sign_with``, the article is signed here with the postage this node
        and group need for that key's level (UN-RFC 0025 section 5), and once more
        if the node asks for more. Without it, it must be signed already."""
        if sign_with is None:
            return await self._post_article(art, node)
        target = node or self.node_for(art.group)
        name = self._identity_named_by(sign_with.public_key)
        if name is not None and await self.node_wants_ripening(target):
            await self.ensure_ripe(name, target)   # the level decides the postage
        bits = await self.postage_for(art, target)
        for attempt in (1, 2):
            if (not art.get("Signature") or art.proven_pow() < bits
                    or art.author_key != sign_with.public_key):
                await self._compute(lambda: art.finalize(sign_with, bits))
            try:
                return await self._post_article(art, node)
            except SessionError as exc:
                need = _needed_bits(str(exc))
                if attempt == 2 or need <= bits:
                    raise
                bits = need                        # the node wants more: once more
        raise AssertionError("unreachable")

    async def postage_for(self, art, node: str | None = None) -> int:
        """The postage for an article (or a group ID) on this node: a manifest or a
        removal pays only the node's minimum; anything else the group's too, which
        is learned from the network if we don't have it, rather than guessed high
        (a guess of 20 bits plus a surcharge is a minute of work in Python)."""
        if isinstance(art, Article):
            control = (art.get("Control") or "").split()[:1]
            group = None if control in (["manifest"], ["rmgroup"]) else art.group
        else:
            group = art
        if group and not self.manifest_data(group):
            try:
                m = await self.fetch_manifest(group, node=node)
            except (SessionError, OSError, ConnectionError, asyncio.IncompleteReadError):
                m = None
            if m is not None:
                self.group_entry(group)["manifest"] = dict(m.raw)
        return await self.required_pow(group, node=node)

    async def _send_article(self, art: Article, node: str | None = None) -> str:
        raw = art.to_bytes()
        target = node or self.node_for(art.group)
        code, text = await self._call(lambda c: c.post(raw), target)
        if code != 240 and node is None and "not carried" in text:
            for other in (n for n in self.nodes if n != target):   # e.g. someone's inbox elsewhere
                try:
                    code, text = await self._call(lambda c: c.post(raw), other)
                except (OSError, ConnectionError, SessionError, asyncio.IncompleteReadError):
                    continue
                if code == 240:
                    if art.group in self.data["groups"]:
                        self.pin_group(art.group, other)
                    break
        if code != 240:
            raise SessionError(f"rejected by node: {text}")
        return art.message_id

    async def edit(self, msg: Message, subject: str, body: str,
                   content_type: str | None = None) -> str:
        """Post a new version of your own post or chat line (UN-RFC 0042 section 4.3):
        same group, kind and place in its thread, naming every earlier version."""
        if msg.private:
            raise SessionError("private posts cannot be edited")
        if msg.author_key != self.identity().key_text:
            raise SessionError("you can only edit your own posts")
        versions = [msg.message_id] + [v for v in msg.versions if v != msg.message_id]
        if len(versions) > MAX_SUPERSEDES:
            raise SessionError(f"a post can be edited at most {MAX_SUPERSEDES} times")
        original = self.find_message(msg.group, msg.message_id) or msg   # its own References
        return await self.post(msg.group, subject, body, references=original.references or None,
                               kind=msg.kind, content_type=content_type or msg.content_type or None,
                               supersedes=versions)

    def may_edit(self, msg: Message) -> bool:
        return (not msg.private and msg.readable and bool(msg.author_key)
                and msg.author_key == self.identity().key_text
                and len(msg.versions) + 1 <= MAX_SUPERSEDES)

    async def post(self, group_id: str, subject: str, body: str,
                   references: list[str] | None = None, kind: str = KIND_POST,
                   content_type: str | None = None,
                   supersedes: list[str] | None = None,
                   extra: list[tuple[str, str]] | None = None,
                   from_name: str | None = None) -> str:
        """Post to a group: a post (with a subject) or a chat line (UN-RFC 0028).

        ``extra`` are more headers, for a program's own (``X-``, ``Gateway-*``,
        UN-RFC 0046 section 4.9); ``from_name`` replaces your display name."""
        if self.portal_warning(group_id):
            # Clients ask first (portal_warning / accept_portals); this is the safety net.
            raise SessionError("this group has a portal: its posts are also published outside "
                               "Tor, and you have not accepted that yet")
        if kind not in self.group_kinds(group_id):
            raise SessionError("this group does not take " +
                               ("chat lines" if kind == KIND_CHAT else "posts with a subject"))
        if kind == KIND_POST and not subject.strip():
            raise SessionError("a post needs a subject")
        content_type = content_type or self.text_type()      # Markdown by default (UN-RFC 0031)
        edit_header = [("Supersedes", " ".join(supersedes))] if supersedes else []   # 0042
        edit_header += list(extra or [])
        shown = from_name or self.display_name()
        author = self.identity()
        entry = self.group_entry(group_id)
        cert = None
        if entry.get("type") == "closed":
            if not entry["keys"]:
                raise SessionError("you are not a member of this closed group")
            epoch = max(int(e) for e in entry["keys"])
            keys = crypto.GroupKeys(bytes.fromhex(entry["keys"][str(epoch)]))

            def build(bits):                       # postage is CPU work: runs in a thread
                return encrypted_article(
                    group_id, epoch, keys, author, from_name=shown,
                    subject=subject, body=body, references=references, kind=kind,
                    content_type=content_type, pow_bits=bits, extra=edit_header)
        else:
            cert = naming.header_for(self, group_id)     # your name, once a week here (UN-RFC 0019)

            def build(bits):
                # a chat line has an empty subject; the kind is a header (UN-RFC 0028, 3.2-3.3)
                art = new_article(group_id, "" if kind == KIND_CHAT else subject, body,
                                  from_name=shown, references=references,
                                  extra=[("Content-Type", content_type), ("Message-Kind", kind)]
                                  + ([cert] if cert else []) + edit_header)
                return art.finalize(author, bits)
        gtype = self.manifest_data(group_id).get("type") or entry.get("type")
        if gtype == "moderated" and not self.moderates(group_id):
            return await self._submit(group_id, subject, build)
        msgid = (await self._post_with_postage(group_id, build)).message_id
        self._remember_mine(msgid)
        if cert:
            naming.sent_header(self, group_id)
        marks = self.data["read"].setdefault(group_id, [])   # your own posts are read
        marks.append(msgid)
        self.save()
        return msgid
