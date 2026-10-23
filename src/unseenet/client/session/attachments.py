"""Files on posts (UN-RFC 0027): preparing them, and checking them against a group.

Belongs here: reading files and preparing them for a post (``prepare_files``: the
type from the content, pictures cleaned of their metadata by ``client.media``), and
checking them before anything is computed or sent (``check_files``: does the group
take files, of this type and size, may they go here at all). ``post(files=...)`` in
posting.py sends them, as blobs on the same connection as the post (``BLOBPOST``).

Not here: the rules every node checks (``core.blobs``), cleaning a picture
(``client.media``).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class AttachmentsMixin:
    def prepare_files(self, paths) -> list:
        """Read files and prepare them for a post: a list of ``media.Prepared``, each
        with its media type found from its content, a picture saved again without
        its metadata (GPS, time, camera), and a ``note`` for what was not cleaned.
        ``SessionError`` if a file cannot be read or is not a picture it claims to be."""
        from .. import media
        out = []
        for path in paths:
            p = Path(path)
            try:
                octets = p.read_bytes()
            except OSError as exc:
                raise SessionError(f"cannot read {p.name}: {exc.strerror or exc}") from exc
            try:
                out.append(media.prepare(p.name, octets))
            except ValueError as exc:
                raise SessionError(f"{p.name}: {exc}") from exc
        return out

    def check_files(self, group_id: str, files) -> None:
        """Raise ``SessionError`` with a sentence for the user unless these prepared
        files may go on a post here: the group takes files (its manifest's
        ``attachments``, UN-RFC 0027 section 5.1), of these types and sizes, at most
        four and 8 MiB together, and not yet in closed groups, inboxes or moderated
        groups - their files are encrypted, which comes later."""
        from ...core import blobs as bl
        files = list(files)
        if not files:
            return
        entry = self.group_entry(group_id)
        data = self.manifest_data(group_id)
        gtype = data.get("type") or entry.get("type")
        if gtype in ("closed", "inbox") or group_id == self.my_inbox:
            raise SessionError("files in closed groups and private posts are not possible yet")
        if gtype == "moderated" and not self.moderates(group_id):
            raise SessionError("files in moderated groups are not possible yet")
        att = data.get("attachments")
        if not isinstance(att, dict):
            raise SessionError("this group takes no files - its owner can allow them")
        if len(files) > bl.MAX_PER_ARTICLE:
            raise SessionError(f"at most {bl.MAX_PER_ARTICLE} files on a post")
        if sum(len(f.octets) for f in files) > bl.MAX_TOTAL:
            raise SessionError(f"at most {bl.MAX_TOTAL // (1024 * 1024)} MiB of files on a post")
        for f in files:
            if len(f.octets) > att["max_size"]:
                raise SessionError(f"{f.name} is {len(f.octets) // 1024} KiB; this group takes "
                                   f"files up to {att['max_size'] // 1024} KiB")
            if not bl.type_allowed(f.media_type, att.get("types")):
                raise SessionError(f"{f.name} is {f.media_type}, which this group does not take")
