"""Profiles and pictures (UN-RFC 0022).

Belongs here: reading profiles (``profile_of``, read in batches so a node cannot tell
whose you open, ``prefetch_profiles``), publishing your own and your picture
(``publish_profile``, ``publish_picture``), hiding someone's profile for yourself, and
the pictures of many keys at once, read together and decoded in a separate process
before they are shown (``pictures``, UN-RFC 0022 section 8, UN-RFC 0027 section 9.2),
with a switch to show identicons only (``show_pictures``).

Not here: private profiles shared in a group or a private post (#182, coming), labels
(labels.py).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class ProfilesMixin:
    # ------------------------------------------------------------------
    # profiles and pictures (UN-RFC 0022)
    # ------------------------------------------------------------------
    PROFILE_CACHE_SECONDS = 24 * 3600
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
        """True when this client has the manifest of your profile group, i.e. your
        profile has been published (UN-RFC 0022)."""
        return bool(self.manifest_data(prof.profile_id(self.identity().public_key)))

    async def _publish_key_bound(self, group_id: str, make) -> dict:
        """Post a new manifest of one of our own key-bound groups, with a serial above
        any we used (UN-RFC 0029 section 8), and keep it so it is renewed."""
        self.mark_in_use()               # a profile or picture is using the identity
        entry = self.group_entry(group_id)
        if not self.manifest_data(group_id):
            # a vault that has not seen this group - restored from a backup, or a second
            # device: the network may have a manifest with a higher serial already
            try:
                current = await self.fetch_manifest(group_id)
            except (SessionError, OSError, ConnectionError, NNTPError, asyncio.IncompleteReadError):
                current = None
            if current is not None:
                entry["manifest"] = dict(current.raw)
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
        self.__dict__.get("_picture_cache", {}).pop(ident.key_text, None)
        return await self._publish_key_bound(
            prof.avatar_id(ident.public_key),
            lambda serial, bits: prof.avatar_manifest(ident, picture, serial=serial,
                                                      pow_bits=bits))

    async def publish_picture_file(self, path, alt: str = "") -> dict:
        """Publish a picture from a file as this identity's profile picture: the middle
        square, at most 128 pixels and 8 KiB, saved again without metadata
        (``client.media.avatar``, section 8.1). Returns the published manifest data."""
        try:
            octets = Path(path).read_bytes()
        except OSError as exc:
            raise SessionError(f"cannot read {Path(path).name}: {exc.strerror or exc}") from exc
        return await self.publish_picture(self.make_picture(octets, alt))

    @staticmethod
    def make_picture(octets: bytes, alt: str = "") -> dict:
        """The picture object that would be published from a picture's octets: the middle
        square, at most 128 pixels and 8 KiB, saved again without metadata (section
        8.1). A client shows it before publishing it (8.5)."""
        from .. import media
        try:
            data, ctype, px = media.avatar(octets)
            return prof.make_picture(data, ctype, px, alt.strip()[:prof.MAX_ALT])
        except (ValueError, prof.ProfileError) as exc:
            raise SessionError(str(exc)) from exc

    def my_picture(self) -> dict | None:
        """This identity's published picture object, or None."""
        return self.manifest_data(prof.avatar_id(self.identity().public_key)).get("avatar") or None

    def show_pictures(self) -> bool:
        """False when the user chose identicons only (section 8.5)."""
        return self.data.get("show_pictures") is not False

    def set_show_pictures(self, on: bool) -> None:
        """Show people's pictures (True) or identicons only (False); kept in the vault."""
        self.data["show_pictures"] = bool(on)
        self.save()

    async def pictures(self, keys) -> dict:
        """The pictures of many keys, read together so a node cannot tell whose you look
        at (sections 8.2, 13): key -> ``{"type", "px", "octets", "alt"}`` or None. Each
        is decoded and saved again in a separate process and kept only if it is the
        square still picture it says (8.1); none for a key you hid or ignore, or when
        pictures are off - then the identicon is shown (8.5). Kept in memory a day."""
        from .. import decode
        cache = self.__dict__.setdefault("_picture_cache", {})
        now = datetime.now(timezone.utc).timestamp()
        mine = self.identity().key_text
        out: dict = {}
        todo: dict[str, str] = {}
        for key in dict.fromkeys(str(k).strip() for k in keys if k):
            if key != mine and (not self.show_pictures() or self.profile_hidden(key)
                                or self.is_ignored(key)):
                out[key] = None
                continue
            hit = cache.get(key)
            if hit and now - hit[0] <= self.PROFILE_CACHE_SECONDS:
                out[key] = hit[1]
                continue
            try:
                todo[prof.avatar_id(crypto.key_from_text(key))] = key
            except crypto.CryptoError:
                out[key] = None
        if todo:
            try:
                found = await self.fetch_manifests(list(todo))
            except OSError:                     # node away: identicons now, ask again later
                return {**out, **dict.fromkeys(todo.values())}
            for gid, key in todo.items():
                m = found.get(gid)
                obj = prof.picture_from_manifest(m) if m is not None else None
                pic = None
                if obj is not None:
                    try:
                        shown = await decode.picture_async(prof.check_picture(obj), obj["type"])
                    except (decode.DecodeError, prof.ProfileError):
                        shown = None
                    if shown and shown.width == shown.height == obj["px"] and shown.frames == 1:
                        pic = {"type": shown.media_type, "px": obj["px"], "octets": shown.octets,
                               "alt": obj.get("alt", "")}
                cache[key] = (now, pic)
                out[key] = pic
        return out

    async def picture_of(self, key_text: str) -> dict | None:
        """The picture of a key, if its node carries avatar groups (section 8.2)."""
        pk = crypto.key_from_text(key_text)
        m = await self.fetch_manifest(prof.avatar_id(pk))
        return prof.picture_from_manifest(m) if m else None

    # --- private profiles (section 6) ---
    async def share_profile(self, to: str, profile: dict | None = None) -> str:
        """Share a profile with one person (their inbox) or a closed group, where only
        they can read it (section 6): by default your public one, or another made for
        them - with a picture inline if you like (8.3). Returns the Message-ID."""
        if profile is None:
            profile = dict(self.my_profile() or {"v": 1})
            pic = self.my_picture()
            if pic and "avatar" not in profile:
                profile["avatar"] = {k: v for k, v in pic.items() if k in ("type", "data", "alt")}
        try:
            obj = prof.check_profile(profile, private=True)
        except prof.ProfileError as exc:
            raise SessionError(str(exc)) from exc
        body = prof.canonical_json(obj) + "\n"
        if split_group_id(to)[0] == INBOX_NAME:
            if to == self.my_inbox:
                raise SessionError("share your profile with someone else's inbox")
            return await self.send_private(to, "Profile", body, content_type=prof.PRIVATE_TYPE,
                                           remember=False)
        if self.group_entry(to).get("type") != "closed":
            raise SessionError("a private profile goes to a person or a closed group; "
                               "for everyone, publish your profile")
        return await self.post(to, "Profile", body, content_type=prof.PRIVATE_TYPE)

    async def withdraw_shared_profile(self, to: str) -> str:
        """Take back the profile you shared there (an empty one, section 6)."""
        return await self.share_profile(to, {"v": 1})

    def _keep_private_profile(self, msg: "Message", context: str) -> None:
        """A private profile read in a context ("me": sent to you; or a closed group's
        ID): kept as the newest for that key there, or withdrawn. The post itself is not
        shown among the others."""
        msg.private_profile = True
        try:
            obj = prof.check_profile(json.loads(msg.body), private=True)
        except (ValueError, prof.ProfileError):
            return
        store = self.data.setdefault("private_profiles", {}).setdefault(context, {})
        key = msg.author_key
        when = msg.date.isoformat() if msg.date else ""
        old = store.get(key)
        # Date is rounded to 10 minutes: of two the same, the one the node got later
        if old and (old.get("date", ""), old.get("number", 0)) >= (when, msg.number):
            return                                   # an older one, read later
        if old and old.get("msgid") == msg.message_id:
            return
        mark = {"date": when, "number": msg.number, "msgid": msg.message_id}
        store[key] = {"withdrawn": True, **mark} if prof.withdraws(obj) else {"profile": obj, **mark}

    def private_profile(self, key_text: str, context: str) -> dict | None:
        """The profile this key shared in this context (\"me\", or a closed group's ID), or
        None. Never one from another context (section 6)."""
        got = self.data.get("private_profiles", {}).get(context, {}).get(key_text)
        return got.get("profile") if got and not got.get("withdrawn") else None

    def shared_contexts(self, key_text: str) -> list[str]:
        """The contexts in which this key has shared a profile you can see."""
        return [c for c, keys in self.data.get("private_profiles", {}).items()
                if keys.get(key_text) and not keys[key_text].get("withdrawn")]

    def hide_profile(self, key_text: str, hidden: bool = True) -> None:
        """Section 9.2: the user may hide the profile of a key."""
        hidden_set = set(self.data.setdefault("hidden_profiles", []))
        (hidden_set.add if hidden else hidden_set.discard)(key_text)
        self.data["hidden_profiles"] = sorted(hidden_set)
        self.save()

    def profile_hidden(self, key_text: str) -> bool:
        """True when you hid this key's profile for yourself (see ``hide_profile``)."""
        return key_text in self.data.get("hidden_profiles", [])
