"""Catching up by pull (UN-RFC 0017): history for new nodes, gaps after downtime."""

import time

from unseenet.core import crypto
from unseenet.core.article import new_article
from unseenet.core.groups import encrypted_article, make_key_update, make_manifest
from unseenet.core.store import Store
from unseenet.node.pulling import Puller
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8
DAY = 86400


def make_node(name, **kw) -> Node:
    return Node(Store(), NodeConfig(name=name, min_pow=BITS, forward_delay=(0, 0), **kw))


async def serve(node):
    server = await node.serve("127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def post(node, owner, gid, text):
    art = new_article(gid, text, text + "\n", from_name="A").finalize(owner, BITS)
    node.accept(art.to_bytes())
    return art


def fill(a: Node):
    """An open group and a closed group with history on node A."""
    owner = crypto.Identity.generate()
    m_open = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    a.accept(m_open.to_bytes())
    posts = [post(a, owner, m_open.group, f"indlæg {i}") for i in range(3)]
    m_closed = make_manifest(owner, "familie", "closed", pow_bits=BITS)
    a.accept(m_closed.to_bytes())
    keys = crypto.GroupKeys.generate()
    a.accept(make_key_update(owner, m_closed.group, 1, keys, [], pow_bits=BITS).to_bytes())
    secret = encrypted_article(m_closed.group, 1, keys, owner, from_name="A", subject="hemmeligt",
                               body="kun for familien\n", pow_bits=BITS)
    a.accept(secret.to_bytes())
    return owner, m_open, posts, m_closed, secret


async def test_new_node_gets_the_history():
    a = make_node("a")
    owner, m_open, posts, m_closed, secret = fill(a)
    server_a, addr_a = await serve(a)
    b = make_node("b", peers=[PeerConfig(name="a", address=addr_a)])   # no key: just reads
    res = await Puller(b, b.config.peers[0]).run_once()
    assert res["accepted"] == 7, res                 # 2 manifests, 3 posts, key update, secret
    for art in posts + [secret]:
        assert b.store.get(art.message_id) == a.store.get(art.message_id)   # no Path/Xref added
    assert b.store.epochs(m_closed.group)                                   # can check members

    # the next pull asks only for what is new
    newer = post(a, owner, m_open.group, "ny")
    res = await Puller(b, b.config.peers[0]).run_once()
    assert res["fetched"] == 1 and res["accepted"] == 1
    assert b.store.get(newer.message_id)
    server_a.close()


async def test_group_state_comes_first_whatever_its_age():
    """B pulled long ago, before the group existed; the manifest arrived at A
    outside the window B asks for, but is listed anyway."""
    a = make_node("a")
    owner, m_open, *_ = fill(a)
    a.store.db.execute("UPDATE articles SET received = received - ?", (30 * DAY,))
    a.store.db.commit()
    newer = post(a, owner, m_open.group, "efter pausen")
    server_a, addr_a = await serve(a)
    b = make_node("b", peers=[PeerConfig(name="a", address=addr_a)])
    b.store.set_pulled("a", int(time.time()) - 3600)
    res = await Puller(b, b.config.peers[0]).run_once()
    assert b.store.get(newer.message_id), res
    assert b.store.manifest(m_open.group) is not None
    server_a.close()


async def test_key_updates_do_not_expire():
    a = make_node("a")
    owner, m_open, posts, m_closed, secret = fill(a)
    a.store.db.execute("UPDATE articles SET date = date - ?", (200 * DAY,))
    a.store.db.commit()
    a.store.expire(90)
    assert a.store.get(posts[0].message_id) is None          # ordinary posts expire
    assert a.store.state_ids(m_closed.group)[0] == a.store.manifest(m_closed.group).message_id
    assert len(a.store.state_ids(m_closed.group)) == 2        # manifest + key update kept


async def test_only_chosen_groups_and_never_local_ones():
    a = make_node("a")
    owner, m_open, posts, m_closed, secret = fill(a)
    local = make_manifest(owner, "lokalt", "open", local=True, pow_bits=BITS)
    a.accept(local.to_bytes())
    server_a, addr_a = await serve(a)
    b = make_node("b", peers=[PeerConfig(name="a", address=addr_a, pull="dk.*")])
    await Puller(b, b.config.peers[0]).run_once()
    assert b.store.manifest(m_open.group) is not None
    assert b.store.manifest(m_closed.group) is None           # not asked for
    c = make_node("c", peers=[PeerConfig(name="a", address=addr_a)])
    res = await Puller(c, c.config.peers[0]).run_once()
    assert c.store.manifest(local.group) is None and res["rejected"]["group"] == 1
    # a rejected article is not fetched again
    res = await Puller(c, c.config.peers[0]).run_once()
    assert res["fetched"] == 0
    server_a.close()


async def test_pulled_posts_are_passed_on_but_not_back():
    a = make_node("a")
    fill(a)
    server_a, addr_a = await serve(a)
    b = make_node("b", peers=[PeerConfig(name="a", address=addr_a),
                              PeerConfig(name="c", address="unused:1", pull="")])
    await Puller(b, b.config.peers[0]).run_once()
    assert len(b.store.due("c", 100)) == 7       # queued for B's other peer
    assert b.store.due("a", 100) == []           # not pushed back where it came from
    server_a.close()


async def test_peer_with_key_is_checked():
    a_key = crypto.Identity.generate()
    a = Node(Store(), NodeConfig(name="a", min_pow=BITS), key=a_key)
    fill(a)
    server_a, addr_a = await serve(a)
    impostor = make_node("b", peers=[PeerConfig(name="a", address=addr_a,
                                                key=crypto.Identity.generate().key_text)])
    try:
        await Puller(impostor, impostor.config.peers[0]).run_once()
        raise AssertionError("pulled from a node with the wrong key")
    except Exception as exc:  # noqa: BLE001
        assert "answered with key" in str(exc)
    # the right key, though A does not list B: it reads like any client
    b = make_node("b", peers=[PeerConfig(name="a", address=addr_a, key=a_key.key_text)])
    res = await Puller(b, b.config.peers[0]).run_once()
    assert res["accepted"] == 7
    server_a.close()


def test_old_stores_learn_their_key_updates(tmp_path):
    """Stores from before UN-RFC 0017 find the key updates among their articles."""
    a = Node(Store(tmp_path / "a.sqlite"), NodeConfig(name="a", min_pow=BITS))
    owner, m_open, posts, m_closed, secret = fill(a)
    a.store.db.execute("DELETE FROM epoch_articles")
    a.store.db.commit()
    again = Store(tmp_path / "a.sqlite")
    assert len(again.state_ids(m_closed.group)) == 2
