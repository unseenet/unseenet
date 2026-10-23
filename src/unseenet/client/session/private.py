"""Inboxes, private posts, a new identity's first lifetime, renewal. Part of Session (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class PrivateMixin:
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

    # --- a new identity's first lifetime (UN-RFC 0029 section 4, unseenet #270) ---
    IN_USE_DAYS = 3                 # opened on this many different days: in use

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
