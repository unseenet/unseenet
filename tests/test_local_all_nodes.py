"""#134: a local group read on all your nodes - an operator's contact inbox on each of
their nodes, in one place: posts from every node that carries it, each once, with the
node it came from; read marks hold; the offline cache keeps them all."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}
BITS = 8


@pytest.fixture
async def three(tmp_path, monkeypatch):
    """Three nodes; the operator's local contact inbox on the first two."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    op = Session(Vault.open(tmp_path / "op.vault", "pw", **KDF), status=lambda *_: None)
    op.new_identity("op", "Operator")
    contact = make_manifest(op.identity(), "operator", "inbox", local=True, pow_bits=10)
    nodes, servers, addrs = [], [], []
    for i in range(3):
        n = Node(Store(), NodeConfig(name=f"node{i + 1}", min_pow=BITS, forward_delay=(0, 0)))
        if i < 2:
            n.accept(contact.to_bytes())
        srv = await n.serve("127.0.0.1", 0)
        nodes.append(n), servers.append(srv)
        addrs.append(f"127.0.0.1:{srv.sockets[0].getsockname()[1]}")
    for a in addrs:
        op.add_node(a)
    made = [op]

    def person(name, addr):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title())
        p.add_node(addr)
        made.append(p)
        return p
    yield op, contact.group, addrs, person, tmp_path
    for p in made:
        await p.close()
    for s in servers:
        s.close()


async def test_the_contact_inbox_of_every_node_in_one_place(three):
    op, gid, addrs, person, tmp_path = three
    a, b = person("a", addrs[0]), person("b", addrs[1])
    await a.send_private(gid, "Spam i alt.snak", "se her\n", owner_key=op.identity().public_key)
    await b.send_private(gid, "Hjælp", "min node\n", owner_key=op.identity().public_key)
    op.subscribe(gid)
    msgs = await op.fetch_group(gid)
    got = {m.subject: m.node for m in op.visible(msgs)}
    assert got == {"Spam i alt.snak": addrs[0], "Hjælp": addrs[1]}       # both, from where they are
    assert all(m.readable for m in msgs)
    assert op.read_from(gid) == [addrs[0], addrs[1]]                     # node3 does not carry it
    info = op.group_info(gid)
    assert info.local and info.read_from == [addrs[0], addrs[1]]
    assert {m.to_dict()["node"] for m in msgs} == {addrs[0], addrs[1]}

    # read marks hold, and fetching again brings only what is new, once
    for m in msgs:
        op.mark_read(m)
    await b.send_private(gid, "Igen", "endnu en\n", owner_key=op.identity().public_key)
    msgs = op.visible(await op.fetch_group(gid))
    assert sorted(m.subject for m in msgs) == ["Hjælp", "Igen", "Spam i alt.snak"]
    assert op.unread_count(gid) == 1

    # the offline cache keeps the other node's posts, and where they came from
    op.save_offline()
    op.cache.clear()
    op._raw.clear()
    op.load_offline()
    assert {m.subject: m.node for m in op.cache[gid].values()} == {
        "Spam i alt.snak": addrs[0], "Hjælp": addrs[1], "Igen": addrs[1]}


async def test_ordinary_groups_are_read_from_one_node(three):
    op, _, addrs, person, _ = three
    owner = person("owner", addrs[0])
    gid = await owner.create_group("alt.snak", "open", min_pow=10)
    await owner.post(gid, "Hej", "x\n")
    op.subscribe(gid)
    msgs = await op.fetch_group(gid)
    assert [m.node for m in msgs] == [op.node_for(gid)]
    assert op.read_from(gid) == [op.node_for(gid)] and op.group_info(gid).read_from == []


def test_numbers_from_other_nodes_never_meet():
    a, b = Session._node_offset("x.onion:119"), Session._node_offset("y.onion:119")
    assert a >= Session.NODE_OFFSET and b >= Session.NODE_OFFSET
    assert a % Session.NODE_OFFSET == 0 and a != b
    assert crypto  # noqa: B018  (imported for the fixture's keys)
