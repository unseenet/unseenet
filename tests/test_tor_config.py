"""How Tor is started: bundled libraries, bridges, settings (no network needed)."""

import json
import sys
from pathlib import Path

import pytest

from unseenet.core import tor as tormod
from unseenet.core.tor import (TorError, TorProcess, bridge_transports, bridges_for,
                               builtin_bridges, launch_command)

OBFS4 = "obfs4 192.0.2.1:443 0123456789ABCDEF0123456789ABCDEF01234567 cert=abc iat-mode=0"


def fake_bundle(tmp_path: Path) -> Path:
    folder = tmp_path / "tor"
    (folder / "pluggable_transports").mkdir(parents=True)
    tor = folder / ("tor.exe" if sys.platform == "win32" else "tor")
    tor.write_text("")
    (folder / "libevent-2.1.so.7").write_text("")
    (folder / "pluggable_transports" / ("lyrebird.exe" if sys.platform == "win32" else "lyrebird")).write_text("")
    (folder / "pluggable_transports" / "pt_config.json").write_text(json.dumps(
        {"bridges": {"obfs4": [OBFS4], "snowflake": ["snowflake 192.0.2.3:80 AAAA fingerprint=AAAA"]}}))
    return tor


def test_builtin_and_custom_bridges(tmp_path):
    tor = str(fake_bundle(tmp_path))
    assert bridges_for(None, tor) is None
    assert bridges_for({"mode": "off"}, tor) is None
    assert bridges_for({"mode": "obfs4"}, tor) == [OBFS4]
    assert builtin_bridges(tor, "snowflake")[0].startswith("snowflake ")
    assert bridges_for({"mode": "custom", "custom": [" " + OBFS4, ""]}, tor) == [OBFS4]
    with pytest.raises(TorError):
        bridges_for({"mode": "custom", "custom": []}, tor)
    with pytest.raises(TorError, match="portable builds"):
        bridges_for({"mode": "obfs4"}, str(tmp_path / "elsewhere" / "tor"))


def test_transports_needed():
    assert bridge_transports([OBFS4, "snowflake 1.2.3.4:1 X"]) == {"obfs4", "snowflake"}
    assert bridge_transports(["192.0.2.7:9001 0123"]) == set()          # a plain bridge


def test_torrc_with_bridges(tmp_path):
    tor = fake_bundle(tmp_path)
    rc = TorProcess(tmp_path / "data", str(tor), bridges=[OBFS4])._torrc()
    assert "UseBridges 1" in rc and f"Bridge {OBFS4}" in rc
    plugin = next(ln for ln in rc.splitlines() if ln.startswith("ClientTransportPlugin"))
    assert "obfs4" in plugin and "snowflake" in plugin
    assert str(tmp_path) not in plugin.split(" exec ")[-1].split()[-1]    # relative path
    assert "UseBridges" not in TorProcess(tmp_path / "d", str(tor))._torrc()


@pytest.mark.skipif(sys.platform == "win32", reason="no library path variables on Windows")
def test_bundled_libraries_come_first(tmp_path, monkeypatch):
    tor = fake_bundle(tmp_path)
    var = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
    monkeypatch.setenv(var, "/somewhere")
    _, env = launch_command(str(tor))
    assert env[var].split(":")[0] == str(tor.parent.resolve())
    # a frozen client gives the child the original path, not its own libraries
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv(var, "/frozen/_internal")
    monkeypatch.setenv(f"{var}_ORIG", "/original")
    _, env = launch_command(str(tor))
    assert env[var].split(":") == [str(tor.parent.resolve()), "/original"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_not_executable_runs_through_the_loader(tmp_path, monkeypatch):
    tor = fake_bundle(tmp_path)
    tor.chmod(0o644)                                   # as on a FAT stick mounted showexec
    monkeypatch.setattr(tormod.os.path, "exists", lambda p: True)
    argv, _ = launch_command(str(tor))
    assert argv[0].startswith("/lib") and argv[1] == str(tor)


async def test_session_bridge_setting(tmp_path):
    from unseenet.client.session import Session, SessionError
    from unseenet.core.vault import Vault
    s = Session(Vault.open(tmp_path / "v.vault", "pw", ops=1, mem=8192 * 1024), status=lambda *_: None)
    assert s.bridge_setting()["mode"] == "off"
    await s.set_bridges("custom", [OBFS4])
    assert s.bridge_setting() == {"mode": "custom", "custom": [OBFS4]}
    with pytest.raises(SessionError):
        await s.set_bridges("custom", [])
    with pytest.raises(SessionError):
        await s.set_bridges("teleport")


async def test_onion_refusals_become_connection_errors(monkeypatch):
    """Tor's SOCKS refusals are retried, then reported as ConnectionError (which
    the client handles) with a readable reason - not a crash."""
    from python_socks import ProxyError
    calls = []

    class FakeProxy:
        async def connect(self, dest_host, dest_port):
            calls.append(dest_host)
            raise ProxyError("Host unreachable", error_code=0x04)

    monkeypatch.setattr(tormod.Proxy, "from_url", staticmethod(lambda *a, **k: FakeProxy()))
    monkeypatch.setattr(tormod, "ONION_RETRY_PAUSES", (0.0, 0.0))
    with pytest.raises(ConnectionError, match="node may be down"):
        await tormod.open_connection("abc.onion:119", 9050)
    assert len(calls) == 3
    calls.clear()

    class BadAddress(FakeProxy):
        async def connect(self, dest_host, dest_port):
            calls.append(dest_host)
            raise ProxyError("bad", error_code=0xF6)
    monkeypatch.setattr(tormod.Proxy, "from_url", staticmethod(lambda *a, **k: BadAddress()))
    with pytest.raises(ConnectionError, match="typos"):
        await tormod.open_connection("abc.onion:119", 9050)
    assert len(calls) == 1                         # a wrong address is not retried
