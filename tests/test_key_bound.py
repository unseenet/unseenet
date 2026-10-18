"""UN-RFC 0029: key-bound groups expire unless their owner's client renews them."""

import random
import time
from datetime import datetime, timedelta, timezone

import pytest

import unseenet.core.store as store_mod
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article, parse_date
from unseenet.core.groups import (MAX_LIFETIME, Manifest, canonical_json, inbox_article,
                                  is_key_bound, make_group_id, make_manifest, manifest_article,
                                  personal_inbox_id)
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}
DAY = 86400


def _node(**kw) -> Node:
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), **kw))


def test_which_groups_are_key_bound():
    pk = crypto.Identity.generate().public_key
    for name in ("inbox", "names", "profile", "avatar"):
        assert is_key_bound(make_group_id(name, pk))
    assert not is_key_bound(make_group_id("unseenet.names", pk))   # the registrar's group
    assert not is_key_bound(make_group_id("dk.snak", pk))


def test_key_bound_manifest_gets_expires_and_ordinary_does_not():
    owner = crypto.Identity.generate()
    inbox = make_manifest(owner, "inbox", "inbox", pow_bits=BITS)
    m = Manifest.from_article(inbox)
    assert m.expires is not None
    assert m.expires <= parse_date(inbox["Date"]) + MAX_LIFETIME
    assert m.expires > datetime.now(timezone.utc) + timedelta(days=729)
    assert not m.expired() and not m.renewal_due()
    plain = Manifest.from_article(make_manifest(owner, "dk.snak", "open", pow_bits=BITS))
    assert plain.expires is None and not plain.expired()


def _raw_manifest(owner, name, data):
    gid = make_group_id(name, owner.public_key)
    art = new_article(gid, None, canonical_json(data),
                      extra=[("Control", "manifest"), ("Content-Type", "application/json")])
    return art.finalize(owner, BITS)


def test_manifest_without_or_with_too_late_expires_is_refused():
    owner = crypto.Identity.generate()
    base = {"v": 1, "name": "inbox", "type": "inbox", "owner": owner.key_text, "serial": 1,
            "min_pow": 0, "retention_days": 30}
    with pytest.raises(ArticleError, match="needs expires"):
        Manifest.from_article(_raw_manifest(owner, "inbox", base))
    late = (datetime.now(timezone.utc) + timedelta(days=800)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(ArticleError, match="730 days"):
        Manifest.from_article(_raw_manifest(owner, "inbox", {**base, "expires": late}))


def test_node_hides_then_removes_an_expired_inbox(monkeypatch):
    owner, writer = crypto.Identity.generate(), crypto.Identity.generate()
    node = _node()
    gid = personal_inbox_id(owner.public_key)
    node.accept(make_manifest(owner, "inbox", "inbox", pow_bits=BITS).to_bytes())
    node.accept(inbox_article(gid, owner.public_key, from_name="w", subject="s", body="b",
                              sender=writer, pow_bits=BITS).to_bytes())
    assert node.store.manifest(gid) is not None
    assert gid in [g for g, *_ in node.store.groups()]

    later = time.time() + 731 * DAY
    monkeypatch.setattr(store_mod.time, "time", lambda: later)
    assert node.store.manifest(gid) is None                    # not carried any more
    assert gid not in [g for g, *_ in node.store.groups()]     # not listed or offered
    assert node.store.state_ids(gid) == []
    with pytest.raises(ArticleError, match="group"):           # posts: 441 group
        node.accept(inbox_article(gid, owner.public_key, from_name="w", subject="s", body="b",
                                  pow_bits=BITS).to_bytes())
    assert node.store.remove_expired_key_bound() == []          # still within 30 days

    much_later = later + 31 * DAY
    monkeypatch.setattr(store_mod.time, "time", lambda: much_later)
    assert node.store.remove_expired_key_bound() == [gid]
    assert not node.store.known_group(gid) and node.store.numbers(gid) == []


def test_renewal_brings_an_expired_inbox_back_even_on_a_closed_node():
    owner = crypto.Identity.generate()
    node = _node(new_groups="manual")                            # takes no new groups
    gid = personal_inbox_id(owner.public_key)
    past = datetime.now(timezone.utc) - timedelta(days=750)
    data = {"v": 1, "name": "inbox", "type": "inbox", "owner": owner.key_text, "serial": 3,
            "min_pow": 0, "retention_days": 30}
    old = manifest_article(owner, gid, dict(data), BITS, now=past)  # ran out 20 days ago
    node.store.add(old, old.to_bytes())                         # carried before it expired
    node.store.set_manifest(Manifest.from_article(old))
    assert node.store.expired(gid) and node.store.manifest(gid) is None

    renewal = manifest_article(owner, gid, dict(data, serial=4), BITS)
    node.accept(renewal.to_bytes())
    assert node.store.manifest(gid).serial == 4 and not node.store.expired(gid)

    stranger = crypto.Identity.generate()                       # nobody else can renew it
    with pytest.raises(ArticleError):
        node.accept(manifest_article(stranger, gid, dict(data, serial=9), BITS).to_bytes())


def test_expired_manifest_is_refused():
    owner = crypto.Identity.generate()
    node = _node()
    old = make_manifest(owner, "inbox", "inbox", pow_bits=BITS)
    # a manifest dated 800 days ago has run out
    past = datetime.now(timezone.utc) - timedelta(days=800)
    gid = personal_inbox_id(owner.public_key)
    stale = manifest_article(owner, gid, dict(Manifest.from_article(old).raw), BITS, now=past)
    with pytest.raises(ArticleError, match="expired"):
        node.accept(stale.to_bytes())


def test_stored_manifest_from_before_0029_lasts_until_renewed():
    owner = crypto.Identity.generate()
    s = Store()
    base = {"v": 1, "name": "inbox", "type": "inbox", "owner": owner.key_text, "serial": 1,
            "min_pow": 0, "retention_days": 30}
    art = _raw_manifest(owner, "inbox", base)
    s.add(art, art.to_bytes())
    s.db.execute("UPDATE groups SET manifest=?, manifest_id=?, serial=1 WHERE group_id=?",
                 (canonical_json(base), art.message_id, art.group))
    assert not s.expired(art.group)                    # kept, as from its Date ...
    assert s.manifest(art.group).serial == 1
    assert s.expired(art.group, now=time.time() + 731 * DAY)    # ... for the full lifetime
    assert s.remove_expired_key_bound(now=time.time() + 31 * DAY) == []


async def test_client_renews_all_key_bound_groups_together(tmp_path):
    s = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me")
    me = s.identity()
    posted = []

    async def fake_post(art, node=None):
        posted.append(art)
        return art.message_id

    async def no_pow(_gid):
        return BITS

    s._post_article = fake_post
    s.required_pow = no_pow
    for name in ("inbox", "profile"):
        gid = make_group_id(name, me.public_key)
        art = make_manifest(me, name, "inbox" if name == "inbox" else "channel", pow_bits=BITS)
        entry = s.group_entry(gid)
        entry.update({"owner": True, "manifest": Manifest.from_article(art).raw})

    assert await s.renew_key_bound() == []                      # fresh: nothing to do

    rng = random.Random(1)
    soon = datetime.now(timezone.utc) + timedelta(days=200)     # 530 days left
    assert await s.renew_key_bound(now=soon, rng=rng) == []     # a moment is chosen ...
    at = s.data["identities"]["me"]["renew_at"]
    assert soon.timestamp() <= at <= soon.timestamp() + 30 * DAY
    renewed = await s.renew_key_bound(now=datetime.fromtimestamp(at + 1, timezone.utc))
    assert sorted(renewed) == sorted(s.key_bound_groups())     # ... and both renew together
    assert all(Manifest.from_article(a).serial == 2 for a in posted)
    assert "renew_at" not in s.data["identities"]["me"]


async def test_client_renews_at_once_when_expiry_is_near(tmp_path):
    s = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me")
    me = s.identity()

    async def fake_post(art, node=None):
        return art.message_id

    async def no_pow(_gid):
        return BITS

    s._post_article, s.required_pow = fake_post, no_pow
    gid = personal_inbox_id(me.public_key)
    s.group_entry(gid).update({"owner": True, "manifest": Manifest.from_article(
        make_manifest(me, "inbox", "inbox", pow_bits=BITS)).raw})
    near = datetime.now(timezone.utc) + timedelta(days=700)     # 30 days left
    assert await s.renew_key_bound(now=near) == [gid]
