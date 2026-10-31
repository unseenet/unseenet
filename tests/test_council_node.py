"""Council groups on a node: carrying the copies, counting the chain, posting rules and
keeping the chain (UN-RFC 0054 sections 5 and 6)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.council import (Member, council_article, council_body,
                                   make_council_group_id, next_body)
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8
T0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=400)


def _node(name="a", peers=()):
    return Node(Store(), NodeConfig(name=name, min_pow=BITS,
                                    peers=[PeerConfig(name=p, address="x.onion") for p in peers]))


def _council(n=3, gtype="channel", **fields):
    ids = [crypto.Identity.generate() for _ in range(n)]
    body = council_body("unseenet.lists", gtype, seq=1, date=T0,
                        members=[Member(i.public_key, T0, True) for i in ids],
                        fields={"min_pow": 0, "retention_days": 30, **fields})
    return ids, make_council_group_id("unseenet.lists", body), body


def _post_all(node, ids, gid, body, **kw):
    for i in ids:
        node.accept(council_article(i, gid, body, pow_bits=BITS).to_bytes(), **kw)


def _post(author, gid, text="Hej"):
    return new_article(gid, text, text + "\n", from_name="M").finalize(author, BITS)


def test_the_genesis_counts_when_every_member_has_posted_it():
    node = _node()
    ids, gid, body = _council()
    _post_all(node, ids[:2], gid, body)
    assert node.store.manifest(gid) is None            # carried, not yet counted
    _post_all(node, ids[2:], gid, body)
    m = node.store.manifest(gid)
    assert m is not None and m.is_council and m.serial == 1 and set(m.council) == {
        i.public_key for i in ids}


def test_only_members_post_in_a_channel_council_group():
    node = _node()
    ids, gid, body = _council()
    _post_all(node, ids, gid, body)
    node.accept(_post(ids[0], gid).to_bytes())
    with pytest.raises(ArticleError) as err:
        node.accept(_post(crypto.Identity.generate(), gid).to_bytes())
    assert err.value.reason == "permission"


def test_an_open_council_group_takes_anybody():
    node = _node()
    ids, gid, body = _council(gtype="open")
    _post_all(node, ids, gid, body)
    node.accept(_post(crypto.Identity.generate(), gid).to_bytes())


def test_a_stranger_cannot_post_a_council_manifest():
    node = _node()
    ids, gid, body = _council()
    _post_all(node, ids, gid, body)
    stranger = crypto.Identity.generate()
    from unseenet.core.council import CouncilManifest
    nxt = next_body(CouncilManifest.from_body(gid, body), date=T0 + timedelta(days=1),
                    title="mine")
    with pytest.raises(ArticleError) as err:
        node.accept(council_article(stranger, gid, nxt, pow_bits=BITS).to_bytes())
    assert err.value.reason == "permission"
    with pytest.raises(ArticleError):                   # nor an owner's manifest
        from unseenet.core.groups import manifest_article
        node.accept(manifest_article(stranger, gid, {"v": 1, "name": "unseenet.lists",
                                                     "type": "channel", "serial": 9,
                                                     "owner": stranger.key_text},
                                     pow_bits=BITS).to_bytes())


def test_a_later_manifest_counts_with_a_majority():
    node = _node()
    ids, gid, body = _council()
    _post_all(node, ids, gid, body)
    from unseenet.core.council import CouncilManifest
    g = CouncilManifest.from_body(gid, body)
    b2 = next_body(g, date=T0 + timedelta(days=1), title="Lister")
    _post_all(node, ids[:1], gid, b2)
    assert node.store.manifest(gid).serial == 1
    _post_all(node, ids[1:2], gid, b2)
    m = node.store.manifest(gid)
    assert m.serial == 2 and m.title == "Lister"


def test_a_manifest_ahead_of_the_chain_is_asked_again():
    node = _node(peers=["b"])
    ids, gid, body = _council()
    from unseenet.core.council import CouncilManifest
    g = CouncilManifest.from_body(gid, body)
    b2 = next_body(g, date=T0 + timedelta(days=1), title="x")
    with pytest.raises(ArticleError) as err:
        node.accept(council_article(ids[0], gid, b2, pow_bits=BITS).to_bytes(),
                    source="b", from_peer=True)
    assert err.value.reason == "later"


def test_cancels_are_not_defined():
    node = _node()
    ids, gid, body = _council()
    _post_all(node, ids, gid, body)
    post = _post(ids[0], gid)
    node.accept(post.to_bytes())
    cancel = new_article(gid, None, "cancel\n",
                         extra=[("Control", f"cancel {post.message_id}")]).finalize(ids[0], BITS)
    with pytest.raises(ArticleError) as err:
        node.accept(cancel.to_bytes())
    assert err.value.reason == "permission"


def test_the_chain_is_kept_past_retention_and_offered_first():
    node = _node()
    ids, gid, body = _council()
    copies = [council_article(i, gid, body, pow_bits=BITS) for i in ids]
    for c in copies:
        node.accept(c.to_bytes())
    post = _post(ids[0], gid)
    node.accept(post.to_bytes())
    assert set(node.store.state_ids(gid)[:3]) == {c.message_id for c in copies}
    # everything is old now: the post goes, the chain stays
    node.store.db.execute("UPDATE articles SET date=? WHERE group_id=?",
                          (int(time.time()) - 400 * 86400, gid))
    node.store.db.commit()
    node.store.expire(90)
    assert all(node.store.has(c.message_id) for c in copies)
    assert not node.store.has(post.message_id)
    assert node.store.manifest(gid) is not None


def test_a_node_catching_up_counts_the_chain_from_the_copies():
    a, b = _node("a"), _node("b")
    ids, gid, body = _council()
    _post_all(a, ids, gid, body)
    from unseenet.core.council import CouncilManifest
    b2 = next_body(CouncilManifest.from_body(gid, body), date=T0 + timedelta(days=1), title="to")
    _post_all(a, ids[:2], gid, b2)
    for mid in a.store.state_ids(gid):
        b.accept(a.store.get(mid), source="a", from_peer=True)
    assert b.store.manifest(gid).serial == 2
