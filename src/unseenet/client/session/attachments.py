"""Files on posts (UN-RFC 0027): preparing them, and checking them against a group.

Belongs here: reading files and preparing them for a post (``prepare_files``: the
type from the content, pictures cleaned of their metadata by ``client.media``), and
checking them before anything is computed or sent (``check_files``: does the group
take files, of this type and size, may they go here at all). ``post(files=...)`` in
posting.py sends them, as blobs on the same connection as the post (``BLOBPOST``).
And the other way: fetching the file a post carries from the node, checked against
its blob ID and size before it is anything (``fetch_blob``), a picture of it made
safe to show (``picture``), and whether a group's node carries files at all
(``node_files``).

Not here: the rules every node checks (``core.blobs``), cleaning a picture
(``client.media``), decoding one from the network (``client.decode``).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from collections import OrderedDict

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


BLOB_CACHE_OCTETS = 64 * 1024 * 1024     # checked blobs kept in memory while the client runs


class FileUnavailable(SessionError):
    """A file a post carries that cannot be had now. ``why`` is ``none`` (the node
    carries no files), ``later`` (it is still fetching it), ``gone`` (it has not got
    it) or ``wrong`` (it sent another file than the post names)."""

    def __init__(self, text: str, why: str):
        super().__init__(text)
        self.why = why


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

    # --- files on posts you read (UN-RFC 0027 sections 6.4, 9.2) ---------------
    def attachment(self, group_id: str, blob_id: str) -> tuple[dict, "Message"]:
        """The attachment with this blob ID on a post of this group that this client
        has read, and that post. ``SessionError`` when no such post carries it."""
        for msg in self.cache.get(group_id, {}).values():
            for a in msg.attachments:
                if a["blob"] == blob_id:
                    return a, msg
        raise SessionError("no post here carries that file")

    async def node_files(self, group_id: str) -> bool:
        """True when the node this group is read from carries files (it announces
        ``UNSEENET-BLOB``, UN-RFC 0027 section 6.1)."""
        async def run(c: Client):
            return c.capability("UNSEENET-BLOB") is not None
        return await self._call(run, self.node_for(group_id))

    def node_files_known(self, group_id: str) -> bool | None:
        """What ``node_files`` says, from the open connection to the group's node, without
        asking it anything; None while there is none."""
        c = self._clients.get(self.node_for(group_id) or "")
        return None if c is None else c.capability("UNSEENET-BLOB") is not None

    async def fetch_blob(self, group_id: str, blob_id: str) -> bytes:
        """The file a post in this group carries, from the group's node: checked against
        its blob ID and size before anything else is done with it (section 9.2), and
        kept in memory for a while. Files in encrypted groups are not possible yet.
        ``SessionError`` with a sentence for the user when it cannot be had."""
        from ...core import blobs as bl
        att, _ = self.attachment(group_id, blob_id)
        cache = self.__dict__.setdefault("_blob_cache", OrderedDict())
        if blob_id in cache:
            cache.move_to_end(blob_id)
            return cache[blob_id]

        async def run(c: Client):
            if c.capability("UNSEENET-BLOB") is None:
                return "none"
            try:
                return await c.blob(blob_id)
            except NNTPError as exc:
                if exc.code == 436:
                    return "later"
                raise
        got = await self._call(run, self.node_for(group_id))
        if got == "none":
            raise FileUnavailable("this node carries no files - another node may", "none")
        if got == "later":
            raise FileUnavailable("the node is still fetching this file - try again in a moment",
                                  "later")
        if got is None:
            raise FileUnavailable("the node does not have this file (any more)", "gone")
        if bl.blob_id(got) != blob_id or len(got) != att["size"]:
            raise FileUnavailable("the node sent another file than the post names - not shown",
                                  "wrong")
        cache[blob_id] = got
        while sum(len(v) for v in cache.values()) > BLOB_CACHE_OCTETS and len(cache) > 1:
            cache.popitem(last=False)
        return got

    async def picture(self, group_id: str, blob_id: str, *, asked: bool = False):
        """A picture a post in this group carries, made safe to show: fetched and
        checked (``fetch_blob``), then decoded and saved again in a separate, limited
        process (``client.decode``). Not from an author you ignore unless ``asked``
        (section 9.2). Returns a ``decode.Picture``; ``SessionError`` otherwise."""
        from .. import decode
        att, msg = self.attachment(group_id, blob_id)
        if not asked and self.is_ignored(msg.author_key):
            raise SessionError("you ignore this author: their pictures are not shown")
        octets = await self.fetch_blob(group_id, blob_id)
        try:
            return await decode.picture_async(octets, att["type"])
        except decode.DecodeError as exc:
            raise SessionError(str(exc)) from exc
