"""Using a Tor that is already running (#140): Tails, Whonix, a system tor."""

import asyncio

import pytest

from unseenet.client.session import Session, SessionError
from unseenet.core import tor
from unseenet.core.tor import Socks, TorError, check_socks, existing_tor, parse_socks
from unseenet.core.vault import Vault

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture(autouse=True)
def not_tails(monkeypatch):
    monkeypatch.delenv(tor.TOR_SOCKS_ENV, raising=False)
    monkeypatch.setattr(tor, "running_on_tails", lambda: False)


def test_parse_socks():
    assert parse_socks("9050") == ("127.0.0.1", 9050)
    assert parse_socks("127.0.0.1:9150") == ("127.0.0.1", 9150)
    assert parse_socks("10.152.152.10:9050") == ("10.152.152.10", 9050)    # Whonix
    assert parse_socks("[::1]:9050") == ("::1", 9050)
    assert parse_socks("localhost:9050") == ("localhost", 9050)
    for bad in ("tor.example:9050", "127.0.0.1:x", "127.0.0.1:0", "70000"):
        with pytest.raises(TorError):
            parse_socks(bad)                    # a name would be resolved outside Tor


def test_which_tor(monkeypatch):
    assert existing_tor(None) is None                           # our own, by default
    assert existing_tor({"socks": "127.0.0.1:9050"}) == Socks("127.0.0.1", 9050, "setting")
    monkeypatch.setattr(tor, "running_on_tails", lambda: True)
    assert existing_tor(None) == Socks("127.0.0.1", 9050, "Tails")
    assert existing_tor({"socks": "auto"}).source == "Tails"
    assert existing_tor({"socks": "own"}) is None                # always our own, even on Tails
    monkeypatch.setenv(tor.TOR_SOCKS_ENV, "9150")                # the environment wins
    assert existing_tor({"socks": "own"}) == Socks("127.0.0.1", 9150, tor.TOR_SOCKS_ENV)
    monkeypatch.setenv(tor.TOR_SOCKS_ENV, "own")
    assert existing_tor({"socks": "127.0.0.1:9050"}) is None


def test_isolation_username_per_node():
    s = Socks("127.0.0.1", 9050)
    a = tor._proxy_url(s, "aaaa.onion")
    b = tor._proxy_url(s, "bbbb.onion")
    assert a != b and a.startswith("socks5://unseenet-aaaa.onion:") and a.endswith("@127.0.0.1:9050")
    assert tor._proxy_url(9050, "aaaa.onion") == "socks5://127.0.0.1:9050"
    assert str(Socks("::1", 9050)) == "[::1]:9050"


async def _fake_socks(reply: bytes):
    async def handle(reader, writer):
        await reader.readexactly(4)
        writer.write(reply)
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_check_socks():
    server, port = await _fake_socks(b"\x05\x00")
    async with server:
        await check_socks(Socks("127.0.0.1", port, "test"))
    server, port = await _fake_socks(b"HTTP")
    async with server:
        with pytest.raises(TorError, match="not a SOCKS5 port"):
            await check_socks(Socks("127.0.0.1", port, "test"))
    with pytest.raises(TorError, match="no Tor answers"):
        await check_socks(Socks("127.0.0.1", port, "test"), timeout=2)    # closed by now


async def test_session_uses_the_running_tor_and_starts_none(tmp_path, monkeypatch):
    server, port = await _fake_socks(b"\x05\x00")
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    monkeypatch.setattr(tor.TorProcess, "find_binary",
                        staticmethod(lambda *a: pytest.fail("must not start a Tor")))
    async with server:
        await s.set_tor(f"127.0.0.1:{port}")
        assert s.tor_setting() == f"127.0.0.1:{port}"
        assert await s._ensure_tor(lambda *_: None) == Socks("127.0.0.1", port, "setting")
        assert s.tor is None
    await s.set_bridges("snowflake")
    assert s.tor_setting() == f"127.0.0.1:{port}"            # bridges keep the Tor choice
    await s.set_tor("auto")
    assert s.tor_setting() == "auto" and s.tor_in_use() is None
    with pytest.raises(SessionError):
        await s.set_tor("tor.example:9050")


async def test_session_says_when_the_running_tor_is_gone(tmp_path, monkeypatch):
    monkeypatch.setenv(tor.TOR_SOCKS_ENV, "127.0.0.1:1")
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    with pytest.raises(SessionError, match="no Tor answers on 127.0.0.1:1"):
        await s._ensure_tor(lambda *_: None)
