"""UN-RFC 0040 section 6: pulling reconciles key-bound state before NEWNEWS."""

import time

import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError
from unseenet.core.groups import inbox_article, is_key_bound, make_manifest
from unseenet.core.store import Store
from unseenet.node import pulling
from unseenet.node.pulling import Puller
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8
DAY = 86400


def make_node(name, **kw) -> Node:
    return Node(Store(), NodeConfig(name=name, min_pow=BITS, forward_delay=(0, 0), **kw))


async def serve(node):
    server = await node.serve("127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def as_after_0040(node: Node) -> None:
    """Key-bound groups out of LIST and NEWNEWS part 1, as UN-RFC 0040 sections 3 and 5
    say (step 4 of #217); part 2 unchanged."""
    groups = node.store.groups
    node.store.groups = lambda: [g for g in groups() if not is_key_bound(g[0])]


def inbox_with_old_manifest(a: Node):
    """An inbox whose manifest A received long ago (not in NEWNEWS part 2 for a new
    node) and a message in it A received just now."""
    owner, sender = crypto.Identity.generate(), crypto.Identity.generate()
    m = make_manifest(owner, "inbox", "inbox", pow_bits=BITS)
    a.accept(m.to_bytes())
    a.store.db.execute("UPDATE articles SET received=? WHERE message_id=?",
                       (int(time.time()) - 200 * DAY, m.message_id))
    a.store.db.commit()
    msg = inbox_article(m.group, owner.public_key, from_name="s", subject="hej", body="b",
                        sender=sender, pow_bits=BITS)
    a.accept(msg.to_bytes())
    return m, msg


async def test_new_node_reconciles_before_newnews():
    a = make_node("a")
    as_after_0040(a)
    m, msg = inbox_with_old_manifest(a)
    server, addr = await serve(a)
    try:
        b = make_node("b", peers=[PeerConfig(name="a", address=addr)])
        res = await Puller(b, b.config.peers[0]).run_once()
        assert res["reconciled"]["need"] == 1 and res["reconciled"]["complete"]
        assert b.store.get(msg.message_id) is not None          # its manifest came first
        assert b.store.kb_items() == a.store.kb_items()
        assert not b.store.reconcile_due("a")                    # next time: in about a day

        res = await Puller(b, b.config.peers[0]).run_once()
        assert res["reconciled"] is None                         # not due
        b.reconcile_wanted.add("a")
        res = await Puller(b, b.config.peers[0]).run_once()
        assert res["reconciled"]["need"] == 0 and "a" not in b.reconcile_wanted
    finally:
        server.close()


async def test_what_the_peer_lacks_is_offered():
    a = make_node("a")
    server, addr = await serve(a)
    try:
        b = make_node("b", peers=[PeerConfig(name="a", address=addr)])
        only_b = make_manifest(crypto.Identity.generate(), "inbox", "inbox", pow_bits=BITS)
        b.accept(only_b.to_bytes())
        b.store.db.execute("DELETE FROM peer_queue")            # as if the push was lost
        res = await Puller(b, b.config.peers[0]).run_once()
        assert res["reconciled"]["offered"] == 1
        assert b.store.due("a") == [only_b.message_id]
    finally:
        server.close()


async def test_without_reconcile_the_manifest_is_fetched_by_group(monkeypatch):
    """A peer that cannot reconcile: an article in a key-bound group we hold no
    manifest for makes us fetch the group's manifests from it, then take it."""
    a = make_node("a")
    as_after_0040(a)
    m, msg = inbox_with_old_manifest(a)
    capability = pulling.Client.capability
    monkeypatch.setattr(pulling.Client, "capability",
                        lambda self, name: None if name == "UNSEENET-RECONCILE"
                        else capability(self, name))
    server, addr = await serve(a)
    try:
        b = make_node("b", peers=[PeerConfig(name="a", address=addr)])
        res = await Puller(b, b.config.peers[0]).run_once()
        assert res["reconciled"] is None
        assert b.store.known_group(m.group) and b.store.get(msg.message_id) is not None
        assert not res["rejected"]
    finally:
        server.close()


def test_pushed_article_without_manifest_waits_then_is_refused(monkeypatch):
    a, b = make_node("a"), make_node("b")
    m, msg = inbox_with_old_manifest(a)
    with pytest.raises(ArticleError) as err:
        b.accept(msg.to_bytes(), source="a", from_peer=True)
    assert err.value.reason == "later" and "a" in b.reconcile_wanted
    with pytest.raises(ArticleError) as err:                 # a client: no waiting
        b.accept(msg.to_bytes())
    assert err.value.reason == "group"
    monkeypatch.setattr(Node, "KB_WAIT_SECONDS", -1.0)
    with pytest.raises(ArticleError) as err:
        b.accept(msg.to_bytes(), source="a", from_peer=True)
    assert err.value.reason == "group"
    monkeypatch.setattr(Node, "KB_WAIT_SECONDS", 3600.0)
    b.accept(m.to_bytes(), source="a", from_peer=True)       # the manifest arrives
    b.accept(msg.to_bytes(), source="a", from_peer=True)
    assert b.store.get(msg.message_id) is not None
