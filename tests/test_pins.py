"""#361: kept articles (UN-RFC 0017 section 2.1) and pins (UN-RFC 0033) on the node."""
from datetime import datetime, timedelta, timezone

import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import Manifest, make_manifest
from unseenet.core.pins import pin_article
from unseenet.core.store import Store
from unseenet.node.pulling import Puller
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8
NOW = datetime.now(timezone.utc) - timedelta(days=2)
STEP = timedelta(minutes=10)        # Date is rounded to 10 minutes (UN-RFC 0002)


def _node(name="a", **kw) -> Node:
    return Node(Store(), NodeConfig(name=name, min_pow=BITS, forward_delay=(0, 0), **kw))


def _group(node, owner, gtype="open", **kw):
    m = make_manifest(owner, "dk.marsvin", gtype, pow_bits=BITS, **kw)
    node.accept(m.to_bytes())
    return m


def _post(node, who, gid, text, when=None):
    art = new_article(gid, text, text + "\n", from_name="X", now=when).finalize(who, BITS)
    node.accept(art.to_bytes(), now=(when + timedelta(seconds=1)) if when else None)
    return art


def _pin(node, who, gid, target, *, unpin=False, note="", when=None):
    art = pin_article(who, gid, target, unpin=unpin, note=note, pow_bits=BITS, now=when)
    node.accept(art.to_bytes(), now=(when + timedelta(seconds=1)) if when else None)
    return art


def test_who_may_pin():
    a = _node()
    owner, mod, someone = (crypto.Identity.generate() for _ in range(3))
    g = _group(a, owner, moderators=[mod.key_text]).group
    p = _post(a, someone, g, "Velkommen")
    _pin(a, owner, g, p.message_id, note="Læs denne først")
    _pin(a, mod, g, p.message_id)
    with pytest.raises(ArticleError, match="owner or a moderator"):
        _pin(a, someone, g, p.message_id)
    long_note = new_article(g, None, "x" * 257 + "\n",
                            extra=[("Control", f"pin {p.message_id}")]).finalize(owner, BITS)
    with pytest.raises(ArticleError, match="note"):
        a.accept(long_note.to_bytes())
    with pytest.raises(ArticleError, match="control"):
        _pin(a, owner, g, a.store.manifest(g).message_id)
    with pytest.raises(ArticleError, match="Message-ID"):
        _pin(a, owner, g, "nonsense")


def test_max_pins_in_the_manifest():
    owner = crypto.Identity.generate()
    assert Manifest.from_article(make_manifest(owner, "dk.a", "open", pow_bits=BITS))
    m = make_manifest(owner, "dk.a", "open", pow_bits=BITS)
    data = m.body.replace('"min_pow"', '"max_pins":26,"min_pow"')
    bad = new_article(m.group, None, data, extra=[("Control", "manifest"),
                      ("Content-Type", "application/json")]).finalize(owner, BITS)
    with pytest.raises(ArticleError, match="max_pins"):
        Manifest.from_article(bad)


def test_which_pins_are_in_force():
    a = _node()
    owner, mod = crypto.Identity.generate(), crypto.Identity.generate()
    m1 = _group(a, owner, moderators=[mod.key_text])
    g = m1.group
    posts = [_post(a, owner, g, f"p{i}") for i in range(7)]
    for i, p in enumerate(posts[:6]):                         # six pins: the five latest count
        _pin(a, owner if i else mod, g, p.message_id, when=NOW + i * STEP)
    force = a.store.pins_in_force(g)
    assert [x.target for x in force] == [p.message_id for p in reversed(posts[1:6])]
    _pin(a, owner, g, posts[5].message_id, unpin=True, when=NOW + 10 * STEP)
    assert posts[5].message_id not in [x.target for x in a.store.pins_in_force(g)]
    # the moderator's pin (posts[0]) comes back as the fifth, then goes when they are removed
    assert posts[0].message_id in [x.target for x in a.store.pins_in_force(g)]
    m2 = make_manifest(owner, "dk.marsvin", "open", serial=2, pow_bits=BITS)
    a.accept(m2.to_bytes())
    assert posts[0].message_id not in [x.target for x in a.store.pins_in_force(g)]
    # a cancelled target is not kept by a pin
    cancel = new_article(g, None, "", extra=[("Control", f"cancel {posts[1].message_id}")]
                         ).finalize(owner, BITS)
    a.accept(cancel.to_bytes())
    assert posts[1].message_id not in [x.target for x in a.store.pins_in_force(g)]


def test_pinned_posts_outlive_the_window_and_come_first():
    a = _node()
    owner = crypto.Identity.generate()
    g = _group(a, owner, retention_days=30).group
    old = NOW - timedelta(days=20)
    welcome = _post(a, owner, g, "Velkommen", when=old)
    other = _post(a, owner, g, "Noget andet", when=old)
    pin = _pin(a, owner, g, welcome.message_id, when=old + timedelta(minutes=1))
    a.store.db.execute("UPDATE articles SET date = date - ?", (20 * 86400,))   # 40 days old now
    a.store.db.execute("UPDATE markers SET date = date - ?", (20 * 86400,))
    a.store.db.commit()
    a.store.expire(90)
    assert a.store.get(welcome.message_id) and a.store.get(pin.message_id)
    assert a.store.get(other.message_id) is None
    state = a.store.state_ids(g)
    assert state == [a.store.manifest(g).message_id, pin.message_id, welcome.message_id]
    # unpinned: the unpin is kept while inside the window, the post expires
    unpin = _pin(a, owner, g, welcome.message_id, unpin=True)
    a.store.expire(90)
    assert a.store.get(welcome.message_id) is None
    assert a.store.state_ids(g) == [a.store.manifest(g).message_id, unpin.message_id]


async def test_a_new_node_gets_an_old_pinned_post():
    a = _node("a")
    owner = crypto.Identity.generate()
    old = NOW - timedelta(days=40)
    m = make_manifest(owner, "dk.marsvin", "open", retention_days=30, pow_bits=BITS)
    a.accept(m.to_bytes())
    g = m.group
    welcome = _post(a, owner, g, "Velkommen", when=old)            # accepted while it was new
    pin = _pin(a, owner, g, welcome.message_id, when=NOW - timedelta(days=1))
    server = await a.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    b = _node("b", peers=[PeerConfig(name="a", address=addr)])
    res = await Puller(b, b.config.peers[0]).run_once()
    assert b.store.get(pin.message_id) and b.store.get(welcome.message_id), res
    server.close()


async def test_a_pin_before_its_target_is_pending():
    a = _node()
    owner = crypto.Identity.generate()
    g = _group(a, owner, retention_days=30).group
    old = NOW - timedelta(days=40)
    target = new_article(g, "Gammel", "x\n", from_name="X", now=old).finalize(owner, BITS)
    _pin(a, owner, g, target.message_id)                 # we do not hold the target
    a.accept(target.to_bytes())                          # old, but a pin names it
    assert a.store.get(target.message_id)
    stray = new_article(g, "Også gammel", "y\n", from_name="X", now=old).finalize(owner, BITS)
    with pytest.raises(ArticleError, match="older"):
        a.accept(stray.to_bytes())


def test_no_pins_in_inboxes():
    a = _node()
    owner = crypto.Identity.generate()
    inbox = make_manifest(owner, "inbox", "inbox", pow_bits=BITS)
    a.accept(inbox.to_bytes())
    with pytest.raises(ArticleError, match="inbox"):
        _pin(a, owner, inbox.group, "<x@y>")


def test_a_quick_undo_is_ordered_by_supersedes_not_by_the_rounded_date():
    """UN-RFC 0033 section 3.1: pin and unpin in the same 10 minutes."""
    for _ in range(8):                            # the Message-IDs fall either way
        a = _node()
        owner = crypto.Identity.generate()
        g = _group(a, owner).group
        p = _post(a, owner, g, "Hov")
        pin = _pin(a, owner, g, p.message_id, when=NOW)
        unpin = pin_article(owner, g, p.message_id, unpin=True, replaces=[pin.message_id],
                            pow_bits=BITS, now=NOW)
        a.accept(unpin.to_bytes())
        assert a.store.pins_in_force(g) == []
        again = pin_article(owner, g, p.message_id, replaces=[unpin.message_id, pin.message_id],
                            pow_bits=BITS, now=NOW)
        a.accept(again.to_bytes())
        assert [x.message_id for x in a.store.pins_in_force(g)] == [again.message_id]


def test_a_removed_moderators_unpin_gives_way():
    a = _node()
    owner, mod = crypto.Identity.generate(), crypto.Identity.generate()
    g = _group(a, owner, moderators=[mod.key_text]).group
    p = _post(a, owner, g, "Regler")
    pin = _pin(a, owner, g, p.message_id, when=NOW)
    unpin = pin_article(mod, g, p.message_id, unpin=True, replaces=[pin.message_id],
                        pow_bits=BITS, now=NOW + STEP)
    a.accept(unpin.to_bytes())
    assert a.store.pins_in_force(g) == []
    a.accept(make_manifest(owner, "dk.marsvin", "open", serial=2, pow_bits=BITS).to_bytes())
    assert [x.message_id for x in a.store.pins_in_force(g)] == [pin.message_id]
    other = _post(a, owner, g, "Andet")
    with pytest.raises(ArticleError, match="same target"):
        a.accept(pin_article(owner, g, other.message_id, replaces=[pin.message_id],
                             pow_bits=BITS).to_bytes())


def test_a_pin_follows_an_edit():
    """UN-RFC 0033 section 4.2 step 2: the current version of an edited post is kept."""
    a = _node()
    owner = crypto.Identity.generate()
    g = _group(a, owner, retention_days=30).group
    old = NOW - timedelta(days=20)
    v1 = _post(a, owner, g, "Velkommen", when=old)
    pin = _pin(a, owner, g, v1.message_id, when=old + STEP)
    v2 = new_article(g, "Velkommen!", "rettet\n", from_name="X", now=old + 2 * STEP,
                     extra=[("Supersedes", v1.message_id)]).finalize(owner, BITS)
    a.accept(v2.to_bytes(), now=old + 3 * STEP)
    assert a.store.get(v1.message_id) is None                     # withdrawn by the edit
    assert a.store.state_ids(g)[-1] == v2.message_id
    a.store.db.execute("UPDATE articles SET date = date - ?", (20 * 86400,))
    a.store.db.execute("UPDATE markers SET date = date - ?", (20 * 86400,))
    a.store.db.commit()
    a.store.expire(90)
    assert a.store.get(v2.message_id) and a.store.get(pin.message_id)


@pytest.fixture(autouse=True)
def _history_dates(monkeypatch):
    """These tests build history with old Dates, or move the clock, as nodes see articles
    over time; the rule that a POST is not more than an hour in the past (UN-RFC 0049
    section 3.2) has its own tests in test_origins.py."""
    from datetime import timedelta
    from unseenet.node import server as node_server
    monkeypatch.setattr(node_server, "POST_PAST", timedelta(days=3650))
