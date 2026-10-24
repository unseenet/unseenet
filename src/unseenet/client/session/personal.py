"""Personal groups (UN-RFC 0029 section 2.1): an identity's own feed and site.

Belongs here: the Group IDs of an identity's personal feed (``feed@<fp>``, UN-RFC
0034 section 5) and site (``site@<fp>``, UN-RFC 0035 section 7), starting one when
the user asks for it, and the warning a client must show first. Once started they
are renewed with the identity's other key-bound groups (private.py) and ended by
removing them (groups.py, ``remove_group``).

Not here: posting in a feed (posting.py), the pages of a site (kept.py), following
someone's feed (coming with following).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time

# UN-RFC 0029 section 2.1: told before a personal group is made
PERSONAL_GROUP_WARNING = (
    "A personal {what} is public and tied to this identity: anyone who knows your key or "
    "your name can find and read it.\n\n"
    "What you publish there can be kept by others and cannot be recalled - not when you "
    "change it, and not when you remove the {what}.\n\n"
    "For a few people only, use a closed group instead.")
PERSONAL_KINDS = {"feed": "feed", "site": "site"}


class PersonalMixin:
    def personal_group(self, kind: str, name: str | None = None) -> str:
        """The Group ID of an identity's personal feed or site (``kind`` ``feed`` or
        ``site``), started or not: ``feed@<fingerprint>``, ``site@<fingerprint>``."""
        if kind not in PERSONAL_KINDS:
            raise SessionError("a personal group is a feed or a site")
        return make_group_id(kind, self.identity(name).public_key)

    async def personal_groups_of(self, key: str) -> dict:
        """Someone's personal feed and site, if they have started them: ``{"feed":
        <Group ID or None>, "site": ...}``, from their manifests, read in one request
        (UN-RFC 0041) - so a profile can offer to look at them without following.
        Nothing is kept in the vault: looking is not following."""
        pk = crypto.key_from_text(key.strip())
        gids = {kind: make_group_id(kind, pk) for kind in PERSONAL_KINDS}
        found = await self.fetch_manifests(list(gids.values()))
        return {kind: gid if found.get(gid) is not None and not found[gid].expired() else None
                for kind, gid in gids.items()}

    def has_personal_group(self, kind: str) -> bool:
        """Whether this identity has started its personal feed or site in this vault:
        followed and owned here - what clients show as "My feed" or "My site"."""
        gid = self.personal_group(kind)
        return (gid in self.data["subscribed"]
                and bool(self.data["groups"].get(gid, {}).get("owner")))

    def personal_group_without_files(self, kind: str) -> bool:
        """Your personal feed or site is started but takes no files - made before they
        took pictures by default (#496); clients offer to turn pictures on, once."""
        if not self.has_personal_group(kind):
            return False
        gid = self.personal_group(kind)
        return (not isinstance(self.manifest_data(gid).get("attachments"), dict)
                and not self.group_entry(gid).get("files_offered"))

    async def allow_pictures(self, group_id: str) -> None:
        """Let a group you own carry pictures (``blobs.PICTURES``)."""
        from ...core import blobs as bl
        await self.update_group(group_id, attachments=bl.PICTURES)

    def personal_group_warning(self, kind: str) -> str:
        """What the user must be told before a personal feed or site is started."""
        return PERSONAL_GROUP_WARNING.format(what=kind)

    async def start_personal_group(self, kind: str, *, comments: str = "open",
                                   title: str = "", attachments: dict | None = None) -> str:
        """Start this identity's personal feed or site - only when the user asked for it,
        after showing ``personal_group_warning``. A feed takes comments unless
        ``comments="none"`` (UN-RFC 0034 section 5.2); a site is a channel shown as
        pages. ``attachments`` (``{"max_size": ..., "types": [...]}``, UN-RFC 0027
        section 5.1) is what files it carries; a new one takes pictures unless told
        otherwise (#496), ``{}`` for none. If it exists already, it is followed again,
        and given ``attachments`` if they are given and differ. Returns its Group ID."""
        from ...core import blobs as bl
        from ...core.groups import PERSONAL_GROUPS
        given, attachments = attachments, (bl.PICTURES if attachments is None
                                           else attachments or None)
        gid = self.personal_group(kind)
        try:
            current = await self.fetch_manifest(gid)
        except (SessionError, OSError, ConnectionError, NNTPError):
            current = None
        entry = self.group_entry(gid)
        if current is None or current.expired():
            serial = max(int(self.manifest_data(gid).get("serial", 0)),
                         current.serial if current else 0) + 1
            art = make_manifest(self.identity(), kind, "channel", view=PERSONAL_GROUPS[kind],
                                title=title, serial=serial, min_pow=_s.DEFAULT_POW,
                                comments=comments if kind == "feed" else None,
                                extra={"attachments": attachments} if attachments else None,
                                pow_bits=await self.required_pow(gid),
                                lifetime=self.key_bound_lifetime())
            await self._post_article(art)
            entry["manifest"] = json.loads(art.body)
            entry.update({"type": "channel", "owner": True})
        else:
            entry["manifest"] = dict(current.raw)
            entry.update({"type": "channel", "owner": True})
            if given is not None and current.raw.get("attachments") != attachments:
                await self.update_group(gid, attachments=attachments)
        self.subscribe(gid)
        return gid
