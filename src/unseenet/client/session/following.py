"""Following feeds and people, and the timeline (UN-RFC 0034 sections 6, 7).

Belongs here: following a feed (subscribing to it), following a **person** - their
personal groups and the feeds their profile lists that are really theirs (UN-RFC 0022
section 4.5), resolved from a key, a fingerprint, an address or a name once and then
kept by key (``follow_person``) - keeping that up to date as profiles change
(``refresh_following``), unfollowing, and the **timeline**: the entries of every
feed you follow, newest first, in the order they were written and nothing else.

The list of whom you follow is kept in the vault only (``data["following"]``) and is
never sent anywhere; following someone does not tell them (section 6.1).

Not here: subscribing as such (reading.py), profiles (profiles.py), personal groups
of your own (personal.py).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time

_FP_RE = re.compile(r"^[a-z2-7]{16}$")


class FollowingMixin:
    def _following(self) -> dict:
        return self.data.setdefault("following", {}).setdefault("people", {})

    async def _resolve_person(self, target: str) -> tuple[str, str | None, str | None]:
        """``(fingerprint, key or None, name or None)`` of a person given by key,
        fingerprint, ``unseenet:`` address or name (UN-RFC 0019)."""
        from ...core import addresses as addr
        target = target.strip()
        if target.lower().startswith(addr.SCHEME):
            try:
                a = addr.parse(target)
            except addr.AddressError as exc:
                raise SessionError(str(exc)) from exc
            if a.kind != "identity":
                raise SessionError("that address is a group, not a person: follow the group")
            return a.fingerprint, None, None
        if target.startswith("ed25519:"):
            try:
                return crypto.fingerprint(crypto.key_from_text(target)), target, None
            except crypto.CryptoError as exc:
                raise SessionError("that is not a key") from exc
        if _FP_RE.match(target):
            return target, None, None
        try:
            split_group_id(target)
            raise SessionError("that is a group: follow it as a feed")
        except ValueError:
            pass
        try:
            await self.refresh_naming()
        except (SessionError, OSError, ConnectionError, NNTPError, asyncio.TimeoutError):
            pass                                  # the names this client knows already
        key = naming.key_for_name(self, target)
        if key is None:
            raise SessionError(f"no identity is known by the name {target}")
        return crypto.fingerprint(crypto.key_from_text(key)), key, target

    async def _feeds_of(self, fp: str, key: str | None) -> tuple[list[str], str | None]:
        """The feeds that are a person's own now, and their key: the personal groups
        that are current (UN-RFC 0029 section 2.1), and the feeds their profile lists
        whose manifest is a feed naming them as owner, moderator or poster (0022, 4.5)."""
        from ...core import profiles as prof
        out = []

        async def current(gid):
            try:
                m = await self.fetch_manifest(gid)
            except (SessionError, OSError, ConnectionError, NNTPError, asyncio.IncompleteReadError):
                return None
            return None if m is None or m.expired() else m

        listed = []
        m = await current(f"profile@{fp}")
        if m is not None:
            key = key or crypto.key_to_text(m.owner)
            p = prof.profile_from_manifest(m)
            listed = list((p.raw if p else {}).get("feeds", []))
        for kind in ("feed", "site"):
            m = await current(f"{kind}@{fp}")
            if m is not None:
                key = key or crypto.key_to_text(m.owner)
                out.append(m.group_id)
        for gid in listed:
            m = await current(gid)
            if m is None or m.view != "feed" or key is None:
                continue
            roles = {crypto.key_to_text(k) for k in (m.owner, *m.moderators, *m.posters)}
            if key in roles:
                out.append(gid)
        return out, key

    def _followed_for(self, gid: str, but: str | None = None) -> bool:
        return any(gid in p.get("feeds", []) for fp, p in self._following().items() if fp != but)

    async def follow_person(self, target: str) -> dict:
        """Follow a person - by key, fingerprint, ``unseenet:`` address or name - which
        follows their own feeds now and as they change (UN-RFC 0034 section 6.1). A
        name is resolved to a key once, and the key is followed from then on. Returns
        ``{"fingerprint", "key", "name", "feeds", "new"}``; nobody is told."""
        fp, key, name = await self._resolve_person(target)
        person = self._following().setdefault(fp, {"key": key, "name": name, "feeds": [],
                                                   "skip": []})
        if name and not person.get("name"):
            person["name"] = name
        result = await self._update_person(fp, person, key)
        self.save()
        return result

    async def _update_person(self, fp: str, person: dict, key: str | None) -> dict:
        feeds, key = await self._feeds_of(fp, key or person.get("key"))
        if key:
            person["key"] = key
        new = []
        for gid in feeds:
            if gid in person.get("skip", []) or gid in person["feeds"]:
                continue
            if gid not in self.data["subscribed"]:
                self.subscribe(gid)
                person["feeds"].append(gid)       # followed because of this person
                new.append(gid)
        for gid in [g for g in person["feeds"] if g not in feeds]:   # no longer theirs
            person["feeds"].remove(gid)
            if not self._followed_for(gid, but=fp):
                self.subscribe(gid, on=False)
        return {"fingerprint": fp, "key": person.get("key"), "name": person.get("name"),
                "feeds": feeds, "new": new}

    async def refresh_following(self) -> list[str]:
        """Read the profiles and personal groups of everyone you follow again: follow
        feeds that are new, and stop following those that are no longer theirs
        (unless followed on their own or for someone else). Returns the new ones."""
        new = []
        for fp, person in list(self._following().items()):
            new += (await self._update_person(fp, person, person.get("key")))["new"]
        self.save()
        return new

    async def unfollow_person(self, target: str) -> list[str]:
        """Stop following a person: the feeds followed only because of them are
        unsubscribed (UN-RFC 0034 section 6.1). Returns those."""
        fp, _, _ = await self._resolve_person(target)
        person = self._following().pop(fp, None)
        if person is None:
            raise SessionError("you do not follow that person")
        gone = []
        for gid in person.get("feeds", []):
            if not self._followed_for(gid):
                self.subscribe(gid, on=False)
                gone.append(gid)
        self.save()
        return gone

    def following(self) -> list[dict]:
        """The people you follow: ``{"fingerprint", "key", "name", "label", "feeds"}``,
        ``feeds`` those followed because of them."""
        return [{"fingerprint": fp, "key": p.get("key"), "name": p.get("name"),
                 "label": self.label_of(p["key"]) if p.get("key") else (p.get("name") or fp),
                 "feeds": list(p.get("feeds", []))}
                for fp, p in sorted(self._following().items())]

    def follow_feed(self, group_id: str, on: bool = True) -> None:
        """Follow a feed on its own (or stop, ``on=False``): subscribing, kept when a
        person who lists it is unfollowed - and not followed again for them once you
        stopped (section 6)."""
        split_group_id(group_id)
        for person in self._following().values():
            if group_id in person.get("feeds", []):
                person["feeds"].remove(group_id)
                if not on:
                    person.setdefault("skip", []).append(group_id)
        self.subscribe(group_id, on=on)
        self.save()

    def feeds_followed(self) -> list[str]:
        """The groups you follow that are feeds (their manifest's view is ``feed``)."""
        return [g for g in self.data["subscribed"] if self.manifest_data(g).get("view") == "feed"]

    def timeline(self, limit: int = 100) -> list[Message]:
        """The timeline (UN-RFC 0034 section 7): the entries - posts that start a thread
        - of every feed you follow, newest first by ``Date``, from what has been fetched.
        Nothing reorders it, and nothing from a feed you do not follow is in it."""
        rows = []
        for gid in self.feeds_followed():
            for msg, depth in self.threads(gid):
                if depth == 0 and not msg.private and msg.page is None and msg.readable:
                    rows.append(msg)
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        rows.sort(key=lambda m: (m.date or epoch, m.message_id), reverse=True)
        return rows[:limit]
