"""#518: nodes by name - the signed known-node list first, a node's own name marked as
its claim, else the short onion address - and your nodes in the local client API
(UN-RFC 0046 section 4.17)."""

import pytest

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI
from unseenet.client.localapi import server as srv
from unseenet.client.session import Session, SessionError, clean_node_name, short_node
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.known_nodes import KnownNode
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}
ONION = "f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion"
OTHER = "ze4aqpjfyteij4tqaaztyujoj7wsjgbv4cliexljckdfp5eomkshfead.onion"


@pytest.fixture
async def two(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    nodes, servers = [], []
    for name in ("first-node", "unseenet-node1"):          # the second pretends to be listed
        node = Node(Store(), NodeConfig(name=name, min_pow=8, forward_delay=(0, 0)))
        servers.append(await node.serve("127.0.0.1", 0))
        nodes.append(f"127.0.0.1:{servers[-1].sockets[0].getsockname()[1]}")
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(nodes[0])
    yield LocalAPI(session=s), nodes
    await s.close()
    for server in servers:
        server.close()


def test_short_and_clean():
    assert short_node(ONION) == "f6vnchi5….onion"
    assert short_node("127.0.0.1:1190") == "127.0.0.1:1190"
    assert clean_node_name("  my\x00 node\u202e\n") == "my node"
    assert clean_node_name("x" * 100) == "x" * 64
    assert clean_node_name("\x01\x02") is None and clean_node_name(5) is None


def test_names_in_order(tmp_path, monkeypatch):
    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    monkeypatch.setattr(type(s), "known_nodes",
                        lambda self: [KnownNode(name="unseenet-node1", address=ONION,
                                                description="Project test node 1")])
    assert s.node_name(ONION) == ("unseenet-node1", "known")
    assert s.node_label(ONION) == "unseenet-node1"
    s._keep_node_name(ONION, {"name": "evil"})           # the list wins over the node
    assert s.node_label(ONION) == "unseenet-node1"
    assert s.node_name(OTHER) == (None, "none") and s.node_label(OTHER) == "ze4aqpjf….onion"
    s._keep_node_name(OTHER, {"name": "unseenet-node1"})    # anyone can say so
    assert s.node_name(OTHER) == ("unseenet-node1", "self")
    assert s.node_label(OTHER) == "unseenet-node1 (unlisted)"
    s.add_node(ONION)
    s.add_node(OTHER)
    e = s.node_entries()
    assert [x["address"] for x in e] == [ONION, OTHER] and e[0]["default"]
    assert e[0]["description"] == "Project test node 1" and e[1]["source"] == "self"
    s.remove_node(OTHER)
    assert OTHER not in s.data["node_names"]


async def test_nodes_in_the_api(two):
    api, (first, second) = two
    async def nothing(client):
        return None
    await api.session._call(nothing, first)                # connecting learns its own name
    assert api.status == "Connected to first-node (unlisted)" and api.status_idle   # any node
    api.session.say("Starting Tor ...")
    assert not api.status_idle
    st = api.state()
    assert st["node"] == first and st["node_label"] == "first-node (unlisted)"
    assert st["node_names"][first] == {"name": "first-node", "source": "self",
                                       "label": "first-node (unlisted)"}
    got = await api.change_nodes({"action": "add", "address": second})
    assert [n["address"] for n in got["nodes"]] == [first, second]
    got = await api.nodes(info=True)
    by = {n["address"]: n for n in got["nodes"]}
    assert by[second]["reachable"] and by[second]["info"]["name"] == "unseenet-node1"
    assert by[second]["label"] == "unseenet-node1 (unlisted)"       # not the listed one
    assert all(k["address"] not in by for k in got["known"])
    got = await api.change_nodes({"action": "default", "address": second})
    assert got["nodes"][0]["address"] == second and got["nodes"][0]["default"]
    got = await api.change_nodes({"action": "remove", "address": first})
    assert [n["address"] for n in got["nodes"]] == [second] and got["moved"] == []
    with pytest.raises(SessionError, match="at least one"):
        await api.change_nodes({"action": "remove", "address": second})
    for data, match in [({"action": "add", "address": "nope.onion"}, "onion address"),
                        ({"action": "add", "address": "host"}, "host:port"),
                        ({"action": "add", "address": "h:99999"}, "port"),
                        ({"action": "jump", "address": second}, "action"),
                        ({"action": "add"}, "address"),
                        ({"action": "remove", "address": first}, "not one of")]:
        with pytest.raises(SessionError, match=match):
            await api.change_nodes(data)
    routes = {(m, p) for m, p, _ in srv.ROUTES}
    assert {("GET", "/api/nodes"), ("POST", "/api/nodes")} <= routes
