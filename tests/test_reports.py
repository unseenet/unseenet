"""UN-RFC 0045: spam reports - their form, the book, and what a node does (#122)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from unseenet import hierarchies as hz
from unseenet.core import crypto
from unseenet.core import reports as rpt
from unseenet.core.article import Article, ArticleError, new_article
from unseenet.core.groups import Manifest, is_key_bound, make_manifest
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig

BITS = 8
NOW = datetime.now(timezone.utc)


def node(**kw) -> Node:
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), **kw))


def group(n: Node, owner, name="dk.snak", gtype="open"):
    m = make_manifest(owner, name, gtype, pow_bits=BITS)
    n.accept(m.to_bytes())
    return m.group


def post(who, gid, body="køb billige ure", subject="Tilbud"):
    return new_article(gid, subject, body, from_name="x").finalize(who, BITS)


def reports_manifest(issuer, **extra):
    return make_manifest(issuer, "reports", "channel", pow_bits=BITS, extra=extra or None)


def report(issuer, posts=(), keys=(), note="", date=None):
    return rpt.report_article(issuer, rpt.report_body(posts, keys, note), pow_bits=BITS, now=date)


# --- the group and its manifest (section 3) ----------------------------------------

def test_reports_is_a_key_bound_channel():
    me = crypto.Identity.generate()
    gid = rpt.reports_group(me.public_key)
    assert is_key_bound(gid) and rpt.is_reports_group(gid)
    m = Manifest.from_article(reports_manifest(me, policy="Spam i dk.*", contact="inbox@x",
                                               automatic=False))
    assert m.type == "channel" and m.raw["policy"] == "Spam i dk.*" and m.expires
    with pytest.raises(ArticleError, match="channel"):
        Manifest.from_article(make_manifest(me, "reports", "open", pow_bits=BITS))
    with pytest.raises(ValueError, match="reports@"):
        make_manifest(me, "dk.snak", "open", pow_bits=BITS, extra={"policy": "x"})
    with pytest.raises(ValueError, match="2000"):
        reports_manifest(me, policy="x" * 2001)
    with pytest.raises(ValueError, match="true or false"):
        reports_manifest(me, automatic="ja")


# --- reports (section 4) ------------------------------------------------------------

def test_a_report_is_built_and_read_back():
    me, spammer = crypto.Identity.generate(), crypto.Identity.generate()
    art = report(me, posts=[("<a@x>", "dk.snak@abc", "spam")],
                 keys=[(spammer.key_text, "flood", None)], note="300 nye nøgler")
    r = rpt.parse_report(art)
    assert r.issuer == me.key_text and r.note == "300 nye nøgler"
    assert r.posts == (rpt.PostEntry("<a@x>", "dk.snak@abc", "spam"),)
    [k] = r.keys
    assert k.key == spammer.key_text and k.reason == "flood"
    assert k.until == r.date + timedelta(days=365)


def test_what_a_report_may_not_say():
    me = crypto.Identity.generate()
    for posts, keys, msg in (
            ([("<a@x>", "inbox@abc", "spam")], [], "sealed"),
            ([("<a@x>", "dk.snak@abc", "rude")], [], "reason"),
            ([("a@x", "dk.snak@abc", "spam")], [], "Message-ID"),
            ([], [(me.key_text, "spam", NOW + timedelta(days=400))], "365"),
            ([], [], "at least one"),
            ([("<%d@x>" % i, "g@x", "spam") for i in range(1001)], [], "1000")):
        with pytest.raises(ValueError, match=msg):
            rpt.report_body(posts, keys)
    with pytest.raises(ValueError, match="200"):
        rpt.report_body([("<a@x>", "g@x", "spam")], note="x" * 201)


def test_bad_entries_are_left_out_and_only_the_owner_reports():
    me, other = crypto.Identity.generate(), crypto.Identity.generate()
    gid = rpt.reports_group(me.public_key)
    body = json.dumps({"v": 1, "posts": [
        {"id": "<ok@x>", "group": "g@x", "reason": "spam"},
        {"id": "<sealed@x>", "group": "inbox@x", "reason": "spam"},
        {"id": "<why@x>", "group": "g@x", "reason": "boring"}],
        "keys": [{"key": other.key_text, "reason": "spam"},                       # no until
                 {"key": other.key_text, "reason": "spam", "until": "2099-01-01T00:00:00Z"}]})
    art = new_article(gid, None, body, extra=[("Content-Type", "application/json")]).finalize(me, BITS)
    r = rpt.parse_report(art)
    assert [p.id for p in r.posts] == ["<ok@x>"] and r.keys == ()
    forged = new_article(gid, None, body,
                         extra=[("Content-Type", "application/json")]).finalize(other, BITS)
    with pytest.raises(rpt.ReportError, match="own key"):
        rpt.parse_report(forged)


def test_the_book_shows_the_first_report_and_forgets_a_withdrawn_one():
    a, b, spammer = (crypto.Identity.generate() for _ in range(3))
    book = rpt.Book()
    first = rpt.parse_report(report(a, posts=[("<p@x>", "g@x", "spam")],
                                    date=NOW - timedelta(hours=1)))
    second = rpt.parse_report(report(b, posts=[("<p@x>", "g@x", "phishing")],
                                     keys=[(spammer.key_text, "spam", None)]))
    book.add(second)
    book.add(first, automatic=True)
    assert book.post("<p@x>").issuer == a.key_text and book.post("<p@x>").automatic
    assert book.post("<p@x>", {b.key_text}).reason == "phishing"
    assert book.key(spammer.key_text).issuer == b.key_text
    assert book.key(spammer.key_text, now=NOW + timedelta(days=366)) is None   # ran out
    book.remove(first.message_id)
    assert book.post("<p@x>").issuer == b.key_text
    book.remove(second.message_id)
    assert book.post("<p@x>") is None and book.key(spammer.key_text) is None


# --- hierarchies name issuers (section 7.1) -----------------------------------------

def test_hierarchy_lists_name_issuers_and_lower_ones_add():
    dk, snak = crypto.Identity.generate(), crypto.Identity.generate()
    i1, i2 = crypto.Identity.generate().key_text, crypto.Identity.generate().key_text
    snak_list = f"dk.snak.liste@{crypto.fingerprint(snak.public_key)}"
    dk_list = f"dk.liste@{crypto.fingerprint(dk.public_key)}"
    root = {"dk": hz.Hierarchy("dk", "governed", dk.key_text, dk_list)}
    top = hz.parse_hierarchy_list(json.dumps({
        "v": 1, "hierarchy": "dk", "groups": [], "report_issuers": [i1, "nonsense", i1],
        "sub": [{"name": "dk.snak", "policy": "governed", "maintainer": snak.key_text,
                 "list": snak_list}]}), "dk")
    assert top.report_issuers == (i1,)
    low = hz.parse_hierarchy_list(json.dumps({
        "v": 1, "hierarchy": "dk.snak", "groups": [], "report_issuers": [i2, i1]}), "dk.snak")
    lists = {"dk": top, "dk.snak": low}
    assert hz.report_issuers_for("dk.snak.biler", root, lists) == {i1: "dk", i2: "dk.snak"}
    assert hz.report_issuers_for("dk.mad", root, lists) == {i1: "dk"}
    many = [crypto.Identity.generate().key_text for _ in range(20)]
    assert len(hz.parse_hierarchy_list(json.dumps({"v": 1, "hierarchy": "dk", "groups": [],
                                                   "report_issuers": many}), "dk").report_issuers) == 16


# --- nodes (section 6) ----------------------------------------------------------------

def follow(issuer, posts="hide", keys="ignore"):
    return [{"issuer": issuer.key_text, "posts": posts, "keys": keys}]


def test_a_node_follows_nobody_unless_told():
    issuer, owner, spammer = (crypto.Identity.generate() for _ in range(3))
    n = node()
    gid = group(n, owner)
    spam = post(spammer, gid)
    n.accept(spam.to_bytes())
    n.accept(reports_manifest(issuer).to_bytes())
    n.accept(report(issuer, posts=[(spam.message_id, gid, "spam")]).to_bytes())
    assert not n.report_hidden(spam.message_id)
    assert "report_issuers" not in n.node_info()["policy"]


def test_a_followed_report_hides_a_post_held_and_one_that_comes_later():
    issuer, owner, spammer = (crypto.Identity.generate() for _ in range(3))
    n = node(follow_reports=follow(issuer))
    gid = group(n, owner)
    held, later = post(spammer, gid, "a"), post(spammer, gid, "b")
    n.accept(held.to_bytes())
    n.accept(reports_manifest(issuer).to_bytes())
    r = report(issuer, posts=[(held.message_id, gid, "spam"), (later.message_id, gid, "spam")])
    n.accept(r.to_bytes())
    assert n.report_hidden(held.message_id) and n.store.get(held.message_id)   # kept, unserved
    n.accept(later.to_bytes())                                                # taken, not passed on
    assert n.report_hidden(later.message_id)
    assert n.node_info()["policy"]["report_issuers"] == [issuer.key_text]
    # the issuer withdraws its report: served again
    cancel = new_article(r.group, "cancel", "", from_name="x",
                         extra=[("Control", f"cancel {r.message_id}")])
    n.accept(cancel.finalize(issuer, BITS).to_bytes())
    assert not n.report_hidden(held.message_id)


def test_delete_removes_held_posts_and_refuses_them_again():
    issuer, owner, spammer = (crypto.Identity.generate() for _ in range(3))
    n = node(follow_reports=follow(issuer, posts="delete"))
    gid = group(n, owner)
    spam, ok = post(spammer, gid), post(owner, gid, "velkommen")
    n.accept(spam.to_bytes())
    n.accept(ok.to_bytes())
    n.accept(reports_manifest(issuer).to_bytes())
    n.accept(report(issuer, posts=[(spam.message_id, gid, "spam")]).to_bytes())
    assert n.store.get(spam.message_id) is None and n.store.get(ok.message_id)
    with pytest.raises(ArticleError):
        n.accept(spam.to_bytes())


def test_reported_keys_are_refused_or_pay_more():
    issuer, owner, spammer = (crypto.Identity.generate() for _ in range(3))
    for keys, outcome in (("refuse", "permission"), ("surcharge", "postage"), ("ignore", None)):
        n = node(follow_reports=follow(issuer, keys=keys))
        gid = group(n, owner)
        n.accept(reports_manifest(issuer).to_bytes())
        n.accept(report(issuer, keys=[(spammer.key_text, "spam", None)]).to_bytes())
        art = post(spammer, gid)
        if outcome is None:
            n.accept(art.to_bytes())
            continue
        with pytest.raises(ArticleError) as err:
            n.accept(art.to_bytes())
        assert err.value.reason == outcome
        if keys == "surcharge":                                   # paying 6 bits more works
            paid = new_article(gid, "Tilbud", "x", from_name="x").finalize(spammer, BITS + 6)
            n.accept(paid.to_bytes())
    # the reported key may still renew its own key-bound groups
    n = node(follow_reports=follow(issuer, keys="refuse"))
    n.accept(reports_manifest(issuer).to_bytes())
    n.accept(report(issuer, keys=[(spammer.key_text, "spam", None)]).to_bytes())
    n.accept(make_manifest(spammer, "feed", "channel", view="feed", pow_bits=BITS).to_bytes())


def test_reports_by_others_in_the_issuers_group_do_not_count():
    issuer, owner, spammer = (crypto.Identity.generate() for _ in range(3))
    n = node(follow_reports=follow(issuer))
    gid = group(n, owner)
    spam = post(spammer, gid)
    n.accept(spam.to_bytes())
    n.accept(reports_manifest(issuer).to_bytes())
    forged = new_article(rpt.reports_group(issuer.public_key), "Report",
                         rpt.report_body([(spam.message_id, gid, "spam")]), from_name="x",
                         extra=[("Content-Type", "application/json")]).finalize(spammer, BITS)
    with pytest.raises(ArticleError):                     # a channel: only its owner posts
        n.accept(forged.to_bytes())
    assert not n.report_hidden(spam.message_id)


async def test_a_hidden_post_is_not_served():
    from unseenet.nntp import Client
    issuer, owner, spammer = (crypto.Identity.generate() for _ in range(3))
    n = node(follow_reports=follow(issuer))
    gid = group(n, owner)
    spam, ok = post(spammer, gid), post(owner, gid, "velkommen")
    for a in (spam, ok, reports_manifest(issuer), report(issuer, posts=[(spam.message_id, gid, "spam")])):
        n.accept(a.to_bytes())
    server = await n.serve("127.0.0.1", 0)
    try:
        c = await Client.connect(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
        assert await c.article(spam.message_id) is None
        assert await c.article(ok.message_id) is not None
        await c.group(gid)
        got = [await c.article(str(i)) for i in range(1, 5)]
        ids = [Article.from_bytes(g).message_id for g in got if g]
        assert ok.message_id in ids and spam.message_id not in ids
    finally:
        server.close()
