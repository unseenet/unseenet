"""The signed list of known nodes (UN-RFC 0010)."""

import json

import pytest

import unseenet.client.session as sess
import unseenet.known_nodes as kn
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.article import new_article
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}
ONION = "a" * 56 + ".onion"


def node_list(*addresses, updated="2026-10-16"):
    return json.dumps({"v": 1, "updated": updated, "nodes": [
        {"name": f"n{i}", "address": a, "description": "test"} for i, a in enumerate(addresses)]})


def test_parse_and_builtin():
    updated, nodes = kn.parse_node_list(node_list(ONION, "host.example:1119", "not a node!"))
    assert [n.address for n in nodes] == [ONION, "host.example:1119"]     # bad entry skipped
    with pytest.raises(ValueError):
        kn.parse_node_list(json.dumps({"v": 2, "nodes": []}))
    assert kn.KNOWN_NODES and all(n.address.endswith(".onion") for n in kn.KNOWN_NODES)


async def test_client_reads_the_newest_signed_list(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    project, robot, stranger = (crypto.Identity.generate() for _ in range(3))
    manifest = make_manifest(project, "unseenet.nodes", "channel", posters=[robot.key_text], pow_bits=8)
    node.accept(manifest.to_bytes())
    monkeypatch.setattr(kn, "PROJECT_KEY", project.key_text)
    monkeypatch.setattr(kn, "NODES_GROUP", manifest.group)

    def post(author, body, date=None):
        art = new_article(manifest.group, "Known nodes", body, from_name="Unseenet")
        if date:
            art.set("Date", date)
        node.accept(art.finalize(author, 8).to_bytes())

    post(robot, node_list(ONION, updated="old"), "Wed, 14 Oct 2026 10:00:00 +0000")
    post(project, node_list(ONION, "b" * 56 + ".onion", updated="new"), "Thu, 15 Oct 2026 10:00:00 +0000")
    with pytest.raises(Exception):
        post(stranger, node_list("evil" * 14 + ".onion"))       # the node refuses it

    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(addr)
    assert [n.address for n in s.known_nodes()] == [n.address for n in kn.KNOWN_NODES]
    assert await s.refresh_known_nodes() is True
    assert [n.address for n in s.known_nodes()] == [ONION, "b" * 56 + ".onion"]
    assert s.data["known_nodes"]["updated"] == "new"
    assert manifest.group not in s.data["subscribed"] and manifest.group not in s.cache
    assert await s.refresh_known_nodes() is False          # nothing new

    # a group with the same name but another owner is ignored
    monkeypatch.setattr(kn, "PROJECT_KEY", stranger.key_text)
    s.data.pop("known_nodes")
    assert await s.refresh_known_nodes() is False
    await s.close()
    server.close()
