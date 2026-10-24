"""Shared NNTP line handling and a small async ONNTP client (UN-RFC 0005)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .core import tor

MAX_LINE = 512
RECONCILE_MAX_BYTES = 16 * 1024 * 1024    # one XUN-RECONCILE message, either way
MANIFESTS_MAX = 256                       # lines in one XUN-MANIFESTS request (UN-RFC 0041)
MANIFESTS_ANSWER_BYTES = 1024 * 1024      # articles in one XUN-MANIFESTS answer (2.3)
MANIFEST_MAX_BYTES = 128 * 1024           # one manifest article, read defensively
BLOB_MAX_BYTES = 4 * 1024 * 1024 + 40     # one blob, encrypted ones 40 octets more (UN-RFC 0027)


def dot_stuff(raw: bytes) -> bytes:
    """Article bytes -> multi-line block terminated by '.'."""
    lines = raw.replace(b"\r\n", b"\n").split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    out = [b"." + ln if ln.startswith(b".") else ln for ln in lines]
    return b"\r\n".join(out) + b"\r\n.\r\n"


async def read_block(reader: asyncio.StreamReader, limit: int = 70000) -> bytes:
    """Read a dot-terminated block and undo dot-stuffing. Returns CRLF-joined bytes."""
    lines: list[bytes] = []
    size = 0
    while True:
        line = await reader.readline()
        if not line:
            raise ConnectionError("connection closed inside block")
        line = line.rstrip(b"\r\n")
        if line == b".":
            break
        if line.startswith(b".."):
            line = line[1:]
        size += len(line) + 2
        if size <= limit:
            lines.append(line)
    if size > limit:
        raise ValueError("block too large")
    if not lines:
        return b""
    return b"\r\n".join(lines) + b"\r\n"


def strip_reader_headers(raw: bytes) -> bytes:
    """Remove Path/Xref that a node adds for newsreaders (UN-RFC 0005, 3)."""
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = [ln for ln in head.split(b"\r\n") if not ln.lower().startswith((b"path:", b"xref:"))]
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


class NNTPError(Exception):
    def __init__(self, code: int, text: str):
        super().__init__(f"{code} {text}")
        self.code, self.text = code, text


@dataclass
class ManifestAnswer:
    """One answer to a line of XUN-MANIFESTS (UN-RFC 0041 section 2.2)."""
    code: int                   # 220 article, 223 unchanged, 411 none, 431 ask again
    group_id: str
    message_id: str | None = None
    raw: bytes | None = None    # the article, for 220


class Client:
    """Minimal ONNTP client used by the CLI and by peering."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self.capabilities: list[str] = []

    @classmethod
    async def connect(cls, address: str, socks_port: int | None = None) -> "Client":
        c = cls(*await tor.open_connection(address, socks_port))
        code, text = await c._response()
        if code not in (200, 201):
            raise NNTPError(code, text)
        return c

    async def _response(self) -> tuple[int, str]:
        line = (await self.reader.readline()).decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            raise ConnectionError("connection closed")
        if len(line) < 3 or not line[:3].isdigit():
            # Not a status line: we are out of step with the node (e.g. the rest of
            # an answer whose reader was cancelled). The connection cannot be used.
            raise ConnectionError(f"unexpected reply from the node: {line[:40]!r}")
        return int(line[:3]), line[4:]

    async def command(self, line: str, expect: tuple[int, ...] = ()) -> tuple[int, str]:
        self.writer.write(line.encode() + b"\r\n")
        await self.writer.drain()
        code, text = await self._response()
        if expect and code not in expect:
            raise NNTPError(code, text)
        return code, text

    async def multiline(self, line: str, expect: int) -> list[str]:
        await self.command(line, (expect,))
        return (await read_block(self.reader)).decode("utf-8", "replace").splitlines()

    async def fetch_capabilities(self) -> list[str]:
        self.capabilities = await self.multiline("CAPABILITIES", 101)
        return self.capabilities

    def capability(self, name: str) -> str | None:
        for cap in self.capabilities:
            parts = cap.split(maxsplit=1)
            if parts and parts[0].upper() == name.upper():
                return parts[1] if len(parts) > 1 else ""
        return None

    async def blobpost(self, blob_id: str, octets: bytes) -> tuple[int, str]:
        """``BLOBPOST`` (UN-RFC 0027 section 6): stage a blob on this connection for the
        next POST. ``245`` staged (also when the node has it already), ``445`` not
        taken (``unsupported``: the node carries no files; ``refused``, ``size``,
        ``limit``, ``hash``)."""
        code, text = await self.command(f"BLOBPOST {blob_id} {len(octets)}")
        if code == 345:
            self.writer.write(octets)
            await self.writer.drain()
            code, text = await self._response()
        return code, text

    async def blob(self, blob_id: str) -> bytes | None:
        """``BLOB`` (UN-RFC 0027 section 6.4): the octets the node sends for a blob, or
        None when it has not got it (``430``). ``NNTPError`` 436 while the node is still
        fetching it from a peer. Checking the octets against the ID is the caller's
        (section 9.2): until then they are nothing."""
        code, text = await self.command(f"BLOB {blob_id}")
        if code == 430:
            return None
        if code != 226:
            raise NNTPError(code, text)
        try:
            size = int(text.split()[0])
        except (IndexError, ValueError):
            raise ConnectionError(f"unexpected reply to BLOB: {text[:40]!r}") from None
        if not 0 < size <= BLOB_MAX_BYTES:
            raise ConnectionError(f"a blob of {size} octets is not possible")
        return await self.reader.readexactly(size)

    async def post(self, raw: bytes) -> tuple[int, str]:
        await self.command("POST", (340,))
        self.writer.write(dot_stuff(raw))
        await self.writer.drain()
        return await self._response()

    async def article(self, ident: str) -> bytes | None:
        code, _ = await self.command(f"ARTICLE {ident}")
        if code != 220:
            return None
        return await read_block(self.reader)

    async def group(self, group_id: str) -> tuple[int, int, int]:
        _, text = await self.command(f"GROUP {group_id}", (211,))
        count, low, high = (int(x) for x in text.split()[:3])
        return count, low, high

    async def list_active(self) -> list[str]:
        return await self.multiline("LIST ACTIVE", 215)

    async def newnews(self, wildmat: str, since: str) -> list[str]:
        return await self.multiline(f"NEWNEWS {wildmat} {since} GMT", 230)

    async def reconcile(self, lines: list[str]) -> list[str]:
        """One round of XUN-RECONCILE (UN-RFC 0040 section 4.3): range lines out,
        the node's range lines back. Use with ``core.reconcile.reconcile``."""
        self.writer.write(b"XUN-RECONCILE\r\n" + dot_stuff("\r\n".join(lines).encode()))
        await self.writer.drain()
        code, text = await self._response()
        if code != 295:
            raise NNTPError(code, text)
        block = await read_block(self.reader, RECONCILE_MAX_BYTES)
        return block.decode("utf-8", "replace").splitlines()

    async def manifests(self, entries: list[tuple[str, str | None]]) -> list[ManifestAnswer]:
        """One XUN-MANIFESTS request (UN-RFC 0041 section 2): ``(group_id, held
        Message-ID or None)`` in, one answer per entry back, in order."""
        lines = [f"{gid} {held}" if held else gid for gid, held in entries]
        self.writer.write(b"XUN-MANIFESTS\r\n" + dot_stuff("\r\n".join(lines).encode()))
        await self.writer.drain()
        code, text = await self._response()
        if code != 296:
            raise NNTPError(code, text)
        if text.split()[:1] != [str(len(entries))]:
            raise ConnectionError(f"unexpected XUN-MANIFESTS answer: {text[:40]!r}")
        out = []
        for gid, _ in entries:
            code, text = await self._response()
            parts = text.split()
            if code in (220, 223):
                if len(parts) < 3 or parts[2] != gid:
                    raise ConnectionError(f"XUN-MANIFESTS answer out of order: {text[:60]!r}")
                raw = await read_block(self.reader, MANIFEST_MAX_BYTES) if code == 220 else None
                out.append(ManifestAnswer(code, gid, parts[1], raw))
            elif code in (411, 431):
                if parts[:1] != [gid]:
                    raise ConnectionError(f"XUN-MANIFESTS answer out of order: {text[:60]!r}")
                out.append(ManifestAnswer(code, gid))
            else:
                raise ConnectionError(f"unexpected XUN-MANIFESTS answer: {code} {text[:40]!r}")
        return out

    async def manifests_all(self, entries: list[tuple[str, str | None]]
                            ) -> dict[str, ManifestAnswer]:
        """XUN-MANIFESTS for any number of groups: in requests of the node's maximum,
        asking again for lines answered 431 (section 2.3). Keyed by Group ID."""
        try:
            limit = max(1, int((self.capability("UNSEENET-MANIFESTS") or "").split()[0]))
        except (IndexError, ValueError):
            limit = MANIFESTS_MAX
        todo = list(dict(entries).items())          # no Group ID twice (2.1)
        out: dict[str, ManifestAnswer] = {}
        while todo:
            batch, todo = todo[:limit], todo[limit:]
            answers = await self.manifests(batch)
            again = [(a.group_id, dict(batch)[a.group_id]) for a in answers if a.code == 431]
            if len(again) == len(batch):            # a node must send at least one
                raise ConnectionError("XUN-MANIFESTS: the node sent nothing")
            out.update((a.group_id, a) for a in answers if a.code != 431)
            todo = again + todo
        return out

    async def quit(self) -> None:
        try:
            await self.command("QUIT")
        finally:
            self.writer.close()
