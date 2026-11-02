"""#230: a new node is a node at once - what its own readers post, its announcement
included, goes out to the announced nodes it pulls from; and every node also pulls from
one node that announced itself lately."""

from datetime import datetime, timedelta, timezone

import pytest

from unseenet.core import crypto
from unseenet.core.announcements import Announcement
from unseenet.core.article import new_article
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.node import autopeers as ap
from unseenet.node.server import SPREAD_QUEUE, Node, NodeConfig, PeerConfig
from unseenet.node.spreading import Spreader

from test_announcing import BITS, announce_group, hold  # noqa: F401  (fixture)
from test_autopeers import announced, copy


@pytest.fixture(autouse=True)
def _group(announce_group, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ap, "NODES_ANNOUNCE_GROUP", announce_group.group)


def node(name: str, group, **kw) -> Node:
    n = Node(Store(), NodeConfig(name=name, min_pow=BITS, min_ripe=None, forward_delay=(0, 0),
                                 **kw), key=crypto.Identity.generate())
    hold(n, group)
    return n


@pytest.mark.usefixtures("ripening_rules")
async def test_a_new_node_spreads_its_announcement_and_its_readers_posts(
        tmp_path, announce_group, monkeypatch):  # noqa: F811
    pytest.importorskip("chiavdf")
    monkeypatch.setenv("UNSEENET_TEST_ADDRESSES", "1")
    a, b = node("a", announce_group), node("b", announce_group)
    server = await b.serve("127.0.0.1", 0)
    b_addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    await announced(b, tmp_path, b_addr)
    copy(b, a, only_key=b.key.key_text)                    # a found b's announcement
    await announced(a, tmp_path, "127.0.0.1:9")            # a's own: queued to spread
    assert a.spreads()                                     # no configured peer: "auto" is on
    owner = crypto.Identity.generate()
    group = make_manifest(owner, "dk.test", "open", pow_bits=14)
    a.accept(group.to_bytes())
    post = new_article(group.group, "Hej", "From a new node.\n", from_name="Owner")
    post.finalize(owner, 14)
    a.accept(post.to_bytes())                              # a reader posts to a
    assert len(a.store.due(SPREAD_QUEUE)) >= 3             # announcement, manifest, post
    auto = ap.AutoPeers(a, None, count=3, interval=1)
    taken = await Spreader(a, auto).run_once()
    assert taken >= 3
    assert b.store.seen(post.message_id)                   # the post reached the network
    assert "a" in {x.name for x in ap.held_announcements(b)}   # and b knows of a now
    assert a.store.due(SPREAD_QUEUE) == []
    # nothing is sent twice
    assert await Spreader(a, auto).run_once() == 0
    server.close()


def test_who_spreads():
    n = Node(Store(), NodeConfig(name="n"), key=crypto.Identity.generate())
    assert n.spreads()                                      # a new node: no peers
    n.config.peers = [PeerConfig(name="pull-only", address="x.onion", groups="", pull="*")]
    assert n.spreads()                                      # nobody it pushes to
    n.config.peers = [PeerConfig(name="peer", address="x.onion", groups="*")]
    assert not n.spreads()                                  # it has peers: as before
    n.config.spread = "on"
    assert n.spreads()
    n.config.spread = "off"
    n.config.peers = []
    assert not n.spreads()


def _ann(key: str, days_ago: float, name: str) -> Announcement:
    now = datetime.now(timezone.utc)
    return Announcement(key, "onion:" + "a" * 56 + ".onion", name, {"groups": ["*"]},
                        now - timedelta(days=days_ago), (), None, None, "", ["*"])


def test_newcomers_are_those_first_announced_lately(monkeypatch):
    old, renewed, fresh = "ed25519:" + "a" * 52, "ed25519:" + "b" * 52, "ed25519:" + "c" * 52
    held = [_ann(old, 40, "old"), _ann(old, 20, "old"), _ann(renewed, 30, "renewed"),
            _ann(renewed, 2, "renewed"), _ann(fresh, 1, "fresh")]
    monkeypatch.setattr(ap, "held_announcements", lambda node: held)
    now = datetime.now(timezone.utc)
    assert ap.newcomers(None, now) == {fresh}
    # too little history to tell who is new: nobody is
    monkeypatch.setattr(ap, "held_announcements", lambda node: [_ann(fresh, 1, "fresh")])
    assert ap.newcomers(None, now) == set()


def test_a_place_for_one_newcomer_beside_the_others(monkeypatch):
    keys = [crypto.Identity.generate().key_text for _ in range(5)]
    pool = [(_ann(k, 30, f"n{i}"), f"n{i}.onion") for i, k in enumerate(keys)]
    fresh_key = crypto.Identity.generate().key_text
    pool.append((_ann(fresh_key, 1, "fresh"), "fresh.onion"))
    monkeypatch.setattr(ap, "candidates", lambda node, now, shunned=(): pool)
    monkeypatch.setattr(ap, "newcomers", lambda node, now: {fresh_key})
    n = Node(Store(), NodeConfig(name="n"), key=crypto.Identity.generate())
    auto = ap.AutoPeers(n, None, count=2)
    chosen = auto.choose()
    assert fresh_key in chosen and len(chosen) == 3 and auto.welcome == fresh_key
    assert auto.choose() == chosen                          # kept while it works
    n.config.welcome_new = False
    assert fresh_key not in auto.choose() and len(auto.chosen) == 2
