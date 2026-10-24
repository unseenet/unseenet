"""#384: a new group's posts no longer wait an hour when they reach a peer before its
manifest - the manifest goes first, and a post that still beats it is asked again."""
import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8


def _node(name, peers=(), delay=(0, 0)):
    return Node(Store(), NodeConfig(name=name, min_pow=BITS, forward_delay=delay,
                                    peers=[PeerConfig(name=p, address="x.onion") for p in peers]))


def _group():
    owner = crypto.Identity.generate()
    m = make_manifest(owner, "dk.ny", "open", pow_bits=BITS)
    post = new_article(m.group, "Hej", "Første indlæg\n", from_name="Ejer").finalize(owner, BITS)
    return m, post


def test_a_post_before_its_manifest_is_asked_again():
    b = _node("b", peers=["a"])
    m, post = _group()
    with pytest.raises(ArticleError) as err:
        b.accept(post.to_bytes(), source="a", from_peer=True)
    assert err.value.reason == "later" and "a" in b.reconcile_wanted       # 431, not refused
    with pytest.raises(ArticleError) as err:                              # a client: no waiting
        b.accept(post.to_bytes())
    assert err.value.reason == "group"
    b.accept(m.to_bytes(), source="a", from_peer=True)                    # the manifest arrives
    b.accept(post.to_bytes(), source="a", from_peer=True)
    assert b.store.get(post.message_id) is not None


def test_after_a_while_a_group_that_never_comes_is_refused(monkeypatch):
    b = _node("b", peers=["a"])
    _, post = _group()
    monkeypatch.setattr(Node, "GROUP_WAIT_SECONDS", -1.0)
    with pytest.raises(ArticleError) as err:
        b.accept(post.to_bytes(), source="a", from_peer=True)
    assert err.value.reason == "group"


def test_the_manifest_goes_to_peers_without_the_random_delay():
    a = _node("a", peers=["b"], delay=(600, 600))
    m, post = _group()
    a.accept(m.to_bytes())
    a.accept(post.to_bytes())
    assert a.store.due("b") == [m.message_id]          # the post waits its 10 minutes
