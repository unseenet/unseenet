"""When nodes are gone (#603, #604, #605): carry on with a node that answers - from your
own nodes, else from the known-node list - and never move a group to a node that does
not carry it."""

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.known_nodes import KnownNode
from unseenet.nntp import Client
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}
DEAD = "127.0.0.1:9"                       # nothing listens there


async def start_node():
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def session(tmp_path, name, *nodes):
    s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity(name, name.title())
    for n in nodes:
        s.add_node(n)
    return s


async def test_posting_goes_through_another_node(tmp_path, monkeypatch):
    """#604: the group's node cannot be reached - the post goes out through another node
    of yours that carries the group, and the group is read from there."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    srv, n2 = await start_node()
    bob = session(tmp_path, "bob", n2)
    gid = await bob.create_group("dk.b", "open", min_pow=8)
    me = session(tmp_path, "me", DEAD, n2)
    try:
        me.subscribe(gid, node=DEAD)
        assert me.node_for(gid) == DEAD
        await me.post(gid, "hej", "Kom igennem\n")
        assert me.node_for(gid) == n2
        bodies = [m.body for m in await bob.fetch_group(gid)]
        assert "Kom igennem\n" in bodies
    finally:
        for s in (bob, me):
            await s.close()
        srv.close()


async def test_a_lost_answer_is_not_a_second_post(tmp_path, monkeypatch):
    """#604: the line broke after the article went out - sent again, the node says
    duplicate, and that is a success."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    srv, n1 = await start_node()
    me = session(tmp_path, "me", n1)
    try:
        gid = await me.create_group("dk.mine", "open", min_pow=8)
        real = Client.post
        broke = []

        async def post_then_break(self, raw):
            answer = await real(self, raw)
            if not broke:
                broke.append(answer)
                raise ConnectionError("line broke")
            return answer
        monkeypatch.setattr(Client, "post", post_then_break)
        mid = await me.post(gid, "en gang", "Kun én\n")
        assert broke and broke[0][0] == 240
        monkeypatch.setattr(Client, "post", real)
        posts = [m for m in await me.fetch_group(gid) if m.body == "Kun én\n"]
        assert len(posts) == 1 and posts[0].message_id == mid
    finally:
        await me.close()
        srv.close()


async def test_new_group_and_inbox_on_the_next_node(tmp_path, monkeypatch):
    """#605: the default is gone - a new group and your inbox go to the next node that
    answers, and you are told."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    srv, n2 = await start_node()
    said = []
    me = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda t, **_: said.append(t))
    me.new_identity("me", "Me")
    me.add_node(DEAD)
    me.add_node(n2)
    try:
        assert me.node == DEAD
        gid = await me.create_group("dk.ny", "open", min_pow=8)
        assert me.node_for(gid) == n2
        assert any("made on" in t for t in said)
        inbox = await me.ensure_inbox()
        assert me.node_for(inbox) == n2
        assert await me._call(lambda c: c.group(inbox), n2)      # inboxes are not listed
    finally:
        await me.close()
        srv.close()


async def test_fall_back_to_a_listed_node(tmp_path, monkeypatch):
    """#603: none of your nodes answers - a node from the known-node list becomes your
    default; groups it carries are read there, a group it does not carry stays with
    its own node, and your inbox goes along."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    srv, n2 = await start_node()
    bob = session(tmp_path, "bob", n2)
    carried = await bob.create_group("dk.b", "open", min_pow=8)
    me = session(tmp_path, "me", DEAD)
    monkeypatch.setattr(Session, "known_nodes",
                        lambda self: [KnownNode("unseenet-test", n2)])
    events = []
    real_emit = me.emit
    me.emit = lambda e: (events.append(e), real_emit(e))
    try:
        me.subscribe(carried, node=DEAD)
        only_dead = "alt.lokal@" + carried.split("@", 1)[1]    # carried by DEAD alone
        me.subscribe(only_dead, node=DEAD)
        me.group_entry(me.my_inbox)["node"] = DEAD
        assert await me.fall_back_to_known_node() == n2
        assert me.node == n2 and DEAD in me.nodes               # kept: it may come back
        assert me.node_for(carried) == n2
        assert me.data["groups"][only_dead]["node"] == DEAD     # never moved away
        assert me.node_for(me.my_inbox) == n2
        assert any(getattr(e, "name", "") == "default-node-changed" for e in events)
        await me.ensure_inbox()                                 # made there
        assert await me._call(lambda c: c.group(me.my_inbox), n2)
    finally:
        for s in (bob, me):
            await s.close()
        srv.close()


async def test_no_listed_node_answers(tmp_path, monkeypatch):
    me = session(tmp_path, "me", DEAD)
    monkeypatch.setattr(Session, "known_nodes",
                        lambda self: [KnownNode("gone", "127.0.0.1:7")])
    try:
        assert await me.fall_back_to_known_node() is None
        assert me.nodes == [DEAD]
    finally:
        await me.close()


async def test_default_moves_when_it_has_been_gone(tmp_path, monkeypatch):
    """#605: the default has failed for a while and another of your nodes answers."""
    srv, n2 = await start_node()
    me = session(tmp_path, "me", DEAD, n2)
    try:
        await me.list_groups()
        assert DEAD in me.unreachable and me.down_for(DEAD) > 0
        assert await me.promote_default(give_up=3600) is None   # not long enough yet
        assert await me.promote_default(give_up=0) == n2
        assert me.node == n2
    finally:
        await me.close()
        srv.close()


async def test_removing_a_node_moves_only_what_is_carried(tmp_path, monkeypatch):
    """#603: a removed node's groups go to a node of yours that carries them; the rest
    are said to be unavailable, not moved blindly to the default."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    (s1, n1), (s2, n2) = await start_node(), await start_node()
    alice, bob = session(tmp_path, "alice", n1), session(tmp_path, "bob", n2)
    on_1 = await alice.create_group("dk.a", "open", min_pow=8)
    only_2 = await bob.create_group("dk.b", "open", min_pow=8)
    me = session(tmp_path, "me", n1, n2)
    try:
        me.subscribe(on_1, node=n2)              # read from n2 by mistake: n1 carries it
        me.subscribe(only_2, node=n2)
        moved = me.remove_node(n2)
        assert set(moved) == {on_1, only_2}
        out = await me.rehome_groups(moved)
        assert out["moved"].get(on_1) == n1
        assert only_2 in out["unavailable"]
    finally:
        for s in (alice, bob, me):
            await s.close()
        s1.close()
        s2.close()
