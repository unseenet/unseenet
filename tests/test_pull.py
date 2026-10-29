"""Catching up by pull (UN-RFC 0017): history for new nodes, gaps after downtime."""

import time
from datetime import datetime, timedelta, timezone

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
    # ...but the article itself is not refused: a local group is created on a node by
    # posting its manifest there, which must still work after the pull refused it (#132)
    c.accept(local.to_bytes())
    assert c.store.manifest(local.group) is not None
    server_a.close()


async def test_refused_while_its_group_was_unknown_arrives_later():
    """A post pulled before its group's manifest is refused ("group not carried");
    once the manifest is here, the same post must be accepted from another source (#132)."""
    a = make_node("a")
    owner, m_open, posts, *_ = fill(a)
    b = make_node("b", peers=[PeerConfig(name="a", address="unused:1")])
    b.store.refuse(posts[0].message_id, "a", "group")
    assert not b.store.seen(posts[0].message_id)
    b.accept(m_open.to_bytes())
    b.accept(a.store.get(posts[0].message_id))
    assert b.store.get(posts[0].message_id) is not None


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


async def test_a_listing_past_70_kb_still_pulls():
    """29 Oct 2026: every group's state comes first in NEWNEWS, so the listing grows with
    the network; past 70 KB every pull stopped with 'block too large' (0.6.1)."""
    a = make_node("a")
    owners = [crypto.Identity.generate() for _ in range(40)]
    for i in range(2500):                          # 2500 manifests: ~110 KB listed
        a.accept(make_manifest(owners[i % 40], f"dk.g{i}", "open", pow_bits=BITS).to_bytes())
    server_a, addr_a = await serve(a)
    b = make_node("b", peers=[PeerConfig(name="a", address=addr_a)])
    res = await Puller(b, b.config.peers[0]).run_once()
    assert res["listed"] >= 2500, res
    server_a.close()


async def test_the_state_comes_about_once_a_day(monkeypatch):
    """#748, UN-RFC 0017 3-4 as amended: NEWNEWS lists every group's state only for a
    time at least STATE_AGE back; a puller asks that far back at its first pull and then
    about daily, so hourly pulls do not carry the whole network's state each time."""
    from unseenet.nntp import Client
    from unseenet.node.server.peering_commands import STATE_AGE
    a = make_node("a")
    owner, m_open, posts, m_closed, secret = fill(a)
    server_a, addr_a = await serve(a)

    async def listed(since):
        c = await Client.connect(addr_a, None)
        ids = await c.multiline(f"NEWNEWS * {since:%Y%m%d %H%M%S} GMT", 230)
        await c.quit()
        return set(ids)
    now = datetime.now(timezone.utc)
    assert m_open.message_id in await listed(now - timedelta(days=2))     # far back: the state
    assert await listed(now + timedelta(minutes=5)) == set()              # lately: nothing old

    asked = []
    real = Client.multiline

    async def spy(self, line, expect, limit=70000):
        if line.startswith("NEWNEWS"):
            asked.append(datetime.strptime(" ".join(line.split()[2:4]), "%Y%m%d %H%M%S")
                         .replace(tzinfo=timezone.utc))
        return await real(self, line, expect, limit=limit)
    monkeypatch.setattr(Client, "multiline", spy)
    b = make_node("b", peers=[PeerConfig(name="a", address=addr_a)])
    puller = Puller(b, b.config.peers[0])
    assert (await puller.run_once())["accepted"] == 7    # the first pull: all of it
    await puller.run_once()                              # soon after: from the last pull
    b.state_pulled["a"] = 0                              # a day on: a state pull again
    await puller.run_once()
    t = datetime.now(timezone.utc)
    assert t - asked[1] < timedelta(hours=1)
    assert t - asked[2] >= timedelta(seconds=STATE_AGE)
    server_a.close()
