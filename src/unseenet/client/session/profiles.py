"""Profiles and pictures (UN-RFC 0022).

Belongs here: reading profiles (``profile_of``, read in batches so a node cannot tell
whose you open, ``prefetch_profiles``), publishing your own and your picture
(``publish_profile``, ``publish_picture``), and hiding someone's profile for yourself.

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

    async def publish_picture_file(self, path, alt: str = "") -> dict:
        """Publish a picture from a file as this identity's profile picture: the middle
        square, at most 128 pixels and 8 KiB, saved again without metadata
        (``client.media.avatar``, section 8.1). Returns the published manifest data."""
        from .. import media
        try:
            data, ctype, px = media.avatar(Path(path).read_bytes())
            picture = prof.make_picture(data, ctype, px, alt.strip()[:prof.MAX_ALT])
        except OSError as exc:
            raise SessionError(f"cannot read {Path(path).name}: {exc.strerror or exc}") from exc
        except (ValueError, prof.ProfileError) as exc:
            raise SessionError(str(exc)) from exc
        return await self.publish_picture(picture)

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
        """True when you hid this key's profile for yourself (see ``hide_profile``)."""
        return key_text in self.data.get("hidden_profiles", [])
