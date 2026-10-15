"""One client, several nodes: same identity everywhere, each group read from its node."""

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


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


async def test_groups_from_two_nodes(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    (srv1, n1), (srv2, n2) = await start_node(), await start_node()
    alice = session(tmp_path, "alice", n1)
    bob = session(tmp_path, "bob", n2)
    ga = await alice.create_group("dk.a", "open")
    gb = await bob.create_group("dk.b", "open")
    await alice.post(ga, "på 1", "Hej fra node 1\n")
    await bob.post(gb, "på 2", "Hej fra node 2\n")

    me = session(tmp_path, "me", n1, n2)
    groups = {g.group_id: g for g in await me.list_groups()}
    assert groups[ga].nodes == [n1] and groups[gb].nodes == [n2]
    me.subscribe(ga, node=n1)
    me.subscribe(gb, node=n2)
    assert [m.body for m in await me.fetch_group(ga)] == ["Hej fra node 1\n"]
    assert [m.body for m in await me.fetch_group(gb)] == ["Hej fra node 2\n"]

    # posting goes to the group's own node, with the same key on both
    await me.post(gb, "svar", "Samme nøgle\n")
    got = await bob.fetch_group(gb)
    assert got[-1].body == "Samme nøgle\n"
    assert got[-1].author_key == me.identity().key_text

    # new groups go to the default node, or to the one you choose
    mine = await me.create_group("dk.mine", "open", node=n2)
    assert me.node_for(mine) == n2
    assert mine in {g.group_id for g in await bob.list_groups()}

    # the offline cache keeps each group with its node
    me.save_offline()
    again = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    assert again.load_offline() == 2
    assert [m.body for m in again.cache[ga].values()] == ["Hej fra node 1\n"]
    assert [m.body for m in again.cache[gb].values()] == ["Hej fra node 2\n"]

    # dropping a node moves its groups to the default node
    moved = me.remove_node(n2)
    assert gb in moved and me.node_for(gb) == n1
    for s in (alice, bob, me, again):
        await s.close()
    srv1.close()
    srv2.close()


async def test_group_found_on_another_node(tmp_path, monkeypatch):
    """A group that its node does not carry is read from another of your nodes."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    (srv1, n1), (srv2, n2) = await start_node(), await start_node()
    bob = session(tmp_path, "bob", n2)
    gb = await bob.create_group("dk.b", "open")
    await bob.post(gb, "hej", "Kun på node 2\n")

    me = session(tmp_path, "me", n1, n2)
    me.subscribe(gb)                           # not told where: assumed on the default node
    assert me.node_for(gb) == n1
    assert [m.body for m in await me.fetch_group(gb)] == ["Kun på node 2\n"]
    assert me.node_for(gb) == n2

    # and a private message to an inbox on the other node finds its way
    await bob.ensure_inbox()
    await me.send_private(bob.my_inbox, "hej", "Privat\n", owner_key=bob.identity().public_key)
    got = await bob.fetch_group(bob.my_inbox)
    assert [m.body for m in got if m.readable] == ["Privat\n"]
    for s in (bob, me):
        await s.close()
    srv1.close()
    srv2.close()


async def test_unreachable_node_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    srv1, n1 = await start_node()
    me = session(tmp_path, "me", n1, "127.0.0.1:1")      # nothing listens there
    g = await me.create_group("dk.x", "open")
    assert g in {x.group_id for x in await me.list_groups()}
    assert me.unreachable == ["127.0.0.1:1"]
    await me.close()
    srv1.close()
