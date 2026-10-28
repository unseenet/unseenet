"""A group's own emoji (UN-RFC 0056): read with the group, published by its owner.

Belongs here: which groups may have emoji, reading a group's set from its emoji group
(cached as that group's manifest, not subscribed), and the owner publishing a new set.
Not here: the rules of a set (core.group_emoji), making a picture small (client.media).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from ...core import group_emoji as ge
from ...core.encoding import b64


class GroupEmojiMixin:
    def group_emoji_possible(self, group_id: str) -> bool:
        """Whether a group may have emoji (UN-RFC 0056 section 3.3): an open, moderated or
        channel group that is not local or a data group. Groups whose manifest expires
        (personal feeds and sites) are not offered yet: the emoji group would need the
        same expiry and renewal."""
        m = self.manifest_data(group_id)
        try:
            name, _ = split_group_id(group_id)
        except ValueError:
            return False
        return (m.get("type") in ge.GROUP_TYPES and not m.get("local")
                and m.get("view") != "data" and "expires" not in m and not ge.is_emoji_name(name))

    def group_emoji(self, group_id: str) -> dict:
        """The group's emoji as last read: ``{name: picture}`` (section 4), {} if none or
        the group may have none."""
        if not self.group_emoji_possible(group_id):
            return {}
        raw = self.manifest_data(ge.emoji_group_id(group_id))
        if not raw or raw.get("view") != "data" or not ge.is_emoji_name(str(raw.get("name", ""))):
            return {}
        try:
            return ge.check_set(raw.get("emoji", {}), strict=False)
        except ge.EmojiError:
            return {}

    async def fetch_group_emoji(self, group_id: str) -> dict:
        """Read the group's emoji group from the node, without subscribing (section 6.1),
        and keep its manifest. A node that does not carry it means no emoji: not an
        error. Returns the set."""
        if not self.group_emoji_possible(group_id):
            return {}
        eg = ge.emoji_group_id(group_id)
        try:
            m = await self.fetch_manifest(eg)
        except (SessionError, OSError, ConnectionError, NNTPError, asyncio.IncompleteReadError):
            return self.group_emoji(group_id)
        if m is not None and m.owner == self._manifest_owner(group_id):
            entry = self.group_entry(eg)
            if m.serial >= int(entry.get("manifest", {}).get("serial", 0)):
                entry["manifest"] = dict(m.raw)
        return self.group_emoji(group_id)

    def _manifest_owner(self, group_id: str) -> bytes | None:
        owner = self.manifest_data(group_id).get("owner")
        try:
            return crypto.key_from_text(owner) if owner else None
        except crypto.CryptoError:
            return None

    async def set_group_emoji(self, group_id: str, emoji: dict) -> dict:
        """Owner: publish ``emoji`` (``{name: picture}``, the whole set) as the group's
        emoji (section 3.4); {} removes them. Returns the set as published."""
        if not self.group_entry(group_id).get("owner"):
            raise SessionError("only the group's owner can give it emoji")
        if not self.group_emoji_possible(group_id):
            raise SessionError("this group cannot have its own emoji (UN-RFC 0056 section 3.3)")
        try:
            ge.check_set(emoji)
        except ge.EmojiError as exc:
            raise SessionError(str(exc)) from exc
        ident = self.identity()
        try:
            await self._publish_key_bound(
                ge.emoji_group_id(group_id),
                lambda serial, bits: ge.emoji_manifest(ident, group_id, emoji, serial=serial,
                                                       pow_bits=bits))
        except ge.EmojiError as exc:
            raise SessionError(str(exc)) from exc
        except SessionError as exc:
            from .profiles import refused_picture
            raise refused_picture(exc) from exc
        return self.group_emoji(group_id)

    @staticmethod
    def make_group_emoji(octets: bytes, alt: str = "") -> dict:
        """The picture that would be published for a group emoji from any picture's
        octets: 32 by 32, at most 1 KiB, without metadata (section 4.2). Shown before it
        is published (6.3)."""
        from .. import media
        try:
            data, ctype = media.group_emoji(octets)
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        pic = {"v": 1, "type": ctype, "px": ge.PX, "data": b64(data)}
        if alt.strip():
            pic["alt"] = alt.strip()[:ge.MAX_ALT]
        ge.check_picture(pic)
        return pic
