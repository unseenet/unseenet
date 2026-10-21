"""Nodes and clients with key ripening required (UN-RFC 0025 as amended in #278)."""
import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session, SessionError
from unseenet.core import crypto
from unseenet.core import ripening as rp
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import make_group_id, manifest_article
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

pytest.importorskip("chiavdf")
pytestmark = pytest.mark.usefixtures("ripening_rules")
KDF = {"ops": 1, "mem": 8192 * 1024}


async def _node(**kw):
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), **kw))
    server = await node.serve("127.0.0.1", 0)
    return node, server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def _session(tmp_path, name, *addrs):
    s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity(name, name.title())
    for a in addrs:
        s.add_node(a)
    return s


def _chain(pk, t_total):
    chain = rp.Chain()
    while chain.t < t_total:
        chain.segments.append(rp.prove_segment(pk, chain.end, rp.next_segment_length(chain.t)))
    return chain


def _ripe_manifest(ident, chain, serial=1, bits=20):
    gid = make_group_id(rp.GROUP_NAME, ident.public_key)
    data = {"v": 1, "name": rp.GROUP_NAME, "type": "channel", "owner": ident.key_text,
            "serial": serial, "min_pow": 0, "retention_days": 7, "view": "data",
            "ripening": chain.to_manifest()}
    art = manifest_article(ident, gid, data, bits)
    art.set("Key-Ripening", chain.header())
    return art


async def test_a_new_key_ripens_publishes_ripe_and_posts(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, server, addr = await _node()
    s = _session(tmp_path, "andreas", addr)
    assert s.published_level() is None
    gid = await s.create_group("dk.snak", "open", min_pow=8)      # ripens first, by itself
    msgid = await s.post(gid, "Hej", "Første\n")
    assert s.published_level() == 0 and s.ripening().level == 0
    assert node.store.manifest(s.ripe_group()) is not None
    art = node.store.get(msgid).decode()
    assert "Key-Ripening: vdf-cg1; t=" in art
    # level 0 pays +6 bits on top of the group's 8 (section 5)
    assert await s.required_pow(gid) == 8 + 6
    await s.close()
    server.close()


async def test_riper_keys_pay_less(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, server, addr = await _node()
    s = _session(tmp_path, "andreas", addr)
    gid = await s.create_group("dk.snak", "open", min_pow=20)
    while s.ripening().level is None or s.ripening().level < 3:
        assert await s.ripen_segment()
    await s.publish_ripening()
    assert s.published_level() == 3
    assert await s.required_pow(gid) == 20                      # level 3: no surcharge
    await s.post(gid, "Billigere", "nu\n")
    await s.close()
    server.close()


async def test_node_says_what_is_missing(monkeypatch):
    node, server, _ = await _node()
    ident = crypto.Identity.generate()
    art = new_article("alt.test@" + crypto.fingerprint(ident.public_key), "x", "y\n")
    art.finalize(ident, 20)
    with pytest.raises(ArticleError, match="ripening"):
        node._required_pow(art, None, 0, None, False)            # no Key-Ripening at all
    chain = _chain(ident.public_key, rp.LEVELS[0][1])
    art.set("Key-Ripening", chain.header())
    with pytest.raises(ArticleError, match="unknown"):          # ripe@ not here yet
        node._required_pow(art, None, 0, None, False)
    node.accept(_ripe_manifest(ident, chain).to_bytes())
    assert node._required_pow(art, None, 0, None, False) == 8 + 6
    server.close()


async def test_postage_is_checked_before_ripening(monkeypatch):
    node, server, _ = await _node()
    ident = crypto.Identity.generate()
    art = new_article("alt.test@" + crypto.fingerprint(ident.public_key), "x", "y\n")
    art.finalize(ident, 1)
    art.set("Key-Ripening", rp.format_header(5, bytes(100)))   # bogus, never verified
    with pytest.raises(ArticleError, match="postage"):
        node._required_pow(art, None, 0, None, False)
    server.close()


async def test_ripe_must_extend_and_belong_to_its_key(monkeypatch):
    node, server, _ = await _node()
    ident, other = crypto.Identity.generate(), crypto.Identity.generate()
    chain = _chain(ident.public_key, rp.LEVELS[0][1])
    node.accept(_ripe_manifest(ident, chain).to_bytes())
    fresh = _chain(ident.public_key, rp.LEVELS[0][1])            # same key, but a new chain...
    fresh.segments[-1] = rp.prove_segment(ident.public_key, fresh.segments[-2].y, 7)
    fresh.segments.append(rp.prove_segment(ident.public_key, fresh.end, rp.LEVELS[0][1]))
    with pytest.raises(ArticleError, match="extend|ripening"):
        node.accept(_ripe_manifest(ident, fresh, serial=2).to_bytes())
    longer = rp.Chain(list(chain.segments))
    longer.segments.append(rp.prove_segment(ident.public_key, longer.end, 1 << 12))
    node.accept(_ripe_manifest(ident, longer, serial=3).to_bytes())   # extends: fine
    stolen = _ripe_manifest(other, chain)                              # another key's chain
    with pytest.raises(ArticleError, match="ripening"):
        node.accept(stolen.to_bytes())
    server.close()


async def test_private_posts_need_no_ripening(tmp_path, monkeypatch):
    """Sealed posts are signed by one-time keys, which cannot ripen (section 3.5)."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, server, addr = await _node()
    a, b = _session(tmp_path, "andreas", addr), _session(tmp_path, "sonia", addr)
    await b.ensure_inbox()
    await a.ensure_inbox()
    await a.send_private(b.my_inbox, "Hej", "privat\n", owner_key=b.identity().public_key)
    await b.fetch_group(b.my_inbox)
    assert any(m.subject == "Hej" for m in b.private_messages())
    for s in (a, b):
        await s.close()
    server.close()


async def test_a_node_without_our_chain_gets_it_and_the_post(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node1, server1, addr1 = await _node()
    node2, server2, addr2 = await _node()
    s = _session(tmp_path, "andreas", addr1)
    await s.ensure_ripe()                              # published to node1 only
    assert node1.store.manifest(s.ripe_group()) is not None
    s.add_node(addr2)
    ident = s.identity()
    gid2 = make_group_id("dk.andet", ident.public_key)
    art = manifest_article(ident, gid2, {"v": 1, "name": "dk.andet", "type": "open",
                           "owner": ident.key_text, "serial": 1, "min_pow": 0}, 20)
    await s._post_article(art, addr2)                  # 441 ripening unknown, chain, again
    assert node2.store.manifest(s.ripe_group()) is not None
    assert node2.store.manifest(gid2) is not None
    await s.close()
    for srv in (server1, server2):
        srv.close()


async def test_forwarding_offers_ripe_first(tmp_path, monkeypatch):
    from unseenet.node.server import PeerConfig
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, server, addr = await _node(peers=[PeerConfig(name="friend", address="127.0.0.1:9")])
    s = _session(tmp_path, "andreas", addr)
    gid = await s.create_group("dk.snak", "open", min_pow=8)
    msgid = await s.post(gid, "Hej", "videre\n")
    queue = node.store.due("friend", 100)
    ripe = node.store.manifest(s.ripe_group()).message_id
    assert ripe in queue and queue.index(ripe) < queue.index(msgid)
    await s.close()
    server.close()


def test_min_ripe_is_advertised_and_dash_means_none():
    assert NodeConfig().min_ripe == 0
    assert NodeConfig(min_ripe=None).min_ripe is None


async def test_a_node_from_before_ripening_gets_no_header(tmp_path, monkeypatch):
    """A 0.3 node puts Key-Ripening in the canonical form, so a client must not send
    it there (the signature would not match), nor ripen or pay a surcharge for it."""
    import unseenet.node.server as srv
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    original = srv.Session.send

    def without_minripe(self, line):
        if not line.startswith("UNSEENET-MINRIPE"):
            original(self, line)
    monkeypatch.setattr(srv.Session, "send", without_minripe)
    rp.scale_for_tests(16, rules=False)              # a 0.3 node: no surcharge, no floor
    node, server, addr = await _node(min_ripe=None)
    s = _session(tmp_path, "andreas", addr)
    gid = await s.create_group("dk.snak", "open", min_pow=8)
    msgid = await s.post(gid, "Hej", "gammel node\n")
    assert "Key-Ripening" not in node.store.get(msgid).decode()
    assert s.ripening().t == 0 and node.store.manifest(s.ripe_group()) is None
    assert await s.required_pow(gid) == 8                     # no surcharge either
    await s.close()
    server.close()


async def test_private_posts_carry_the_senders_ripening_inside(tmp_path, monkeypatch):
    """Section 3.5: the sender's Key-Ripening travels in the sealed box; the recipient
    can check it and, if it wants, hide posts from unripe strangers."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, server, addr = await _node()
    a, b = _session(tmp_path, "andreas", addr), _session(tmp_path, "sonia", addr)
    stranger = _session(tmp_path, "fremmed", addr)
    for s in (a, b, stranger):
        await s.ensure_inbox()                          # ripens to level 0 and publishes
    while a.ripening().level < 2:
        assert await a.ripen_segment()
    await a.publish_ripening()
    outer = await a.send_private(b.my_inbox, "Hej", "fra en moden nøgle\\n",
                                 owner_key=b.identity().public_key)
    assert "Key-Ripening" not in node.store.get(outer).decode()   # the node sees none
    await stranger.send_private(b.my_inbox, "Køb", "spam\\n", owner_key=b.identity().public_key)
    await b.fetch_group(b.my_inbox)
    got = {m.subject: m for m in b.private_messages()}
    assert got["Hej"].sender_ripening and await b.sender_level(got["Hej"]) == 2
    assert await b.sender_level(got["Køb"]) == 0
    shown = lambda: {m.subject for m, _ in b.threads(b.my_inbox)}     # what clients show
    assert shown() >= {"Hej", "Køb"}                                   # setting off: all shown

    b.set_private_min_ripe(1)
    await b.check_private_senders()
    assert shown() == {"Hej"}                                          # the stranger is hidden
    b.add_contact(stranger.identity().key_text, "Fremmed")
    assert "Køb" in shown()                                            # contacts always come
    for s in (a, b, stranger):
        await s.close()
    server.close()
