"""#840 (UN-RFC 0054 section 17, withholding): a group read through several nodes - what
any of them holds is read, each article once, and the nodes that lack what another holds
are named. Replicas read the council's groups this way."""

import time

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.known_nodes import KnownNode, builtin_list, parse_node_list
from unseenet.node.server import Node, NodeConfig
from unseenet.replica.cli import explain

KDF = {"ops": 1, "mem": 8192 * 1024}
BITS = 8
LATER = 2 * Session.WIDE_GRACE


@pytest.fixture
async def three(tmp_path, monkeypatch):
    """Three nodes that do not peer, each carrying one open group: what is posted to one
    stays there, as if the others hid it."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    owner = Session(Vault.open(tmp_path / "owner.vault", "pw", **KDF), status=lambda *_: None)
    owner.new_identity("owner", "Owner")
    m = make_manifest(owner.identity(), "alt.raad", "open", pow_bits=10)
    nodes, servers, addrs = [], [], []
    for i in range(3):
        n = Node(Store(), NodeConfig(name=f"node{i + 1}", min_pow=BITS, forward_delay=(0, 0)))
        n.accept(m.to_bytes())
        srv = await n.serve("127.0.0.1", 0)
        nodes.append(n), servers.append(srv)
        addrs.append(f"127.0.0.1:{srv.sockets[0].getsockname()[1]}")
    made = [owner]

    def person(name, *on):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title())
        for a in on:
            p.add_node(a)
        made.append(p)
        return p

    async def post(name, addr, subject):
        p = person(name, addr)
        p.subscribe(m.group)
        await p.fetch_group(m.group)
        await p.post(m.group, subject, "x\n")
        return p
    yield m.group, nodes, addrs, person, post
    for p in made:
        await p.close()
    for s in servers:
        s.close()


async def test_read_through_two_nodes_takes_what_both_hold(three):
    gid, _, addrs, person, post = three
    await post("a", addrs[0], "På node 1")
    await post("b", addrs[1], "På node 2")
    one = person("one", *addrs)
    one.subscribe(gid)
    assert [m.subject for m in one.visible(await one.fetch_group(gid))] == ["På node 1"]

    r = person("r", *addrs)
    r.read_wide(gid, 2)
    r.subscribe(gid)
    msgs = r.visible(await r.fetch_group(gid))
    assert sorted(m.subject for m in msgs) == ["På node 1", "På node 2"]
    assert {m.subject: m.node for m in msgs} == {"På node 1": addrs[0], "På node 2": addrs[1]}
    assert r.read_wide_from(gid) == sorted(addrs[:2])      # two nodes, not the third
    assert r.withheld(gid) == {}                           # may still be on its way
    assert r.withheld(gid, now=time.time() + LATER) == {addrs[0]: 1, addrs[1]: 1}

    # fetching again reads only what is new, each article once
    await post("c", addrs[1], "Igen")
    msgs = r.visible(await r.fetch_group(gid))
    assert sorted(m.subject for m in msgs) == ["Igen", "På node 1", "På node 2"]
    assert r.withheld(gid, now=time.time() + LATER) == {addrs[0]: 2, addrs[1]: 1}


async def test_an_article_that_reaches_the_first_node_late_is_kept_once(three):
    gid, nodes, addrs, person, post = three
    await post("b", addrs[1], "Sent")
    r = person("r", *addrs)
    r.read_wide(gid, 2)
    r.subscribe(gid)
    msgs = r.visible(await r.fetch_group(gid))
    assert [m.node for m in msgs] == [addrs[1]]
    raw = next(iter(r._raw[gid].values()))
    nodes[0].accept(raw)                                   # now node 1 has it too
    msgs = r.visible(await r.fetch_group(gid))
    assert [m.subject for m in msgs] == ["Sent"]
    assert r.withheld(gid, now=time.time() + LATER) == {}


async def test_nodes_elsewhere_are_read_first(three, monkeypatch):
    _, _, addrs, person, _ = three
    r = person("r", *addrs)
    known = [KnownNode("n1", addrs[0], hosting="Denmark"),
             KnownNode("n2", addrs[1], hosting="Denmark"),
             KnownNode("n3", addrs[2], hosting="Oracle Cloud")]
    monkeypatch.setattr(r, "known_nodes", lambda: known)
    assert r.wide_order("x@y") == [addrs[0], addrs[2], addrs[1]]
    known[2] = KnownNode("n3", addrs[2], hosting="Denmark")
    assert r.wide_order("x@y") == addrs                    # all alike: in your order


async def test_council_copies_are_the_union_of_the_nodes(three, monkeypatch):
    _, _, addrs, person, _ = three
    r = person("r", *addrs)
    held = {addrs[0]: [(b"a", "one")], addrs[1]: [(b"a", "one"), (b"b", "two")],
            addrs[2]: [(b"c", "three")]}

    async def call(run, address):
        return held[address]
    monkeypatch.setattr(r, "_call", call)
    assert await r.council_copies("c@x") == [(b"a", "one")]       # one node, as before
    r.read_wide("c@x", 2)
    assert await r.council_copies("c@x") == [(b"a", "one"), (b"b", "two")]
    assert await r.council_copies("c@x", node=addrs[2]) == [(b"c", "three")]


def test_the_node_list_says_where_a_node_runs():
    _, nodes = parse_node_list('{"v": 1, "nodes": [{"address": "%s.onion", "hosting": "%s"}]}'
                               % ("a" * 56, "x" * 60))
    assert nodes[0].hosting == "x" * 40
    hosting = {n.name: n.hosting for n in builtin_list()[1]}
    assert hosting["unseenet-node1"] != hosting["unseenet-node3"]


def test_status_names_nodes_that_disagree():
    st = {"role": "full member", "group": "g", "key": "k", "time": "2026-11-02T20:00:00Z",
          "read_through": {"registrar": ["n1", "n2"], "claims": ["n1", "n2"]},
          "withheld": {"claims": {"n2": 3}}}
    text = "\n".join(explain(st, {}))
    assert "NODES DISAGREE about the claims group: n2 lacks 3" in text
    assert "one node only" not in text
    st = {**st, "read_through": {"registrar": ["n1"]}, "withheld": {}}
    assert "reads the council's groups through one node only" in "\n".join(explain(st, {}))
