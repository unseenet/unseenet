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


def test_parse_and_builtin(monkeypatch):
    monkeypatch.setenv("UNSEENET_TEST_ADDRESSES", "1")                 # UN-RFC 0064 2.2
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


@pytest.fixture(autouse=True)
def _history_dates(monkeypatch):
    """These tests build history with old Dates, or move the clock, as nodes see articles
    over time; the rule that a POST is not more than an hour in the past (UN-RFC 0049
    section 3.2) has its own tests in test_origins.py."""
    from datetime import timedelta
    from unseenet.node import server as node_server
    monkeypatch.setattr(node_server, "POST_PAST", timedelta(days=3650))


async def test_the_list_moves_to_a_list_council(tmp_path, monkeypatch):
    """UN-RFC 0020 section 10: the project's node list group says it moved to a list
    council (``moved_to``); clients take the newest list the council's members posted,
    and only lists by members count."""
    from unseenet.core import lists as ls
    from unseenet.core.groups import manifest_article
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    project = crypto.Identity.generate()
    manifest = make_manifest(project, "unseenet.nodes", "channel", pow_bits=8)
    node.accept(manifest.to_bytes())
    monkeypatch.setattr(kn, "PROJECT_KEY", project.key_text)
    monkeypatch.setattr(kn, "NODES_GROUP", manifest.group)
    old = new_article(manifest.group, "Known nodes", node_list(ONION, updated="old"),
                      from_name="Unseenet")
    node.accept(old.finalize(project, 8).to_bytes())

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name)
        s.add_node(addr)
        return s
    r1, r2, me = session("r1"), session("r2"), session("me")
    keys = [r1.identity().key_text, r2.identity().key_text]
    groups = {}
    for part in ("claims", "reports", "nodes"):
        g, b = r1.council_genesis(f"unseenet.lists.{part}", "open" if part == "claims" else "channel",
                                  keys, fields={"min_pow": 0})
        for s in (r1, r2):
            await s.council_sign(g, b)
        groups[part] = g
    gid, body = r1.council_genesis("unseenet.lists", "channel", keys, fields={
        "min_pow": 0, "lists": {"nodes": groups["nodes"]}, "claims": groups["claims"],
        "reports": groups["reports"]})
    for s in (r1, r2):
        await s.council_sign(gid, body)

    # the project key's last manifest points to the council
    data = json.loads(manifest.body)
    data.update({"serial": data["serial"] + 1, "moved_to": gid, "moved_on": "2026-11-02T12:00:00Z"})
    node.accept(manifest_article(project, manifest.group, data, pow_bits=8).to_bytes())
    # until the council has a list, the old one stands
    assert await me.refresh_known_nodes() is True
    assert me.data["known_nodes"]["updated"] == "old"
    council_list = json.dumps({"v": 1, "updated": "council 1 day 2026-11-01", "nodes": [
        {"name": "c", "address": "c" * 56 + ".onion", "node_key": "ed25519:" + "c" * 52}]})
    await r2.post(groups["nodes"], "node list 2026-11-01", council_list)
    assert await me.refresh_known_nodes() is True
    assert [n.address for n in me.known_nodes()] == ["c" * 56 + ".onion"]
    assert ls.updated_day(me.data["known_nodes"]["updated"])[0] == 1
    for s in (r1, r2, me):
        await s.close()
    server.close()


async def test_the_root_list_moves_to_a_list_council(tmp_path, monkeypatch):
    """UN-RFC 0020 section 10 for the root list: once ``unseenet.hierarchies`` says it
    moved to a list council, clients take the council's root list."""
    from unseenet import hierarchies as hz
    from unseenet.client import naming
    from unseenet.core.groups import manifest_article
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    project = crypto.Identity.generate()
    manifest = make_manifest(project, "unseenet.hierarchies", "channel", pow_bits=8)
    node.accept(manifest.to_bytes())
    monkeypatch.setattr(kn, "PROJECT_KEY", project.key_text)
    monkeypatch.setattr(hz, "HIERARCHIES_GROUP", manifest.group)
    old = json.dumps({"v": 1, "updated": "2026-10-31", "hierarchies": [
        {"name": "alt", "policy": "free", "title": "Anything goes"}]})
    node.accept(new_article(manifest.group, "Root list", old, from_name="Unseenet")
                .finalize(project, 8).to_bytes())

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name)
        s.add_node(addr)
        return s
    r1, r2, me = session("r1"), session("r2"), session("me")
    keys = [r1.identity().key_text, r2.identity().key_text]
    groups = {}
    for part in ("claims", "reports", "nodes", "hierarchies"):
        g, b = r1.council_genesis(f"unseenet.lists.{part}", "open" if part == "claims" else "channel",
                                  keys, fields={"min_pow": 0})
        for s in (r1, r2):
            await s.council_sign(g, b)
        groups[part] = g
    gid, body = r1.council_genesis("unseenet.lists", "channel", keys, fields={
        "min_pow": 0, "lists": {"nodes": groups["nodes"], "root": groups["hierarchies"]},
        "claims": groups["claims"], "reports": groups["reports"]})
    for s in (r1, r2):
        await s.council_sign(gid, body)
    data = json.loads(manifest.body)
    data.update({"serial": data["serial"] + 1, "moved_to": gid, "moved_on": "2026-11-02T12:00:00Z"})
    node.accept(manifest_article(project, manifest.group, data, pow_bits=8).to_bytes())
    assert set(await naming.read_root_list(me)) == {"alt"}           # the old one, for now
    new = json.dumps({"v": 1, "updated": "council 1 day 2026-11-01", "hierarchies": [
        {"name": "alt", "policy": "free", "title": "Anything goes"},
        {"name": "games", "policy": "governed", "maintainer": r1.identity().key_text,
         "list": f"games.list@{r1.identity().fingerprint}", "title": "Games"}]})
    await r2.post(groups["hierarchies"], "root list 2026-11-01", new)
    assert set(await naming.read_root_list(me)) == {"alt", "games"}
    await naming.refresh(me)
    assert "games" in naming.root_list(me)
    for s in (r1, r2, me):
        await s.close()
    server.close()
