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
TIMELINE_TYPES = ("open", "moderated", "channel", "closed")   # groups of people (0034, 6.2)
TIMELINE_VIEWS = ("feed", "threads")                         # not chat, data or sites


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

    async def _feeds_of(self, fp: str, key: str | None) -> tuple[dict, str | None]:
        """The feeds that are a person's own now, with their current manifests, and
        their key: the personal groups that are current (UN-RFC 0029 section 2.1), and
        the feeds their profile lists whose manifest is a feed naming them as owner,
        moderator or poster (0022, 4.5)."""
        from ...core import profiles as prof
        out = {}

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
                out[m.group_id] = dict(m.raw)
        for gid in listed:
            m = await current(gid)
            if m is None or m.view != "feed" or key is None:
                continue
            roles = {crypto.key_to_text(k) for k in (m.owner, *m.moderators, *m.posters)}
            if key in roles:
                out[gid] = dict(m.raw)
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
        if result["key"] and not self.seen_name(result["key"]):
            await self._learn_name(result["key"], result["new"])
        self.save()
        return result

    async def _learn_name(self, key: str, groups: list[str]) -> None:
        """Read the groups just followed for someone whose name we have not seen, so
        they are shown by name at once rather than as ``?~fp`` until the next
        refresh (#709). The name is the ``From`` of their posts - a profile carries
        none (UN-RFC 0022 section 3) - and ``seen_name`` keeps it. The feed first;
        quiet on failure, as the refresh reads them anyway."""
        for gid in sorted(groups, key=lambda g: not g.startswith("feed@")):
            try:
                await self.fetch_group(gid)
            except (SessionError, OSError, ConnectionError, NNTPError, asyncio.TimeoutError):
                continue
            if self.seen_name(key):
                return

    async def _update_person(self, fp: str, person: dict, key: str | None) -> dict:
        feeds, key = await self._feeds_of(fp, key or person.get("key"))
        if key:
            person["key"] = key
        new = []
        for gid, raw in feeds.items():
            if gid in person.get("skip", []):
                continue
            if gid in self.data["subscribed"] or gid in person["feeds"]:
                self.group_entry(gid)["manifest"] = raw   # known to be a feed next time too
                continue
            self.group_entry(gid)["manifest"] = raw
            self.subscribe(gid)
            person["feeds"].append(gid)           # followed because of this person
            new.append(gid)
        for gid in [g for g in person["feeds"] if g not in feeds]:   # no longer theirs
            person["feeds"].remove(gid)
            if not self._followed_for(gid, but=fp):
                self.subscribe(gid, on=False)
        return {"fingerprint": fp, "key": person.get("key"), "name": person.get("name"),
                "feeds": list(feeds), "new": new}

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

    def is_following(self, key: str) -> bool:
        """Whether you follow this person, given by key (for a Follow/Following button)."""
        try:
            fp = crypto.fingerprint(crypto.key_from_text(key.strip()))
        except (crypto.CryptoError, ValueError):
            return False
        return fp in self._following()

    def following(self) -> list[dict]:
        """The people you follow: ``{"fingerprint", "key", "name", "label", "feeds"}``,
        ``feeds`` those followed because of them."""
        out = [{"fingerprint": fp, "key": p.get("key"), "name": p.get("name"),
                "label": self.label_of(p["key"]) if p.get("key") else (p.get("name") or fp),
                "feeds": list(p.get("feeds", []))}
               for fp, p in sorted(self._following().items())]
        self._save_learnt_labels()
        return out

    def _save_learnt_labels(self) -> None:
        if getattr(self, "_labels_learnt", False):
            self._labels_learnt = False
            self.save()

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
        """The groups you follow that are feeds (their manifest's view is ``feed``), as far
        as this client knows their manifests - ``fetch_unknown_manifests`` asks for the
        ones it does not know."""
        return [g for g in self.data["subscribed"] if self.manifest_data(g).get("view") == "feed"]

    # --- what goes into the timeline (UN-RFC 0034 section 6.2) ---------------------
    def timeline_possible(self, group_id: str) -> bool:
        """Whether a group can be in the timeline at all: a group of people (open,
        moderated, channel, closed) whose owner shows it as a feed or as threads, as far
        as this client knows its manifest. Chat, data, inboxes and states never are."""
        m = self.manifest_data(group_id)
        if not m or m.get("type") not in TIMELINE_TYPES:
            return False
        return (m.get("view") or "threads") in TIMELINE_VIEWS

    def timeline_default(self, group_id: str) -> bool:
        """In the timeline unless you chose otherwise: a feed yes, threads no."""
        return self.timeline_possible(group_id) and self.manifest_data(group_id).get("view") == "feed"

    def in_timeline(self, group_id: str) -> bool:
        """Whether a group you follow comes into your timeline: your own choice for it
        if you made one, else its default (``timeline_default``). The view you read the
        group in does not change this."""
        if group_id not in self.data["subscribed"] or not self.timeline_possible(group_id):
            return False
        choice = self.data.get("timeline_choice", {}).get(group_id)
        return choice if isinstance(choice, bool) else self.timeline_default(group_id)

    def set_in_timeline(self, group_id: str, on: bool | None) -> bool:
        """Put a group you follow into the timeline or take it out (``None``: back to
        its default). Only a choice that differs from the default is kept, in the state
        (UN-RFC 0044 ``timeline``). Returns whether it is in the timeline now."""
        if group_id not in self.data["subscribed"]:
            raise SessionError("follow the group first")
        if on and not self.timeline_possible(group_id):
            raise SessionError("chat groups and inboxes cannot be in the timeline")
        choices = self.data.setdefault("timeline_choice", {})
        if on is None or on == self.timeline_default(group_id):
            choices.pop(group_id, None)
        else:
            choices[group_id] = bool(on)
        self.save()
        return self.in_timeline(group_id)

    def timeline_groups(self) -> list[str]:
        """The groups whose entries make up your timeline."""
        return [g for g in self.data["subscribed"] if self.in_timeline(g)]

    async def fetch_unknown_manifests(self) -> int:
        """Fetch the manifest of every group you follow that this client has none of,
        so a feed is known to be one before the timeline is built. Returns how many."""
        found = 0
        for gid in list(self.data["subscribed"]):
            if self.manifest_data(gid):
                continue
            try:
                m = await self.fetch_manifest(gid)
            except (SessionError, OSError, ConnectionError, NNTPError, asyncio.IncompleteReadError):
                continue
            if m is not None:
                self.group_entry(gid)["manifest"] = dict(m.raw)
                found += 1
        if found:
            self.save()
        return found

    def tagged(self, tag: str, limit: int = 200) -> list[Message]:
        """Every post with a tag in the groups and feeds you follow, newest first, from
        what has been fetched (UN-RFC 0052 section 7): the author's own tags, its group's,
        and topics from labellers you follow for topics (UN-RFC 0053). Never private posts.
        Shown as the reader would see them (``visible``: reports, warnings marked)."""
        from ...core import tags as tg
        tag = (tg.normalize([tag]) or [""])[0]
        if not tag:
            return []
        groups = list(dict.fromkeys([*self.data.get("subscribed", []), *self.feeds_followed()]))
        out = []
        for gid in groups:
            if gid.startswith("inbox@"):
                continue
            gtags = self.manifest_data(gid).get("tags")
            in_group = isinstance(gtags, list) and tag in gtags
            for m in self.visible(list(self.cache.get(gid, {}).values())):
                if m.private or not m.readable or m.kind == "reaction":
                    continue
                topics = (m.labels or {}).get("topics", []) if m.labels else []
                if in_group or tag in m.tags or tag in topics:
                    out.append(m)
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        out.sort(key=lambda m: (m.date or epoch, m.message_id), reverse=True)
        return out[:limit]

    def timeline(self, limit: int = 100) -> list[Message]:
        """The timeline (UN-RFC 0034 section 7): the entries - posts that start a thread
        - of every group you have in it (``timeline_groups``: feeds unless you took them
        out, threads you put in), newest first by ``Date``, from what has been fetched.
        Comments and replies stay under their entry. Nothing reorders it, and nothing
        from a group outside it is in it."""
        rows = []
        for gid in self.timeline_groups():
            for msg, depth in self.feed_rows(gid):
                if depth == 0 and not msg.private and msg.page is None and msg.readable:
                    rows.append(msg)
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        # an import sits where it belongs in its author's history (UN-RFC 0049 5.3)
        rows.sort(key=lambda m: (m.sort_date or epoch, m.message_id), reverse=True)
        for m in rows:
            self.seen_name(m.author_key)              # remember the names of those followed
        self._save_learnt_labels()
        return rows[:limit]
