"""A group's own emoji in the local API (UN-RFC 0056, UN-RFC 0046 section 4.7).

Belongs here: reading a group's emoji from its node, and the owner adding, renaming,
describing and removing them, with a preview before. Not here: the rules of a set
(core.group_emoji) or reading and publishing it (client.session.group_emoji).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


def _picture_octets(data) -> bytes:
    import base64
    import binascii
    try:
        return base64.b64decode(str(data or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SessionError("data is b64 of a picture") from exc


class GroupEmoji:
    async def group_emoji(self, gid: str) -> dict:
        """``GET /api/groups/{gid}/emoji``: the group's emoji, read anew from its node
        (without following its emoji group) - ``{"emoji": {name: picture}, "possible",
        "max", "warning"}``, ``warning`` to say before the first is published (6.3). A node that does not carry them gives none: not an error."""
        s = self._ready()
        from ....core import group_emoji as ge
        return {"emoji": await s.fetch_group_emoji(gid), "possible": s.group_emoji_possible(gid),
                "max": ge.MAX_EMOJI, "warning": ge.WARNING}

    async def change_group_emoji(self, gid: str, data: dict) -> dict:
        """``POST /api/groups/{gid}/emoji``, owner: one of
        ``{"preview": {"data", "alt"}}`` - the picture as it would be published (32 by 32,
        at most 1 KiB, no metadata), nothing published;
        ``{"add": {"name", "data", "alt"}}`` - ``data`` b64 of any picture, made small here;
        ``{"alt": {"name", "alt"}}``, ``{"rename": {"from", "to"}}``, ``{"remove": name}``.
        Each publishes the whole set anew. Answers as ``GET``."""
        s = self._ready()
        if "preview" in data:
            p = data["preview"] or {}
            return {"picture": s.make_group_emoji(_picture_octets(p.get("data")), str(p.get("alt", "")))}
        current = dict(await s.fetch_group_emoji(gid))
        from ....core import group_emoji as ge
        try:
            if "add" in data:
                a = data["add"] or {}
                name = ge.check_name(str(a.get("name", "")).strip(":").strip())
                current[name] = s.make_group_emoji(_picture_octets(a.get("data")), str(a.get("alt", "")))
            elif "alt" in data:
                a = data["alt"] or {}
                name = str(a.get("name", ""))
                if name not in current:
                    raise SessionError(f":{name}: is not one of the group's emoji")
                pic = {k: v for k, v in current[name].items() if k != "alt"}
                if str(a.get("alt", "")).strip():
                    pic["alt"] = str(a["alt"]).strip()[:ge.MAX_ALT]
                current[name] = pic
            elif "rename" in data:
                r = data["rename"] or {}
                old, new = str(r.get("from", "")), ge.check_name(str(r.get("to", "")).strip(":").strip())
                if old not in current:
                    raise SessionError(f":{old}: is not one of the group's emoji")
                current = {new if k == old else k: v for k, v in current.items()}
            elif "remove" in data:
                current.pop(str(data["remove"]), None)
            else:
                raise SessionError('give "preview", "add", "alt", "rename" or "remove"')
        except ge.EmojiError as exc:
            raise SessionError(str(exc)) from exc
        await s.set_group_emoji(gid, current)
        s.emit(ev.GroupUpdated(gid))
        return {"emoji": s.group_emoji(gid), "possible": True, "max": ge.MAX_EMOJI,
                "warning": ge.WARNING}
