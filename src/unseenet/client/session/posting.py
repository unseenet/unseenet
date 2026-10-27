"""Posting: writing to the network, and taking it back.

Belongs here: posting a post or chat line (``post``), postage (UN-RFC 0006, with the
ripening level, 0025 section 5), posting articles built elsewhere (``post_article``,
for bots, gateways and the local API), editing (``edit``, UN-RFC 0042) and
withdrawing (``withdraw``, ``cancel``, UN-RFC 0004 section 7).

Not here: private posts (private.py), group settings (groups.py).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class PostingMixin:
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

    async def _post_with_postage(self, group_id: str, build, blobs=()) -> Article:
        """Build with ``build(bits)`` and post; if the node asks for more postage
        ("need N bits"), rebuild once with N and post again. Returns the posted article.
        ``blobs``: ``(blob id, octets)`` staged before the post on the same connection."""
        bits = await self.required_pow(group_id)
        art = await self._compute(lambda: build(bits))
        try:
            await self._post_article(art, blobs=blobs)
            return art
        except SessionError as exc:
            m = re.search(r"need (\d+) bits", str(exc))
            if not m or int(m.group(1)) <= bits or int(m.group(1)) > 28:
                raise
            need = int(m.group(1))
        self.say(f"Node wants {need} bits of postage, computing again ...")
        art = await self._compute(lambda: build(need))
        await self._post_article(art, blobs=blobs)
        entry = self.data["groups"].get(group_id)
        if entry is not None:                      # remember it for next time
            entry.setdefault("manifest", {})
            if int(entry["manifest"].get("min_pow", 0)) < need:
                entry["manifest"]["min_pow"] = need
        return art

    def may_cancel(self, msg: Message) -> bool:
        """Your own post, or any post in a group you own or moderate (UN-RFC 0004, 7.1)."""
        if msg is None or msg.private or msg.group not in self.data["groups"]:
            return False
        me = self.identity().key_text
        manifest = self.manifest_data(msg.group)
        return msg.author_key == me or manifest.get("owner") == me \
            or me in manifest.get("moderators", [])

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

    async def withdraw_all(self, group_id: str, keep=(), reason: str = "",
                           keep_authors=()) -> list[str]:
        """Owner or moderator: withdraw every post in the group but those in ``keep``,
        and those by the keys in ``keep_authors`` (for example a demo's weekly reset,
        which keeps its own people's posts). Returns the Message-IDs withdrawn."""
        if not self.moderates_or_owns(group_id):
            raise SessionError("only the owner or a moderator can withdraw all posts")
        await self.fetch_group(group_id)
        authors = set(keep_authors)
        done = []
        for msg in list(self.cache.get(group_id, {}).values()):
            if msg.message_id in keep or msg.author_key in authors:
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
        changed = self._cancel_reactions(group_id, cancels, privileged)   # UN-RFC 0048, 5
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

    # ------------------------------------------------------------------
    # posting
    # ------------------------------------------------------------------
    async def _post_article(self, art: Article, node: str | None = None, blobs=()) -> str:
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
            return await self._send_article(art, node, blobs)
        except SessionError as exc:
            if _too_old(str(exc)) and self._redate(art, name):
                return await self._send_article(art, node, blobs)
            if name is None or "ripening: unknown" not in str(exc) \
                    or art.group == self.ripe_group(name):
                raise
            await self.publish_ripening(name, node)    # this node lacks our chain: send it
            return await self._send_article(art, node, blobs)

    def _redate(self, art: Article, name: str | None) -> bool:
        """UN-RFC 0049 section 3.4: refused with ``441 date`` because it waited more than
        an hour (a queue, a long ripening, offline) - give it the time of posting and sign
        it again with the same postage, which makes a new Message-ID. Not for an article
        a member key signed too (closed groups), nor a moderator's approval, whose Date
        is the author's. True if it was done."""
        if name is None or art.get("Member-Signature") or art.get("Approved-By"):
            return False
        from ...core.article import format_date
        bits = art.proven_pow()
        art.set("Date", format_date(datetime.now(timezone.utc)))
        art.finalize(self.identity(name), bits)
        return True

    async def post_article(self, art: Article, node: str | None = None,
                           sign_with: crypto.Identity | None = None, *,
                           blobs=(), extra_bits: int = 0) -> str:
        """Post an article built elsewhere (a gateway's imports, a registrar's
        answers, a bot's posts), as everything else is posted: ripening first where
        the node asks for it, Key-Ripening set, our chain sent to a node that lacks
        it. Returns the Message-ID; raises SessionError if refused.

        With ``sign_with``, the article is signed here with the postage this node
        and group need for that key's level (UN-RFC 0025 section 5), and once more
        if the node asks for more. Without it, it must be signed already.

        ``blobs`` are ``(blob ID, octets)`` for the files the article's ``Blobs`` and
        ``Attachment-<n>`` headers name; they are sent first on the same connection
        (``BLOBPOST``, UN-RFC 0027 section 6). ``extra_bits`` is the postage the
        files add (section 4.5, ``core.blobs.extra_bits_for``), paid on top."""
        blobs = list(blobs)
        if sign_with is None:
            return await self._post_article(art, node, blobs)
        target = node or self.node_for(art.group)
        name = self._identity_named_by(sign_with.public_key)
        if name is not None and await self.node_wants_ripening(target):
            await self.ensure_ripe(name, target)   # the level decides the postage
        bits = await self.postage_for(art, target) + extra_bits
        for attempt in (1, 2):
            if (not art.get("Signature") or art.proven_pow() < bits
                    or art.author_key != sign_with.public_key):
                await self._compute(lambda: art.finalize(sign_with, bits))
            try:
                return await self._post_article(art, node, blobs)
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

    async def _send_article(self, art: Article, node: str | None = None, blobs=()) -> str:
        raw = art.to_bytes()
        target = node or self.node_for(art.group)

        async def send(c):
            for bid, octets in blobs:              # staged on this connection (UN-RFC 0027, 6)
                code, text = await c.blobpost(bid, octets)
                if code != 245:
                    return code, _blob_refusal(text)
            return await c.post(raw)

        code, text = await self._call(send, target)
        if code != 240 and node is None and "not carried" in text:
            for other in (n for n in self.nodes if n != target):   # e.g. someone's inbox elsewhere
                try:
                    code, text = await self._call(send, other)
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
                   content_type: str | None = None, files=None) -> str:
        """Post a new version of your own post or chat line (UN-RFC 0042 section 4.3):
        same group, kind and place in its thread, naming every earlier version.

        ``files``: prepared files for the new version; ``None`` keeps the files of
        the earlier version (fetched and sent again with it, #496), ``[]`` none."""
        if msg.private:
            raise SessionError("private posts cannot be edited")
        if msg.author_key != self.identity().key_text:
            raise SessionError("you can only edit your own posts")
        versions = [msg.message_id] + [v for v in msg.versions if v != msg.message_id]
        if len(versions) > MAX_SUPERSEDES:
            raise SessionError(f"a post can be edited at most {MAX_SUPERSEDES} times")
        original = self.find_message(msg.group, msg.message_id) or msg   # its own References
        if files is None:
            files = await self._files_of(msg)
        return await self.post(msg.group, subject, body, references=original.references or None,
                               kind=msg.kind, content_type=content_type or msg.content_type or None,
                               supersedes=versions, files=files or None)

    async def _files_of(self, msg: Message) -> list:
        """The files a post carries, as prepared files to send again with a new version."""
        from ..media import Prepared
        out = []
        for a in msg.attachments or []:
            octets = await self.fetch_blob(msg.group, a["blob"])
            dim = tuple(a["dim"]) if a.get("dim") else None
            out.append(Prepared(a.get("name") or "file", a["type"], octets,
                                alt=a.get("alt") or "", dim=dim))
        return out

    def may_edit(self, msg: Message) -> bool:
        """True when you may publish a new version of this post (UN-RFC 0042): your own,
        public, readable, and not past the number of versions an edit may name."""
        return (not msg.private and msg.readable and bool(msg.author_key)
                and msg.author_key == self.identity().key_text
                and len(msg.versions) + 1 <= MAX_SUPERSEDES)

    # --- the language of what you write (UN-RFC 0052 section 5a) ---
    def remember_languages(self, group_id: str, languages) -> None:
        """What you chose to write in, in a group - offered there next time; ``[]``
        forgets it. Kept in your settings (UN-RFC 0044), never published."""
        from ...core import tags as tg
        mem = self.data.setdefault("languages_by_group", {})
        codes = tg.normalize_languages(languages)
        if codes:
            mem[group_id] = codes
        else:
            mem.pop(group_id, None)

    def choose_chat_language(self, group_id: str, languages) -> None:
        """What you chose to write your chat lines and comments in, in a group - it wins
        over everything the client would suggest for them there; ``[]`` takes the choice
        back. Kept in your settings (UN-RFC 0044), never published (UN-RFC 0052 5a)."""
        from ...core import tags as tg
        chosen = self.data.setdefault("chat_languages", {})
        codes = tg.normalize_languages(languages)
        if codes:
            chosen[group_id] = codes
        else:
            chosen.pop(group_id, None)
        self.save()

    def suggest_languages(self, group_id: str, text: str | None = None, reply_to=None,
                          kind: str = "post") -> tuple[list[str], str]:
        """What to suggest you write in, and why (UN-RFC 0052 section 5a, #686) - only a
        suggestion; you always decide:

        - a **post**: the text, when it tells for sure (``"text"``); else the group's
          ``languages`` (``"group"``); else what you chose there last (``"you"``); else a
          one-language profile (``"profile"``); else ``([], "")`` - better none than wrong;
        - a **comment** (``reply_to``, a Message): the language of the post it answers
          (``"answered"``) - a comment is too short to tell - else as a post;
        - your **choice** for chat lines and comments in the group
          (``choose_chat_language``) wins for them (``"chosen"``);
        - a **chat line** (``kind="chat"``): the conversation's language - its newest
          line's (``"conversation"``) - unless the line is long enough and sure of another
          (``"text"``); a short "ok" keeps it."""
        from ...core import language as lg
        from ...core import tags as tg
        ws = lg.words(text) if text else []
        said = lg.detect(ws) if ws else None
        chosen = self.data.get("chat_languages", {}).get(group_id)
        if chosen and (kind == "chat" or reply_to is not None):
            return list(chosen), "chosen"                   # your choice for lines here wins
        if kind == "chat" and not reply_to:
            convo = self._conversation_language(group_id)
            if said and (len(ws) >= lg.SHORT or not convo) and said not in (convo or []):
                return [said], "text"
            if convo:
                return convo, "conversation"
        elif reply_to is not None:
            answered = list(getattr(reply_to, "languages", ()) or ())
            if not answered and getattr(reply_to, "readable", False):
                g = lg.guess(getattr(reply_to, "body", "") or "")
                answered = [g] if g else []
            if answered:
                return answered, "answered"
        if said:
            return [said], "text"
        group = tg.normalize_languages(self.manifest_data(group_id).get("languages") or [])
        if group:
            return group, "group"
        mine = self.data.get("languages_by_group", {}).get(group_id)
        if mine:
            return list(mine), "you"
        prof = tg.normalize_languages((self.my_profile() or {}).get("lang") or [])
        if len(prof) == 1:
            return prof, "profile"
        return [], ""

    def _conversation_language(self, group_id: str) -> list[str]:
        """The language of a chat's newest line that says or shows one (UN-RFC 0052 5a)."""
        from ...core import language as lg
        msgs = sorted((m for m in self.cache.get(group_id, {}).values() if m.readable and m.kind == "chat"),
                      key=lambda m: m.number, reverse=True)
        for m in msgs[:20]:
            if m.languages:
                return list(m.languages)
            g = lg.guess(m.body or "")
            if g:
                return [g]
        return []

    async def post(self, group_id: str, subject: str, body: str,
                   references: list[str] | None = None, kind: str = KIND_POST,
                   content_type: str | None = None,
                   supersedes: list[str] | None = None,
                   extra: list[tuple[str, str]] | None = None,
                   from_name: str | None = None, files=None, origin: dict | None = None,
                   tags=None, languages=None) -> str:
        """Post to a group: a post (with a subject) or a chat line (UN-RFC 0028).

        ``extra`` are more headers, for a program's own (``X-``, ``Gateway-*``,
        UN-RFC 0046 section 4.9); ``from_name`` replaces your display name.
        ``origin``: an import of your own from another network (UN-RFC 0049 section 4) -
        ``{"network", "date", "id", "from"}``, the date when it was first published
        there; its ``Date`` is still the time of posting.
        ``files`` are prepared files (``prepare_files``): checked against the group
        first, then sent as blobs with the post, which pays their extra postage
        (UN-RFC 0027 sections 4.5, 6). ``tags``: the author's own, at most 8 (UN-RFC
        0052) - normalised here; in a closed group they go inside the encryption.
        ``languages``: what it is written in (UN-RFC 0052 5a), as the author chose -
        remembered for the group, so ``suggest_languages`` offers it next time; ``[]``
        says none, ``None`` leaves the header out and remembers nothing."""
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
        from ...core import tags as tg
        # chips and '#word' in what was written, into the header (UN-RFC 0052 section 3)
        tag_header = tg.header(tg.normalize(list(tags or []) + tg.in_text(f"{subject}\n{body}"))) \
            if kind != "reaction" else None
        langs = tg.normalize_languages(languages) if languages is not None and kind != "reaction" else []
        if languages is not None and kind != "reaction":
            self.remember_languages(group_id, langs)        # for next time here (0052, 5a)
        if langs:
            tag_header = [tag_header] if tag_header else []
            tag_header.append((tg.LANG_HEADER, ", ".join(langs)))
        else:
            tag_header = [tag_header] if tag_header else []
        edit_header = [("Supersedes", " ".join(supersedes))] if supersedes else []   # 0042
        edit_header += list(extra or [])
        if origin:
            from ...core import origins
            try:
                proof = origin.get("proof")                  # the old article, as signed (7.3)
                if isinstance(proof, str):
                    import base64
                    proof = base64.b64decode(proof)
                edit_header += origins.origin_headers(origin.get("network", ""), origin.get("date"),
                                                      origin.get("id", ""), origin.get("from", ""),
                                                      proof=proof)
            except origins.OriginError as exc:
                raise SessionError(str(exc)) from exc
        files = list(files or [])
        blobs, file_bits, inner_files = [], 0, []
        entry = self.group_entry(group_id)
        if files:
            from ...core import blobs as bl
            # the rules for files from the current manifest: this vault may not have it,
            # or have one from before the owner allowed files
            if not isinstance(self.manifest_data(group_id).get("attachments"), dict):
                m = await self.fetch_manifest(group_id)
                if m is not None:
                    self.group_entry(group_id)["manifest"] = dict(m.raw)
            self.check_files(group_id, files)
            described = [(f.name, f.media_type, f.octets, f.alt, f.dim) for f in files]
            if entry.get("type") == "closed":     # encrypted, keys inside (UN-RFC 0027, 3.3)
                outer, inner_files, blobs = bl.encrypted_attachment_headers(
                    described, (self.manifest_data(group_id).get("attachments") or {}).get("max_size"))
                edit_header += outer
            else:
                edit_header += bl.attachment_headers(described)
                blobs = [(bl.blob_id(f.octets), f.octets) for f in files]
            file_bits = bl.extra_bits_for(sum(len(b) for _, b in blobs))
        shown = from_name or self.display_name()
        author = self.identity()
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
                    content_type=content_type, pow_bits=bits + file_bits, extra=edit_header,
                    inner_extra=inner_files + tag_header)
        else:
            await naming.keep_my_names(self)              # a service's own names, once a day
            cert = naming.header_for(self, group_id)     # your name, once a week here (UN-RFC 0019)

            def build(bits):
                # a chat line has an empty subject; the kind is a header (UN-RFC 0028, 3.2-3.3)
                art = new_article(group_id, "" if kind == KIND_CHAT else subject, body,
                                  from_name=shown, references=references,
                                  extra=[("Content-Type", content_type), ("Message-Kind", kind)]
                                  + ([cert] if cert else []) + edit_header + tag_header)
                return art.finalize(author, bits + file_bits)
        gtype = self.manifest_data(group_id).get("type") or entry.get("type")
        if gtype == "moderated" and not self.moderates(group_id):
            return await self._submit(group_id, subject, build, files=files)
        msgid = (await self._post_with_postage(group_id, build, blobs=blobs)).message_id
        self._remember_mine(msgid)
        if cert:
            naming.sent_header(self, group_id)
        marks = self.data["read"].setdefault(group_id, [])   # your own posts are read
        marks.append(msgid)
        self.save()
        return msgid


def _blob_refusal(text: str) -> str:
    """A node's 445 to BLOBPOST, as a sentence for the user (UN-RFC 0027 section 6)."""
    word = text.split()[0] if text.split() else ""
    return {"unsupported": "this node carries no files - post on a node that does, or ask "
                           "its operator to turn them on",
            "refused": "the node refused this file",
            "size": "the file is larger than this node takes",
            "limit": "today's limit for files on this node is reached - try tomorrow",
            "hash": "the file was damaged on the way - try again"}.get(word, f"file: {text}")



def _too_old(text: str) -> bool:
    """A node's ``441 date`` for a Date more than an hour in the past (UN-RFC 0049 3.2)."""
    return "date" in text and "in the past" in text
