"""What a node carries (UN-RFC 0055, #700, #821): pattern lists, the network's own
groups on every node, and peering by what both carry."""

import pytest

from unseenet import hierarchies as hz
from unseenet.core import carrying as ca
from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.node.peering import Feeder
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8


def make_node(**kw) -> Node:
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), **kw))


def test_pattern_lists():
    assert ca.matches(["*"], "dk.snak")
    pats = ["alt.*", "dk.*", "!dk.politik.*"]
    assert ca.matches(pats, "alt.test") and ca.matches(pats, "dk.snak")
    assert not ca.matches(pats, "dk.politik.valg") and not ca.matches(pats, "palaestina.nyt")
    assert ca.check_patterns("alt.*, dk.*") == ["alt.*", "dk.*"]
    for bad in ([], ["a b"], ["alt.*@x"], ["!"], ["*"] * 65, "x" and [3]):
        with pytest.raises(ca.CarriesProblem):
            ca.check_patterns(bad)
    assert ca.read_carries({}) == ["*"]                       # said nothing: all, as before
    assert ca.read_carries({"carries": {"groups": ["alt.*"]}}) == ["alt.*"]
    assert ca.read_carries({"carries": {"groups": "nonsense list"}}) == []


def test_only_endorsed_ids_are_the_networks_own():
    """Section 4.1: a name in unseenet.* is not enough; the endorsed Group ID is."""
    net = ca.network_groups(["unseenet.help@abcdefghijklmnop", "alt.x@abcdefghijklmnop"])
    assert "unseenet.help@abcdefghijklmnop" in net and "alt.x@abcdefghijklmnop" not in net
    assert ca.INFRASTRUCTURE <= net
    assert not ca.carries("unseenet.help@zzzzzzzzzzzzzzzz", ["alt.*"], net)
    assert ca.carries("unseenet.help@abcdefghijklmnop", ["alt.*"], net)


def test_a_node_carries_its_hierarchies_and_the_networks_own(monkeypatch):
    owner = crypto.Identity.generate()
    alt = make_manifest(owner, "alt.test", "open", pow_bits=BITS)
    dk = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    ours = make_manifest(owner, "unseenet.raad", "open", pow_bits=BITS)
    fake = make_manifest(owner, "unseenet.spam", "open", pow_bits=BITS)
    shipped = hz.builtin_checkgroups()
    monkeypatch.setattr(hz, "builtin_checkgroups", lambda: hz.HierarchyList(
        "unseenet", shipped.updated, {**shipped.groups, "unseenet.raad": ours.group}, {}))
    # excludes may not leave out the network's own groups (section 3.2)
    node = make_node(carries=["alt.*"], excludes="unseenet.*")
    node.accept(alt.to_bytes())
    for refused in (dk, fake):
        with pytest.raises(ArticleError) as e:
            node.accept(refused.to_bytes())
        assert e.value.reason == "group"
    node.accept(ours.to_bytes())                                # endorsed: carried anyway
    node.accept(new_article(ours.group, "Hej", "Rådet\n", from_name="x").finalize(owner, BITS)
                .to_bytes())
    info = node.node_info()
    assert info["carries"] == {"groups": ["alt.*"]}
    assert make_node(sites="accept").node_info()["carries"] == {"groups": ["*"], "sites": True}
    # a local group lives on its node whatever the patterns (section 3.3)
    local = make_manifest(owner, "lokal.snak", "open", local=True, pow_bits=BITS)
    node.accept(local.to_bytes())


async def test_a_peer_gets_only_what_it_carries():
    """Section 6: the feeder learns the peer's list and sends only what both carry."""
    b = make_node(name="b", carries=["alt.*"])
    server_b = await b.serve("127.0.0.1", 0)
    port_b = server_b.sockets[0].getsockname()[1]
    a = make_node(name="a", peers=[PeerConfig(name="b", address=f"127.0.0.1:{port_b}")])
    owner = crypto.Identity.generate()
    for name in ("alt.test", "dk.snak"):
        a.accept(make_manifest(owner, name, "open", pow_bits=BITS).to_bytes())
    await Feeder(a, a.config.peers[0]).run_once()
    assert not a.peer_info_due("b")
    assert a.peer_carries("b", "alt.test@abcdefghijklmnop")
    assert not a.peer_carries("b", "dk.snak@abcdefghijklmnop")
    assert a.store.due("b") == []                               # nothing left in the queue
    assert [g[0].split("@")[0] for g in b.store.groups()] == ["alt.test"]
    server_b.close()
