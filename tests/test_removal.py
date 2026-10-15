"""UN-RFC 0013: removing groups."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.nntp import Client
from unseenet.node.peering import Feeder
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}


def rmgroup(group, who):
    return new_article(group, None, "bye\n", extra=[("Control", "rmgroup")]).finalize(who, BITS)


def make_node(**kw):
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), **kw))


def test_only_owner_can_remove_and_removal_is_final():
    node = make_node()
    owner, other = crypto.Identity.generate(), crypto.Identity.generate()
    m = make_manifest(owner, "andlotest", "open", pow_bits=BITS)
    node.accept(m.to_bytes())
    post = new_article(m.group, "hej", "x", from_name="a").finalize(other, BITS)
    node.accept(post.to_bytes())

    with pytest.raises(ArticleError) as e:
        node.accept(rmgroup(m.group, other).to_bytes())
    assert e.value.reason == "permission"

    node.accept(rmgroup(m.group, owner).to_bytes())
    assert node.store.manifest(m.group) is None and node.store.get(post.message_id) is None
    assert node.store.tombstone(m.group) == "owner"
    again = make_manifest(owner, "andlotest", "open", serial=2, pow_bits=BITS)
    with pytest.raises(ArticleError) as e:
        node.accept(again.to_bytes())                    # not even the owner can recreate it
    assert e.value.reason == "group"


def test_rmgroup_for_unknown_group_needs_owner_fingerprint():
    node = make_node()
    owner, other = crypto.Identity.generate(), crypto.Identity.generate()
    gid = make_manifest(owner, "x", "open", pow_bits=BITS).group
    with pytest.raises(ArticleError):
        node.accept(rmgroup(gid, other).to_bytes())
    node.accept(rmgroup(gid, owner).to_bytes())          # tombstone even without the manifest
    with pytest.raises(ArticleError):
        node.accept(make_manifest(owner, "x", "open", pow_bits=BITS).to_bytes())


async def test_rmgroup_replicates_and_group_reports_removed():
    b = make_node(name="b")
    server_b = await b.serve("127.0.0.1", 0)
    addr_b = f"127.0.0.1:{server_b.sockets[0].getsockname()[1]}"
    a = make_node(name="a", peers=[PeerConfig(name="b", address=addr_b)])
    owner = crypto.Identity.generate()
    m = make_manifest(owner, "dk.fejl", "open", pow_bits=BITS)
    a.accept(m.to_bytes())
    await Feeder(a, a.config.peers[0]).run_once()
    assert b.store.manifest(m.group) is not None

    a.accept(rmgroup(m.group, owner).to_bytes())
    await Feeder(a, a.config.peers[0]).run_once()
    assert b.store.tombstone(m.group) == "owner" and b.store.manifest(m.group) is None

    c = await Client.connect(addr_b)
    code, text = await c.command(f"GROUP {m.group}")
    assert code == 411 and "removed by its owner" in text
    assert not [ln for ln in await c.list_active() if m.group in ln]
    await c.quit()
    server_b.close()


def test_operator_drop_is_local_and_reversible():
    node = make_node(peers=[PeerConfig(name="p", address="127.0.0.1:1")])
    owner = crypto.Identity.generate()
    m = make_manifest(owner, "spam.stuff", "open", pow_bits=BITS)
    node.accept(m.to_bytes())
    node.store.dequeue("p", m.message_id)
    node.drop_group(m.group)
    assert node.store.tombstone(m.group) == "operator"
    assert node.store.due("p") == []                     # nothing sent to peers
    with pytest.raises(ArticleError):
        node.accept(make_manifest(owner, "spam.stuff", "open", serial=2, pow_bits=BITS).to_bytes())
    assert node.store.lift_tombstone(m.group)
    node.accept(make_manifest(owner, "spam.stuff", "open", serial=3, pow_bits=BITS).to_bytes())


async def test_client_removes_own_group(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = make_node()
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("a", "A")
    s.add_node(addr)
    gid = await s.create_group("andlotest", "inbox", min_pow=10)
    await s.fetch_group(gid)
    await s.remove_group(gid)
    assert gid not in s.data["subscribed"] and gid not in s.cache
    assert node.store.tombstone(gid) == "owner"
    with pytest.raises(sess.SessionError):
        await s.remove_group(s.my_inbox)                  # never your own inbox
    await s.close()
    server.close()
