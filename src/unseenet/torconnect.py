"""A local HTTP CONNECT proxy that goes on through Tor's SOCKS port.

pip speaks HTTP proxies but not SOCKS (that needs PySocks, which a server's
environment does not have). ``unseenet-service-update`` runs pip with
``--proxy http://127.0.0.1:<port>`` pointing here, so every download of an update -
the index and each package - goes over Tor, and nobody can tell from them which
machine runs a server (#900).

Only ``CONNECT host:443`` is relayed (HTTPS: the TLS stays end to end, between pip and
the index); anything else is refused. It listens on 127.0.0.1 only.

Belongs here: the relay. Not here: starting Tor (``core/tor.py``), updating
(``service_update.py``)."""

from __future__ import annotations

import asyncio
import contextlib
import threading

from python_socks.async_.asyncio import Proxy

ALLOWED_PORTS = {443}
HEAD_LIMIT = 8192


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(1 << 16):
            writer.write(data)
            await writer.drain()
    except (OSError, ConnectionError, asyncio.CancelledError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()


class TorConnect:
    """``async with TorConnect(socks_port) as port:`` - a proxy on 127.0.0.1:port."""

    def __init__(self, socks_port: int, socks_host: str = "127.0.0.1"):
        self.socks = f"socks5://{socks_host}:{socks_port}"
        self.server: asyncio.base_events.Server | None = None
        self.port = 0

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError,
                ConnectionError):
            writer.close()
            return
        line = head.split(b"\r\n", 1)[0].decode("latin-1").split()
        if len(head) > HEAD_LIMIT or len(line) != 3 or line[0] != "CONNECT":
            writer.write(b"HTTP/1.1 405 Only CONNECT\r\n\r\n")
            writer.close()
            return
        host, _, port = line[1].rpartition(":")
        if not host or not port.isdigit() or int(port) not in ALLOWED_PORTS:
            writer.write(b"HTTP/1.1 403 Only HTTPS\r\n\r\n")
            writer.close()
            return
        try:
            sock = await Proxy.from_url(self.socks, rdns=True).connect(
                host.strip("[]"), int(port), timeout=120)
            up_reader, up_writer = await asyncio.open_connection(sock=sock)
        except Exception:  # noqa: BLE001 - whatever Tor said, the client gets a 502
            writer.write(b"HTTP/1.1 502 Not reachable over Tor\r\n\r\n")
            writer.close()
            return
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))

    async def __aenter__(self) -> int:
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def __aexit__(self, *exc) -> None:
        if self.server is not None:
            self.server.close()
            with contextlib.suppress(Exception):
                await self.server.wait_closed()


class TorConnectThread:
    """The same, in a thread of its own, for code that is not async (pip runs as a
    subprocess while the updater waits): ``with TorConnectThread(9050) as port:``."""

    def __init__(self, socks_port: int, socks_host: str = "127.0.0.1"):
        self.proxy = TorConnect(socks_port, socks_host)
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self._stop: asyncio.Event | None = None

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)

        async def main() -> None:
            self._stop = asyncio.Event()
            async with self.proxy:
                self.ready.set()
                await self._stop.wait()
        self.loop.run_until_complete(main())

    def __enter__(self) -> int:
        self.thread.start()
        if not self.ready.wait(10):
            raise OSError("the local proxy to Tor did not start")
        return self.proxy.port

    def __exit__(self, *exc) -> None:
        if self._stop is not None:
            self.loop.call_soon_threadsafe(self._stop.set)
        self.thread.join(10)
