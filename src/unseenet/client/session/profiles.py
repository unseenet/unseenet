"""Profiles and pictures (UN-RFC 0022). Part of Session (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class ProfilesMixin:
    # ------------------------------------------------------------------
    # profiles and pictures (UN-RFC 0022)
    # ------------------------------------------------------------------
    PROFILE_CACHE_SECONDS = 24 * 3600

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
            out.update(await self._call(run, address))
        return out

    async def fetch_manifest(self, group_id: str, node: str | None = None):
        """The current valid, unexpired manifest of one group; None if there is none."""
        return (await self.fetch_manifests([group_id], node)).get(group_id)

    def _profile_cache(self) -> dict:
        return self.data.setdefault("profiles", {})

    async def profile_of(self, key_text: str, refresh: bool = False) -> "prof.Profile | None":
        """The public profile of a key (UN-RFC 0022 section 5.2), cached for a day.
        None when there is none: that is not an error (5.2)."""
        pk = crypto.key_from_text(key_text)
        if pk == self.identity().public_key:
            mine = self.my_profile()
            return prof.Profile.from_object(pk, mine) if mine else None
        cache = self._profile_cache()
        hit = cache.get(key_text)
        now = datetime.now(timezone.utc).timestamp()
        if hit is None or refresh or now - hit.get("fetched", 0) > self.PROFILE_CACHE_SECONDS:
            m = await self.fetch_manifest(prof.profile_id(pk))
            hit = self._cache_profile(key_text, m, now)
            self.save()
        obj = hit.get("profile")
        if not obj:
            return None
        try:
            return prof.Profile.from_object(pk, prof.check_profile(obj), hit.get("serial", 0))
        except prof.ProfileError:
            return None

    def _cache_profile(self, key_text: str, m, now: float) -> dict:
        p = prof.profile_from_manifest(m) if m else None
        hit = {"fetched": now, "profile": p.raw if p else None, "serial": m.serial if m else 0}
        old = self._profile_cache().get(key_text)
        if m is not None and old and m.serial < old.get("serial", 0):
            hit = dict(old, fetched=now)    # never step back to an older serial (0041 3.1)
        self._profile_cache()[key_text] = hit
        return hit

    async def prefetch_profiles(self, keys) -> int:
        """Read the profiles of many keys at once into the cache - all the authors of
        a group, rather than one when the user opens it (UN-RFC 0022 section 9.2,
        UN-RFC 0041 section 3.2). Hidden profiles and our own are skipped. Returns
        the number of keys asked for."""
        cache = self._profile_cache()
        now = datetime.now(timezone.utc).timestamp()
        mine = self.identity().key_text
        todo: dict[str, str] = {}
        for key_text in dict.fromkeys(k.strip() for k in keys if k):
            hit = cache.get(key_text)
            if key_text == mine or self.profile_hidden(key_text) or (
                    hit and now - hit.get("fetched", 0) <= self.PROFILE_CACHE_SECONDS):
                continue
            try:
                todo[prof.profile_id(crypto.key_from_text(key_text))] = key_text
            except crypto.CryptoError:
                continue
        if not todo:
            return 0
        found = await self.fetch_manifests(list(todo))
        for gid, key_text in todo.items():
            self._cache_profile(key_text, found.get(gid), now)
        self.save()
        return len(todo)

    def my_profile(self) -> dict | None:
        """This identity's published profile object, or None."""
        gid = prof.profile_id(self.identity().public_key)
        return self.manifest_data(gid).get("profile") or None

    def has_published_profile(self) -> bool:
        return bool(self.manifest_data(prof.profile_id(self.identity().public_key)))

    async def _publish_key_bound(self, group_id: str, make) -> dict:
        """Post a new manifest of one of our own key-bound groups, with a serial above
        any we used (UN-RFC 0029 section 8), and keep it so it is renewed."""
        self.mark_in_use()               # a profile or picture is using the identity
        entry = self.group_entry(group_id)
        serial = int(self.manifest_data(group_id).get("serial", 0)) + 1
        art = make(serial, await self.required_pow(None))
        await self._post_article(art, self.node)
        data = json.loads(art.body)
        entry.update({"type": "channel", "owner": True, "manifest": data,
                      "node": entry.get("node") or self.node})
        self.save()
        return data

    async def publish_profile(self, profile: dict | None) -> dict:
        """Publish (or with None, empty) this identity's public profile (5.1, 5.3)."""
        ident = self.identity()
        if profile is not None:
            try:
                prof.check_profile(profile)
            except prof.ProfileError as exc:
                raise SessionError(str(exc)) from exc
        return await self._publish_key_bound(
            prof.profile_id(ident.public_key),
            lambda serial, bits: prof.profile_manifest(ident, profile, serial=serial,
                                                       pow_bits=bits))

    async def publish_picture(self, picture: dict | None) -> dict:
        """Publish (or with None, remove) this identity's picture (section 8.2).
        ``picture`` must already be re-encoded without metadata (8.1)."""
        ident = self.identity()
        if picture is not None:
            try:
                prof.check_picture(picture)
            except prof.ProfileError as exc:
                raise SessionError(str(exc)) from exc
        return await self._publish_key_bound(
            prof.avatar_id(ident.public_key),
            lambda serial, bits: prof.avatar_manifest(ident, picture, serial=serial,
                                                      pow_bits=bits))

    async def picture_of(self, key_text: str) -> dict | None:
        """The picture of a key, if its node carries avatar groups (section 8.2)."""
        pk = crypto.key_from_text(key_text)
        m = await self.fetch_manifest(prof.avatar_id(pk))
        return prof.picture_from_manifest(m) if m else None

    def hide_profile(self, key_text: str, hidden: bool = True) -> None:
        """Section 9.2: the user may hide the profile of a key."""
        hidden_set = set(self.data.setdefault("hidden_profiles", []))
        (hidden_set.add if hidden else hidden_set.discard)(key_text)
        self.data["hidden_profiles"] = sorted(hidden_set)
        self.save()

    def profile_hidden(self, key_text: str) -> bool:
        return key_text in self.data.get("hidden_profiles", [])

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
