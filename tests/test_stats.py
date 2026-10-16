"""The node's local stats interface for unseenet-monitor (node/stats.py)."""

import logging
import shutil
import tempfile
import sys
from pathlib import Path

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node import stats as st
from unseenet.node.server import Node, NodeConfig, PeerConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


def test_only_this_computer():
    assert st.parse_listen("127.0.0.1:1120") == ("tcp", 1120)
    assert st.parse_listen("localhost:1120") == ("tcp", 1120)
    assert st.parse_listen("[::1]:1120") == ("tcp", 1120)
    assert st.parse_listen("/run/unseenet/monitor.sock")[0] == "unix"
    for bad in ("0.0.0.0:1120", "192.168.1.5:1120", "example.org:1120"):
        with pytest.raises(ValueError):
            st.parse_listen(bad)


async def _node_with_traffic(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(tmp_path / "articles.sqlite"),
                NodeConfig(min_pow=8, forward_delay=(0, 0),
                           peers=[PeerConfig(name="friend", address="127.0.0.1:9", key=None)]))
    server = await node.serve("127.0.0.1", 0)
    s = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("a", "A")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    gid = await s.create_group("dk.snak", "open", min_pow=10)
    await s.post(gid, "Hej", "Hej\n")
    await s.fetch_group(gid)                       # reads two articles
    return node, server, s, gid


async def test_snapshot_counts(tmp_path, monkeypatch):
    node, server, s, gid = await _node_with_traffic(tmp_path, monkeypatch)
    try:
        node.accept(b"not an article")
    except Exception:  # noqa: BLE001
        pass
    snap = await node.stats.snapshot(node, tmp_path)
    assert snap["v"] == 1
    assert snap["traffic"]["accepted"]["client"] == 2         # manifest and post
    assert sum(snap["traffic"]["rejected"].values()) >= 1
    assert snap["traffic"]["served"] >= 2
    assert sum(snap["traffic"]["per_minute"]["accepted"]) == 2
    assert len(snap["traffic"]["per_minute"]["accepted"]) == 60
    assert snap["connections"]["total"] >= 1
    assert snap["store"]["groups"] == 1 and snap["store"]["articles"] == 2
    assert snap["store"]["busiest"] == [[gid, 2]] or snap["store"]["busiest"] == [(gid, 2)]
    assert snap["store"]["db_bytes"] > 0 and snap["store"]["disk_free"] > 0
    peer = snap["peers"][0]
    assert peer["name"] == "friend" and peer["queue"] == 2      # waiting for the peer
    assert snap["tor"] == {"state": "off"}
    # nothing about who read what: no group names outside the store's own counts
    flat = repr({k: v for k, v in snap.items() if k != "store"})
    assert gid not in flat
    await s.close()
    server.close()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix sockets")
async def test_interface_over_a_unix_socket(tmp_path, monkeypatch):
    node, server, s, gid = await _node_with_traffic(tmp_path, monkeypatch)
    logging.getLogger("unseenet").addHandler(node.stats.log)
    logging.getLogger("unseenet").setLevel(logging.INFO)
    logging.getLogger("unseenet.node").info("hello from the node")
    # pytest's tmp_path is too long for a Unix socket on macOS (104 bytes)
    short = Path(tempfile.mkdtemp(prefix="un-", dir="/tmp"))
    path = short / "monitor.sock"
    mon = await st.serve(node.stats, node, str(path), tmp_path)
    assert (path.stat().st_mode & 0o777) == 0o660               # owner and group only
    snap = await st.fetch(str(path))
    assert snap["store"]["articles"] == 2
    lines = await st.fetch(str(path), "log 10")
    assert any("hello from the node" in ln for ln in lines)
    assert "error" in await st.fetch(str(path), "shutdown")      # read-only: nothing else
    mon.close()
    shutil.rmtree(short, ignore_errors=True)
    logging.getLogger("unseenet").removeHandler(node.stats.log)
    await s.close()
    server.close()


async def test_interface_on_loopback(tmp_path, monkeypatch):
    node, server, s, gid = await _node_with_traffic(tmp_path, monkeypatch)
    mon = await st.serve(node.stats, node, "127.0.0.1:0", tmp_path)
    port = mon.sockets[0].getsockname()[1]
    assert mon.sockets[0].getsockname()[0] == "127.0.0.1"
    snap = await st.fetch(f"127.0.0.1:{port}")
    assert snap["node"]["key"] == node.key.key_text
    mon.close()
    await s.close()
    server.close()


def test_warnings():
    snap = {"tor": {"state": "down"}, "node": {"uptime": 3600},
            "peers": [{"name": "p", "last_error": "unreachable", "last_sent": None,
                       "last_error_at": 1.0, "queue": 5000}],
            "store": {"disk_free": 10 * 1024 * 1024}}
    w = st.warnings(snap)
    assert any("Tor is not running" in x for x in w)
    assert any("peer p: unreachable" in x for x in w)
    assert any("5000 articles waiting" in x for x in w)
    assert any("MB free" in x for x in w)


def test_a_unix_socket_path_that_is_too_long_is_refused():
    import asyncio
    long = "/tmp/" + "x" * 200 + "/monitor.sock"
    with pytest.raises(ValueError, match="too long"):
        asyncio.run(st.serve(None, None, long))
