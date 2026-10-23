"""#377: keeping and removing blobs (UN-RFC 0027 sections 7, 8.1; UN-RFC 0017 2.2)."""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from test_blobs import _manifest, _with_blobs
from unseenet.core import blobs as bl
from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import canonical_json
from unseenet.core.pins import pin_article
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig

BITS = 8
ON = {"max_size": 1048576, "retention_days": 30, "groups": "*"}


def _node(**blobs) -> Node:
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), blobs=ON | blobs))


def _setup(node):
    owner = crypto.Identity.generate()
    m = _manifest(owner, {"max_size": 1048576})
    node.accept(m.to_bytes())
    return owner, m.group


def _post(node, who, gid, data=None, **kw):
    data = data or b"\x89PNG" + os.urandom(2000)
    art = _with_blobs(who, gid, [data], **kw)
    node.accept(art.to_bytes(), staged={bl.blob_id(data): (data, time.monotonic())})
    return art, bl.blob_id(data)


def test_a_cancelled_posts_blob_goes():
    node = _node()
    owner, gid = _setup(node)
    art, bid = _post(node, owner, gid)
    assert node.blobs.has(bid)
    cancel = new_article(gid, None, "", extra=[("Control", f"cancel {art.message_id}")]).finalize(owner, BITS)
    node.accept(cancel.to_bytes())
    assert not node.blobs.has(bid)


def test_a_blob_two_posts_share_stays_while_one_does():
    node = _node()
    owner, gid = _setup(node)
    data = b"\x89PNG" + os.urandom(2000)
    first, bid = _post(node, owner, gid, data)
    second = _with_blobs(owner, gid, [data], extra=[("References", first.message_id)])
    node.accept(second.to_bytes())                            # already stored: nothing to stage
    cancel = new_article(gid, None, "", extra=[("Control", f"cancel {first.message_id}")]).finalize(owner, BITS)
    node.accept(cancel.to_bytes())
    assert node.blobs.has(bid)


def test_expiry_and_retention_but_pinned_blobs_stay():
    node = _node()
    owner, gid = _setup(node)
    old, bid_old = _post(node, owner, gid)
    pinned, bid_pin = _post(node, owner, gid)
    young, bid_young = _post(node, owner, gid)
    node.accept(pin_article(owner, gid, pinned.message_id, pow_bits=BITS).to_bytes())
    # every blob is 40 days old: past the node's 30 days of blob retention
    node.store.db.execute("UPDATE blob_meta SET stored_at = stored_at - ?", (40 * 86400,))
    node.store.db.execute("UPDATE articles SET date = date - ? WHERE message_id=?",
                          (200 * 86400, old.message_id))
    node.store.db.commit()
    node.store.expire(90)
    assert node.store.get(old.message_id) is None
    node.sweep_blobs()
    assert not node.blobs.has(bid_old)                         # its article expired
    assert not node.blobs.has(bid_young) and node.store.get(young.message_id)   # retention
    assert node.blobs.has(bid_pin)                             # kept with its pinned post


def test_refused_by_the_operator():
    node = _node()
    owner, gid = _setup(node)
    art, bid = _post(node, owner, gid)
    node.store.refuse_blob(bid, "not here")
    node.sweep_blobs(retention=False)
    assert not node.blobs.has(bid) and node.store.get(art.message_id)   # the article stays
    # posting it again: accepted, but the blob is not taken back
    data = node.store.blob_refs(art.message_id)
    assert data
    again = _with_blobs(owner, gid, [b"\x89PNG" + os.urandom(10)])
    node.store.refuse_blob(bl.parse_blobs(again)[0][0])
    node.accept(again.to_bytes())                              # nothing staged, nothing asked


def test_refusal_lists_only_from_configured_keys():
    lister, stranger = crypto.Identity.generate(), crypto.Identity.generate()
    node = _node(refusal_keys=[lister.key_text], refusal_groups="dk.*")
    owner, gid = _setup(node)
    art, bid = _post(node, owner, gid)
    body = canonical_json({"blobs": [bid], "reason": "test", "v": 1})
    for who in (stranger, lister):
        lst = new_article(gid, "Refusals", body, from_name="L",
                          extra=[("Content-Type", "application/x-unseenet-blob-refusals")])
        node.accept(lst.finalize(who, BITS).to_bytes())
        assert node.blobs.has(bid) == (who is stranger)
    assert node.store.blob_refused(bid)


def test_daily_quotas():
    node = _node(daily_per_key=5000)
    owner, gid = _setup(node)
    _post(node, owner, gid)                                   # about 2 KiB
    _post(node, owner, gid)
    with pytest.raises(ArticleError, match="quota"):
        _post(node, owner, gid)
    other = crypto.Identity.generate()
    _post(node, other, gid)                                   # per key
    # from a peer: accepted and passed on, its blobs not fetched
    art = _with_blobs(owner, gid, [b"\x89PNG" + os.urandom(2000)])
    node.accept(art.to_bytes(), source="peer", from_peer=True)
    assert node.store.get(art.message_id) and art.message_id not in node.blob_wait


def test_kept_blobs_are_limited_per_group(monkeypatch):
    monkeypatch.setattr(bl, "MAX_KEPT_PER_GROUP", 5000)
    node = _node()
    owner, gid = _setup(node)
    a, _ = _post(node, owner, gid)
    b, _ = _post(node, owner, gid)
    c, _ = _post(node, owner, gid)
    now = datetime.now(timezone.utc)
    node.accept(pin_article(owner, gid, a.message_id, pow_bits=BITS, now=now).to_bytes())
    node.accept(pin_article(owner, gid, b.message_id, pow_bits=BITS,
                            now=now + timedelta(minutes=10)).to_bytes())
    with pytest.raises(ArticleError, match="8 MiB"):
        node.accept(pin_article(owner, gid, c.message_id, pow_bits=BITS,
                                now=now + timedelta(minutes=20)).to_bytes())
