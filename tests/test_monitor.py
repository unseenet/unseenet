"""unseenet-monitor reads a node's stats interface and shows it."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.monitor import MonitorApp, ago, duration, size
from unseenet.node import stats as st
from unseenet.node.server import Node, NodeConfig, PeerConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


def test_formatting():
    assert ago(None) == "never"
    assert ago(100, now=130) == "30s ago" and ago(100, now=100 + 7200) == "2h 0m ago"
    assert duration(90061) == "1d 1h 1m"
    assert size(2048) == "2.0 KB" and size(None) == "?"


async def _node(tmp_path, monkeypatch, name="node1"):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(tmp_path / f"{name}.sqlite"),
                NodeConfig(name=name, min_pow=8, forward_delay=(0, 0),
                           peers=[PeerConfig(name="friend", address="127.0.0.1:9")]))
    server = await node.serve("127.0.0.1", 0)
    s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("a", "A")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    gid = await s.create_group("dk.snak", "open", min_pow=10)
    for i in range(3):
        await s.post(gid, f"Hej {i}", "Hej\n")
    await s.close()
    node.stats.peer_error("friend", "unreachable: connection refused")
    mon = await st.serve(node.stats, node, "127.0.0.1:0", tmp_path)
    return node, server, mon, f"127.0.0.1:{mon.sockets[0].getsockname()[1]}", gid


async def wait_for(pilot, cond, tries=200):
    for _ in range(tries):
        if cond():
            return True
        await pilot.pause(0.05)
    return False


@pytest.mark.parametrize("size_", [(80, 24), (120, 34)])
async def test_monitor_shows_a_node(tmp_path, monkeypatch, size_):
    node, server, mon, where, gid = await _node(tmp_path, monkeypatch)
    app = MonitorApp([where], refresh=0.5)
    async with app.run_test(size=size_) as pilot:
        assert await wait_for(pilot, lambda: app.snapshot is not None)
        await pilot.pause(0.3)
        text = str(app.query_one("#node").render())
        assert "node1" in text and "1 groups, 4 articles" in text
        peers = app.query_one("#peers-table")
        assert peers.row_count == 1 and "friend" in str(peers.get_row_at(0)[0])
        assert "unreachable" in str(peers.get_row_at(0)[7])
        assert app.query_one("#groups-table").row_count == 1
        assert sum(app.query_one("#spark-accepted").data) == 4
        app.save_screenshot(str(tmp_path / f"monitor-{size_[0]}.svg"))
        await pilot.press("2")
        await pilot.pause(0.2)
        assert app.query_one("TabbedContent").active == "groups"
        await pilot.press("q")
    mon.close()
    server.close()


async def test_monitor_several_nodes_and_one_down(tmp_path, monkeypatch):
    node, server, mon, where, gid = await _node(tmp_path, monkeypatch)
    app = MonitorApp([where, "127.0.0.1:9"], refresh=60)
    async with app.run_test(size=(100, 30)) as pilot:
        assert await wait_for(pilot, lambda: app.snapshot is not None)
        assert app.check_action("next_node", ())
        await pilot.press("n")
        # A refused connection takes about two seconds on Windows
        assert await wait_for(pilot, lambda: "Not reachable" in str(app.query_one("#node").render()),
                              tries=400)
        await pilot.press("p")
        assert await wait_for(pilot, lambda: "node1" in str(app.query_one("#node").render()))
        await pilot.press("q")
    mon.close()
    server.close()
