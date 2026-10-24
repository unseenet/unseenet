"""Files on posts (UN-RFC 0046 section 4.10, UN-RFC 0027): showing, saving and posting them.

Belongs here: what a group takes (``_files_policy``, in a group's head), a picture a
post carries made safe to show (``file`` - fetched, checked and decoded in a separate
process by ``Session.picture``), the file itself to save (``file`` with ``save``), and
reading the files a front end sends with a post (``_files_to_post``). The page never
gets anything from the network that the runtime has not checked and saved again.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

import base64
import binascii

from . import *  # noqa: F403  - the module's names, as when this was one file
from ...session import FileUnavailable

MAX_FILES = 4                                  # files on one post (UN-RFC 0027 section 4.1)
_STATUS = {"none": 404, "gone": 404, "later": 503, "wrong": 502}


class Files:
    @staticmethod
    def _files_policy(data: dict) -> dict | None:
        """The manifest's ``attachments`` (UN-RFC 0027 section 5.1) for a front end:
        ``{"max_size", "types"}``, or None when the group takes no files."""
        att = data.get("attachments")
        if not isinstance(att, dict):
            return None
        return {"max_size": att.get("max_size"), "types": list(att.get("types") or [])}

    async def file(self, gid: str, blob_id: str, *, save: bool = False,
                   asked: bool = False) -> dict:
        """``GET /api/groups/{gid}/files/{blob}`` (section 4.10): a picture a post here
        carries, decoded and saved again by the runtime, as ``{"type", "width",
        "height", "frames", "data"}`` with ``data`` a ``data:`` URL - or with ``save``
        the file as the node sent it, checked, as ``{"name", "type", "size",
        "data"}`` (base64), to save and never to open."""
        s = self._ready()
        try:
            att, _ = s.attachment(gid, blob_id)
        except SessionError as exc:
            raise NotFound(str(exc)) from exc
        try:
            if save:
                octets = await s.fetch_blob(gid, blob_id)
                return {"name": att.get("name") or "file", "type": att["type"],
                        "size": len(octets), "data": base64.b64encode(octets).decode()}
            pic = await s.picture(gid, blob_id, asked=asked)
        except FileUnavailable as exc:
            raise Status(str(exc), _STATUS.get(exc.why, 502), why=exc.why) from exc
        except SessionError as exc:                 # ignored author, or not a picture to show
            why = "ignored" if "ignore" in str(exc) else "not_shown"
            raise Status(str(exc), 403 if why == "ignored" else 415, why=why) from exc
        data = base64.b64encode(pic.octets).decode()
        return {"type": pic.media_type, "width": pic.width, "height": pic.height,
                "frames": pic.frames, "data": f"data:{pic.media_type};base64,{data}"}

    @staticmethod
    def _files_to_post(s: Session, gid: str, files, check: bool = True) -> list:
        """The files of ``POST .../post`` (``[{"name", "data", "alt"}]``, ``data`` base64)
        prepared as every client prepares them - the type from the content, pictures
        saved again without metadata - and checked against the group before anything
        is computed (``check=False``: when sending, as for someone's inbox, whose
        manifest is read then). ``SessionError`` with a sentence for people otherwise."""
        from ... import media
        if not files:
            return []
        if not isinstance(files, list) or len(files) > MAX_FILES:
            raise SessionError(f"at most {MAX_FILES} files on a post")
        out = []
        for f in files:
            if not isinstance(f, dict):
                raise SessionError("a file is {\"name\", \"data\", \"alt\"}")
            name = str(f.get("name") or "file")
            try:
                octets = base64.b64decode(str(f.get("data") or ""), validate=True)
            except (binascii.Error, ValueError):
                raise SessionError(f"{name}: data is not base64") from None
            if not octets:
                raise SessionError(f"{name} is empty")
            try:
                p = media.prepare(name, octets)
            except ValueError as exc:
                raise SessionError(f"{name}: {exc}") from exc
            out.append(media.Prepared(p.name, p.media_type, p.octets, p.note,
                                      str(f.get("alt") or "").strip(), p.dim))
        if check:
            s.check_files(gid, out)
        return out
