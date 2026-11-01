"""Pulling from announced nodes (UN-RFC 0055 section 5.5): a node finds peers by itself,
checks their keys, and catches up from them without an agreement."""

import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError
from unseenet.core.store import Store
from unseenet.node import announcing
from unseenet.node import autopeers as ap
from unseenet.node.server import Node, NodeConfig, PeerConfig

from test_announcing import BITS, announce_group, hold  # noqa: F401  (fixture)


def copy(src: Node, dst: Node, *, only_key: str | None = None) -> None:
    """Hand ``dst`` what ``src`` holds (ripe@ chains and announcements), as a peer would."""
    for mid, gid in src.store.received_since(0):
        raw = src.store.get(mid)
        if raw is None or (only_key and only_key.encode() not in raw):
            continue
        try:
            dst.accept(raw, from_peer=True)
        except ArticleError as exc:
            assert exc.reason in ("duplicate", "later"), exc


async def announced(node: Node, tmp_path, address: str) -> None:
    d = tmp_path / node.config.name
    d.mkdir()
    assert await announcing.Announcer(node, d, address, ripen_to=0).run_once()


@pytest.fixture(autouse=True)
def _group(announce_group, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ap, "NODES_ANNOUNCE_GROUP", announce_group.group)


def new_node(name: str, group) -> Node:
    n = Node(Store(), NodeConfig(name=name, min_pow=BITS, forward_delay=(0, 0)),
             key=crypto.Identity.generate())
    hold(n, group)
    return n


@pytest.mark.usefixtures("ripening_rules")
async def test_a_node_pulls_from_the_nodes_it_finds_announced(tmp_path, announce_group,
                                                              monkeypatch):
    pytest.importorskip("chiavdf")
    monkeypatch.setenv("UNSEENET_TEST_ADDRESSES", "1")          # nodes on 127.0.0.1
    a, b, c = (new_node(n, announce_group) for n in ("a", "b", "c"))
    server = await b.serve("127.0.0.1", 0)
    b_addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    await announced(b, tmp_path, b_addr)
    await announced(c, tmp_path, "127.0.0.1:9")                   # c told only b about itself
    copy(c, b)
    copy(b, a, only_key=b.key.key_text)                          # a knows of b, not of c
    assert [x.name for x, _ in ap.candidates(a, ap.datetime.now(ap.timezone.utc))] == ["b"]
    auto = ap.AutoPeers(a, None, count=3, interval=1)
    results = await auto.run_once()
    assert list(results) == [b.key.key_text] and results[b.key.key_text]["accepted"] >= 1
    names = {x.name for x in ap.held_announcements(a)}
    assert names == {"b", "c"}                                   # c's came through b
    # a node does not pull from itself, nor from a configured peer
    assert all(x.key != a.key.key_text for x, _ in ap.candidates(a, ap.datetime.now(ap.timezone.utc)))
    a.config.peers = [PeerConfig(name="b", address=b_addr, key=b.key.key_text)]
    assert "b" not in {x.name for x, _ in ap.candidates(a, ap.datetime.now(ap.timezone.utc))}
    server.close()


@pytest.mark.usefixtures("ripening_rules")
async def test_a_node_with_another_key_is_left_out(tmp_path, announce_group, monkeypatch):
    """Section 5.3: the node at the address must have the key that announced it."""
    pytest.importorskip("chiavdf")
    monkeypatch.setenv("UNSEENET_TEST_ADDRESSES", "1")
    a, b, liar = (new_node(n, announce_group) for n in ("a", "b", "liar"))
    server = await b.serve("127.0.0.1", 0)
    b_addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    await announced(liar, tmp_path, b_addr)                        # b's address, its own key
    copy(liar, a)
    auto = ap.AutoPeers(a, None, count=3, interval=1)
    assert await auto.run_once() == {}
    assert liar.key.key_text in auto.shunned and not auto.chosen
    assert ap.candidates(a, ap.datetime.now(ap.timezone.utc), set(auto.shunned)) == []
    server.close()


def test_only_reachable_addresses_and_a_bounded_count(tmp_path, monkeypatch):
    from unseenet.cli.node import load_node_config
    p = tmp_path / "node.toml"
    p.write_text("[node]\nauto_peers = 0\n")
    assert load_node_config(p).auto_peers == 0
    p.write_text("[node]\nauto_peers = 99\n")
    with pytest.raises(SystemExit, match="auto_peers"):
        load_node_config(p)
    assert load_node_config(None).auto_peers == 3
