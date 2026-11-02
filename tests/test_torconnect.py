"""#900: updates over Tor. pip gets a local CONNECT proxy that goes on through SOCKS."""

import asyncio

import pytest

from unseenet import service_update as su
from unseenet import torconnect


async def _echo_server():
    async def echo(r, w):
        while data := await r.read(100):
            w.write(b"echo:" + data)
            await w.drain()
        w.close()
    return await asyncio.start_server(echo, "127.0.0.1", 0)


async def _socks_server(target_port: int, asked: list):
    """A stand-in for Tor's SOCKS port: notes what was asked for, connects to the echo."""
    async def handle(r, w):
        n = (await r.readexactly(2))[1]
        await r.readexactly(n)
        w.write(b"\x05\x00")
        await w.drain()
        head = await r.readexactly(4)
        if head[3] == 3:
            name = await r.readexactly((await r.readexactly(1))[0])
        else:
            name = await r.readexactly(4)
        port = int.from_bytes(await r.readexactly(2), "big")
        asked.append((name.decode(errors="replace"), port))
        ur, uw = await asyncio.open_connection("127.0.0.1", target_port)
        w.write(b"\x05\x00\x00\x01" + bytes(4) + b"\x00\x00")
        await w.drain()
        await asyncio.gather(torconnect._pipe(r, uw), torconnect._pipe(ur, w))
    return await asyncio.start_server(handle, "127.0.0.1", 0)


async def test_connect_goes_through_socks_by_name():
    echo = await _echo_server()
    asked: list = []
    socks = await _socks_server(echo.sockets[0].getsockname()[1], asked)
    async with torconnect.TorConnect(socks.sockets[0].getsockname()[1]) as port:
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"CONNECT pypi.org:443 HTTP/1.1\r\nHost: pypi.org:443\r\n\r\n")
        await w.drain()
        assert (await r.readuntil(b"\r\n\r\n")).startswith(b"HTTP/1.1 200")
        w.write(b"hello")
        await w.drain()
        assert await r.read(100) == b"echo:hello"
        w.close()
        assert asked == [("pypi.org", 443)]          # the name goes to Tor, not to a resolver
        for request, code in ((b"GET http://pypi.org/ HTTP/1.1\r\n\r\n", b"405"),
                              (b"CONNECT pypi.org:80 HTTP/1.1\r\n\r\n", b"403")):
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(request)
            await w.drain()
            assert code in await r.read(100)
            w.close()
    echo.close()
    socks.close()


def test_which_tor(monkeypatch):
    seen = []
    work = lambda port: seen.append(port) or "current"     # noqa: E731
    assert su._with_tor(None, True, work) == "current" and seen == [None]
    monkeypatch.setattr(su, "_listening", lambda port: port == su.SYSTEM_TOR)
    su._with_tor(None, False, work)
    assert seen[-1] == su.SYSTEM_TOR
    with pytest.raises(su.Problem, match="--direct"):
        su._with_tor(9999, False, work)                  # given, but nothing listens
    monkeypatch.setenv(su.DIRECT_ENV, "1")
    assert su.direct_by_env()


def test_pip_gets_the_proxy(tmp_path, monkeypatch):
    calls = []

    class Done:
        returncode, stderr = 0, ""
    monkeypatch.setattr(su.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())

    class FakeThread:
        def __init__(self, socks):
            self.socks = socks

        def __enter__(self):
            return 4321

        def __exit__(self, *a):
            pass
    monkeypatch.setattr(torconnect, "TorConnectThread", FakeThread)
    monkeypatch.setattr(su.os, "chown", lambda *a: None, raising=False)   # Windows has none
    venv = tmp_path / "venv"
    venv.mkdir()
    su.Machine("x", venv, socks_port=9050).install(b"x==1\n", tmp_path / "work")
    assert calls[-1][calls[-1].index("--proxy") + 1] == "http://127.0.0.1:4321"
    su.Machine("x", venv).install(b"x==1\n", tmp_path / "work")
    assert "--proxy" not in calls[-1]                     # --direct


async def test_an_onion_index_over_plain_http():
    echo = await _echo_server()
    asked: list = []
    socks = await _socks_server(echo.sockets[0].getsockname()[1], asked)
    async with torconnect.TorConnect(socks.sockets[0].getsockname()[1]) as port:
        onion = "a" * 56 + ".onion"
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(f"CONNECT {onion}:80 HTTP/1.1\r\n\r\n".encode())
        await w.drain()
        assert (await r.readuntil(b"\r\n\r\n")).startswith(b"HTTP/1.1 200")
        w.close()
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"CONNECT pypi.org:80 HTTP/1.1\r\n\r\n")         # not an onion: no plain http
        await w.drain()
        assert b"403" in await r.read(100)
        w.close()
    echo.close()
    socks.close()
