"""Nodes announce themselves (UN-RFC 0055 section 5, #700): the node ripens its own
key, posts where it is and what it carries, and keeps only the newest per node."""

from datetime import datetime, timedelta, timezone

import pytest

from unseenet import known_nodes
from unseenet.core import announcements as an
from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import Manifest, make_manifest
from unseenet.core.store import Store
from unseenet.node import announcing
from unseenet.node.server import Node, NodeConfig

BITS = 8
T0 = (datetime.now(timezone.utc) - timedelta(days=3)).replace(minute=0, second=0, microsecond=0)


def test_an_announcement_and_when_to_make_one():
    body = an.make_body("onion:" + "a" * 56 + ".onion", "Kvisten", {"groups": ["alt.*"]}, T0)
    a = an.parse(body, key="ed25519:k", date=T0)
    assert a.name == "Kvisten" and a.patterns == ["alt.*"] and not a.stale(T0 + timedelta(days=44))
    assert a.stale(T0 + timedelta(days=46))
    with pytest.raises(an.AnnouncementProblem):
        an.parse(body, key="ed25519:k", date=T0 + timedelta(hours=1))      # not its Date
    with pytest.raises(an.AnnouncementProblem):
        an.parse(body.replace('"alt.*"', '"a b"'), key="ed25519:k", date=T0)
    f1 = an.fingerprint("a", "n", {"groups": ["*"]})
    f2 = an.fingerprint("a", "n", {"groups": ["alt.*"]})
    assert an.due(None, None, f1, T0)
    assert not an.due(T0, f1, f1, T0 + timedelta(days=5))
    assert an.due(T0, f1, f2, T0 + timedelta(days=1))                  # it changed
    assert not an.due(T0, f1, f2, T0 + timedelta(hours=2))             # but once a day at most
    assert an.due(T0, f1, f1, T0 + an.RENEW)


@pytest.fixture
def announce_group(monkeypatch):
    owner = crypto.Identity.generate()
    m = make_manifest(owner, "unseenet.nodes.announce", "open", pow_bits=BITS)
    monkeypatch.setattr(known_nodes, "NODES_ANNOUNCE_GROUP", m.group)
    monkeypatch.setattr(announcing, "NODES_ANNOUNCE_GROUP", m.group)
    from unseenet.core import carrying
    monkeypatch.setattr(carrying, "INFRASTRUCTURE", carrying.INFRASTRUCTURE | {m.group})
    return m


def hold(node, m):
    """The announcement group, as the project made it (not under test here)."""
    node.store.add(m, m.to_bytes())
    node.store.set_manifest(Manifest.from_article(m))


@pytest.mark.usefixtures("ripening_rules")
async def test_a_node_ripens_its_key_and_announces_itself(tmp_path, announce_group, monkeypatch):
    pytest.importorskip("chiavdf")
    from unseenet.node import server as node_server
    monkeypatch.setattr(node_server, "POST_PAST", timedelta(days=30))    # the test's clock
    clock = [T0]
    node = Node(Store(), NodeConfig(name="kvisten", min_pow=BITS, forward_delay=(0, 0)),
                key=crypto.Identity.generate())
    hold(node, announce_group)
    a = announcing.Announcer(node, tmp_path, "onion:" + "b" * 56 + ".onion", ripen_to=0,
                             now=lambda: clock[0])
    mid = await a.run_once()
    assert mid is not None and a.level == 0
    raw = node.store.get(mid)
    assert b"node kvisten" in raw and node.key.key_text.encode() in raw
    assert await a.run_once() is None                       # nothing changed: not again
    # what it carries changes: announced again the next day, the old one gone
    node.config.carries = ["alt.*"]
    clock[0] += timedelta(hours=2)
    assert await a.run_once() is None                       # once a day at most
    clock[0] += timedelta(days=1)
    mid2 = await a.run_once()
    assert mid2 and node.store.get(mid) is None and b'"alt.*"' in node.store.get(mid2)


@pytest.mark.usefixtures("ripening_rules")
async def test_what_a_node_takes_in_the_announcement_group(tmp_path, announce_group):
    pytest.importorskip("chiavdf")
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)),
                key=crypto.Identity.generate())
    hold(node, announce_group)
    other = Node(Store(), NodeConfig(name="other", min_pow=BITS), key=crypto.Identity.generate())
    hold(other, announce_group)
    a = announcing.Announcer(other, tmp_path, "onion:" + "c" * 56 + ".onion", ripen_to=0)
    mid = await a.run_once()
    for gid in [g[0] for g in other.store.groups()]:          # the ripe@ chain, then the post
        if gid.startswith("ripe@"):
            node.accept(other.store.get(other.store.manifest(gid).message_id), from_peer=True)
    node.accept(other.store.get(mid), from_peer=True)
    # not an announcement at all
    junk = new_article(announce_group.group, "node x", "hello\n", from_name="x")
    junk.finalize(other.key, 16)
    junk.set("Key-Ripening", a.chain.header())
    with pytest.raises(ArticleError) as e:
        node.accept(junk.to_bytes())
    assert e.value.reason == "syntax"


async def test_a_client_reads_checks_and_counts_announced_nodes(tmp_path, announce_group):
    """Section 7: a client reads the announcements, checks a node before it offers or
    uses it (5.3), and shows how many announced nodes carry a group."""
    pytest.importorskip("chiavdf")
    from unseenet.client.session import Session
    from unseenet.core.vault import Vault
    node = Node(Store(), NodeConfig(name="kvisten", min_pow=BITS, forward_delay=(0, 0),
                                    carries=["alt.*"]), key=crypto.Identity.generate())
    hold(node, announce_group)
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    await announcing.Announcer(node, tmp_path, addr, ripen_to=0).run_once()
    # a second "node" announces somebody else's address: its key will not match
    liar = Node(Store(), NodeConfig(name="liar", min_pow=BITS), key=crypto.Identity.generate())
    hold(liar, announce_group)
    (tmp_path / "x").mkdir()
    await announcing.Announcer(liar, tmp_path / "x", addr, ripen_to=0).run_once()
    for mid, gid in liar.store.received_since(0):         # its ripe@ chain, then its word
        if gid != announce_group.group or mid != announce_group.message_id:
            try:
                node.accept(liar.store.get(mid), from_peer=True)
            except ArticleError as exc:
                assert exc.reason == "duplicate"
    s = Session(Vault.open(tmp_path / "c.vault", "pw", ops=1, mem=8192 * 1024),
                status=lambda *_: None)
    s.new_identity("a", "A")
    s.add_node(addr)
    found = {e["name"]: e for e in await s.refresh_announced_nodes()}
    assert set(found) == {"kvisten", "liar"} and found["kvisten"]["checked"] is None
    assert await s.check_announced(found["kvisten"]["key"]) is True
    assert await s.check_announced(found["liar"]["key"]) is False
    assert s.carrying_nodes("alt.test@abcdefghijklmnop")["checked"] == 1
    assert s.carrying_nodes("dk.snak@abcdefghijklmnop")["nodes"] == 1      # the liar says *
    info = await s.node_info(addr)
    assert info["carried"] == {"groups": ["alt.*"]} and isinstance(info["carries"], int)
    await s.close()
    server.close()
