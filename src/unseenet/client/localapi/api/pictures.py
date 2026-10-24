"""Pictures of people (UN-RFC 0046 section 4.11, UN-RFC 0022 section 8).

Belongs here: the pictures and identicons of many keys at once (``pictures``), read
together and decoded in a separate process by ``Session.pictures``, and your own
picture: what it would look like before it is published, publishing it and removing
it (``publish_picture``). The page never gets a picture the runtime has not checked.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

import base64
import binascii

from . import *  # noqa: F403  - the module's names, as when this was one file
from ....core.encoding import b64decode

MAX_PICTURE_KEYS = 255                          # keys in one request, as profiles (0041 3.2)
MAX_PICTURE_UPLOAD = 8 * 1024 * 1024            # the file a picture is made from


def _shown(pic: dict | None) -> dict | None:
    """A picture for the page: a ``data:`` URL of the runtime's own copy."""
    if not pic:
        return None
    data = pic.get("octets") or b64decode(pic.get("data", ""))  # base64url (0022 8.1)
    return {"type": pic["type"], "px": pic["px"], "alt": pic.get("alt", ""),
            "data": f"data:{pic['type']};base64,{base64.b64encode(data).decode()}"}


class Pictures:
    async def pictures(self, keys) -> dict:
        """``GET /api/pictures?keys=...`` (section 4.11): for each key its identicon and its
        picture (or null). The pictures of every author this runtime has are read with
        them, so a node cannot tell whose you look at (UN-RFC 0022 section 13)."""
        s = self._ready()
        keys = [k for k in dict.fromkeys(str(k).strip() for k in keys) if k][:MAX_PICTURE_KEYS]
        for k in keys:
            _key(k)
        authors = [m.author_key for g in s.cache.values() for m in g.values()
                   if m.readable and m.author_key]
        wanted = list(dict.fromkeys([*keys, *authors]))[:MAX_PICTURE_KEYS]
        found = await s.pictures(wanted)
        return {"pictures": {k: {"identicon": _identicon(k), "picture": _shown(found.get(k))}
                             for k in keys}}

    async def publish_picture(self, data: dict) -> dict:
        """``POST /api/profile/picture`` (section 4.11): with ``{"data": <base64>, "alt"}``
        and ``"preview": true``, the picture as it would be published - the middle square,
        at most 128 pixels and 8 KiB, saved again without metadata - and without
        ``preview`` that picture published; ``{"remove": true}`` removes yours."""
        s = self._ready()
        if data.get("remove"):
            await s.publish_picture(None)
            return {"picture": None, "published": False}
        try:
            octets = base64.b64decode(str(data.get("data") or ""), validate=True)
        except (binascii.Error, ValueError):
            raise SessionError("data is not base64") from None
        if not octets or len(octets) > MAX_PICTURE_UPLOAD:
            raise SessionError("a picture to start from is 1 octet to 8 MiB")
        picture = s.make_picture(octets, str(data.get("alt") or ""))
        if data.get("preview"):
            return {"picture": _shown(picture), "published": s.my_picture() is not None}
        await s.publish_picture(picture)
        return {"picture": _shown(picture), "published": True}
