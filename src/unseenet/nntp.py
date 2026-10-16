"""Shared NNTP line handling and a small async ONNTP client (UN-RFC 0005)."""

from __future__ import annotations

import asyncio

from .core import tor

MAX_LINE = 512


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

    async def quit(self) -> None:
        try:
            await self.command("QUIT")
        finally:
            self.writer.close()
