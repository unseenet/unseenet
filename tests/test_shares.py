"""Sharing (UN-RFC 0060): the form of a share, the node's rules and XUN-FETCH."""

import asyncio

import pytest

from unseenet.core import crypto
from unseenet.core import shares as sh
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import message_kind, make_manifest
from unseenet.core.store import Store
from unseenet.nntp import Client
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8


def make_node(**kw) -> Node:
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), **kw))


def group(node, owner, name, gtype="open", **kw):
    m = make_manifest(owner, name, gtype, pow_bits=BITS, **kw)
    node.accept(m.to_bytes())
    return m.group


def feed(node, owner):
    return group(node, owner, "feed", "channel", view="feed", comments="open")


def post(gid, author, subject="Mit marsvin hoster", body="Hvad gør jeg?\n", extra=None):
    return new_article(gid, subject, body, from_name="x", extra=extra).finalize(author, BITS)


def plain(gid, author, tgt, supersedes=None):
    return sh.build_plain(gid, tgt.message_id, tgt.group, from_name="x",
                          supersedes=supersedes).finalize(author, BITS)


def comment(gid, author, tgt, text="Se her!\n", kind="post"):
    extra = [("Message-Kind", kind), *sh.headers(tgt.message_id, tgt.group)]
    return new_article(gid, "Se her" if kind == "post" else "", text, from_name="x",
                       extra=extra).finalize(author, BITS)


def test_form():
    a, b = crypto.Identity.generate(), crypto.Identity.generate()
    node = make_node()
    g = group(node, a, "dk.snak")
    tgt = post(g, a)
    s = plain(feed(node, b), b, tgt)
    assert message_kind(s) == "share" and sh.is_plain(s) and sh.is_share(s)
    assert sh.target(s) == (tgt.message_id, g)
    assert s.body.strip() == sh.address(g, tgt.message_id) and s.body.startswith(f"unseenet:{g}?m=")
    sh.check_form(s)
    bad = sh.build_plain(s.group, tgt.message_id, g)
    bad.set("Subject", "hej")
    with pytest.raises(ArticleError, match="no subject"):
        sh.check_form(bad)
    bad = sh.build_plain(s.group, tgt.message_id, "not-a-group")
    with pytest.raises(ArticleError, match="Group ID"):
        sh.check_form(bad)
    empty = new_article(s.group, "x", "\n", extra=sh.headers(tgt.message_id, g))
    with pytest.raises(ArticleError, match="text of its own"):
        sh.check_form(empty)


def test_what_can_be_shared():
    a = crypto.Identity.generate()
    g = make_manifest(a, "dk.snak", "open", pow_bits=BITS).group
    assert sh.why_not(post(g, a)) is None
    assert sh.why_not(post(g, a, extra=[("Sharing", "no")])) == "the author asked not to share this"
    assert sh.why_not(post(g, a), {"share_from": False}) == "the author asked not to share this"
    assert sh.why_not(post(g, a), {"type": "closed"}) == "closed things are not shared"
    assert sh.share_into({}) and sh.share_into({"view": "feed"})
    assert not sh.share_into({"view": "chat"}) and sh.share_into({"view": "chat", "share_into": True})
    assert not sh.share_into({"share_into": False})
    assert sh.takes_plain({"view": "feed"}) and not sh.takes_plain({"view": "threads"})
    assert not sh.takes_plain({})
    with pytest.raises(ValueError):
        sh.check_manifest_fields({"share_into": "yes"})
    with pytest.raises(ValueError, match="true or false"):
        make_manifest(a, "dk.x", "open", pow_bits=BITS, extra={"share_from": 1})


def test_node_takes_shares_where_they_belong():
    a, b = crypto.Identity.generate(), crypto.Identity.generate()
    node = make_node()
    g = group(node, a, "dk.snak")
    tgt = post(g, a)
    node.accept(tgt.to_bytes())
    node.accept(plain(feed(node, b), b, tgt).to_bytes())           # own feed: always
    with pytest.raises(ArticleError, match="needs a comment"):    # discussion group
        node.accept(plain(g, b, tgt).to_bytes())
    node.accept(comment(g, b, tgt).to_bytes())                     # with a comment: fine
    chat = group(node, a, "dk.chat", view="chat")
    with pytest.raises(ArticleError, match="takes no shares"):     # chat: no by default
        node.accept(comment(chat, b, tgt, kind="chat").to_bytes())
    no = group(node, a, "dk.nej", view="feed", extra={"share_into": False})
    with pytest.raises(ArticleError, match="takes no shares"):
        node.accept(plain(no, b, tgt).to_bytes())
    yes = group(node, a, "dk.ja", view="feed")
    node.accept(plain(yes, b, tgt).to_bytes())                     # feeds take plain shares


def test_please_dont_share_and_three_groups():
    a, b = crypto.Identity.generate(), crypto.Identity.generate()
    node = make_node()
    g = group(node, a, "dk.snak")
    private = post(g, a, extra=[("Sharing", "no")])
    node.accept(private.to_bytes())
    with pytest.raises(ArticleError, match="asked not to share"):
        node.accept(plain(feed(node, b), b, private).to_bytes())
    tgt = post(g, a)
    node.accept(tgt.to_bytes())
    node.accept(plain(sh.own_feed(b.public_key), b, tgt).to_bytes())   # own feed: not counted
    for name in ("dk.a", "dk.b", "dk.c"):
        node.accept(plain(group(node, a, name, view="feed"), b, tgt).to_bytes())
    with pytest.raises(ArticleError, match="at most 3 groups"):
        node.accept(plain(group(node, a, "dk.d", view="feed"), b, tgt).to_bytes())
    other = crypto.Identity.generate()                             # another key may
    node.accept(plain(group(node, a, "dk.e", view="feed"), other, tgt).to_bytes())


def test_wrong_share_group_is_refused():
    a, b = crypto.Identity.generate(), crypto.Identity.generate()
    node = make_node()
    g, g2 = group(node, a, "dk.snak"), group(node, a, "dk.andet")
    tgt = post(g, a)
    node.accept(tgt.to_bytes())
    s = sh.build_plain(feed(node, b), tgt.message_id, g2, from_name="x").finalize(b, BITS)
    with pytest.raises(ArticleError, match="not the group"):
        node.accept(s.to_bytes())


async def _ask(node, mid, gid):
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    c = await Client.connect(f"127.0.0.1:{port}")
    try:
        code, text = await c.command(f"XUN-FETCH {mid} {gid}")
        raw = None
        if code == 220:
            from unseenet.nntp import read_block
            raw = await read_block(c.reader)
        return code, text, raw
    finally:
        await c.quit()
        server.close()


async def test_fetch_held_edited_and_withdrawn():
    a = crypto.Identity.generate()
    node = make_node()
    g = group(node, a, "dk.snak")
    tgt = post(g, a)
    node.accept(tgt.to_bytes())
    code, text, raw = await _ask(node, tgt.message_id, g)
    assert code == 220 and tgt.message_id in text and b"Mit marsvin" in raw
    edit = new_article(g, "Mit marsvin hoster stadig", "Nu værre\n", from_name="x",
                       extra=[("Supersedes", tgt.message_id)]).finalize(a, BITS)
    node.accept(edit.to_bytes())
    code, text, raw = await _ask(node, tgt.message_id, g)           # the newest version
    assert code == 220 and edit.message_id in text and b"stadig" in raw
    code, _, _ = await _ask(node, tgt.message_id, "dk.andet@" + g.split("@")[1])
    assert code == 430                                              # not in that group
    gone = post(g, a, subject="Væk")
    node.accept(gone.to_bytes())
    node.accept(new_article(g, None, "withdrawn\n", from_name="x",
                            extra=[("Control", f"cancel {gone.message_id}")]).finalize(a, BITS).to_bytes())
    assert (await _ask(node, gone.message_id, g))[0] == 430


async def test_fetch_from_a_peer_into_a_cache_not_the_group(monkeypatch):
    a = crypto.Identity.generate()
    far = make_node()
    g = group(far, a, "dk.snak")
    tgt = post(g, a)
    far.accept(tgt.to_bytes())
    far_server = await far.serve("127.0.0.1", 0)
    try:
        port = far_server.sockets[0].getsockname()[1]
        near = make_node()
        near.config.peers = [PeerConfig(name="far", address=f"127.0.0.1:{port}")]
        code, raw = await near.fetch_target(tgt.message_id, g)
        assert code == 220 and b"Mit marsvin" in raw
        assert near.store.get(tgt.message_id) is None                   # not in the group
        assert not near.store.seen(tgt.message_id)                      # not even seen
        code, _ = await near.fetch_target("<missing@x>", g)
        assert code == 430 and "<missing@x>" in near._fetch_misses    # remembered
        forged = post(g, crypto.Identity.generate())                   # wrong group asked
        far.accept(forged.to_bytes())
        assert (await near.fetch_target(forged.message_id,
                                        "dk.andet@" + g.split("@")[1]))[0] == 430
        near.config.fetch = False                                       # section 6.4
        assert (await near.fetch_target("<other@x>", g))[0] == 503
        assert (await near.fetch_target(tgt.message_id, g))[0] == 220   # cached still
    finally:
        far_server.close()


async def test_fetch_answers_436_while_a_peer_is_slow(monkeypatch):
    import unseenet.node.server as srv
    monkeypatch.setattr(srv, "FETCH_HOLD_SECONDS", 0.05)
    node = make_node()
    node.config.peers = [PeerConfig(name="slow", address="127.0.0.1:1")]

    async def slow(mid, gid):
        await asyncio.sleep(0.3)
        return None
    node._fetch_from_peers = slow
    gid = make_manifest(crypto.Identity.generate(), "dk.x", "open", pow_bits=BITS).group
    assert (await node.fetch_target("<a@x>", gid))[0] == 436
    await asyncio.sleep(0.4)
    assert (await node.fetch_target("<a@x>", gid))[0] == 430


# --- the Session (sections 4, 5, 6.3, 7, 8) ---

async def _sessions(tmp_path, monkeypatch, *names):
    import unseenet.client.session as sess
    from unseenet.client.session import Session
    from unseenet.core.vault import Vault
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    out = []
    for name in names:
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", ops=1, mem=8192 * 1024),
                    status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        out.append(s)
    return node, server, out


async def test_session_shares_into_feed_and_group_and_back(tmp_path, monkeypatch):
    from unseenet.client.session import SessionError
    node, server, (author, mette, soren) = await _sessions(tmp_path, monkeypatch,
                                                           "author", "mette", "soren")
    try:
        await author.ensure_inbox()
        gid = await author.create_group("dk.snak", "open", min_pow=10)
        await author.post(gid, "Mit marsvin hoster", "Hvad gør jeg?\n")
        for s in (mette, soren):
            s.subscribe(gid)
            got = await s.fetch_group(gid)
        orig = mette.find_message(gid, got[0].message_id)
        assert mette.share_permission(orig)
        assert not mette.share_into_permission(mette.personal_group("feed"))   # no feed yet
        with pytest.raises(SessionError, match="Start your feed"):
            await mette.share(orig)
        for s in (mette, soren):
            await s.start_personal_group("feed")
        sid = await mette.share(orig)                                     # plain, own feed
        cid = await soren.share(orig, "Det her er præcis det, vi talte om")
        assert mette.my_shares(orig.message_id) == {mette.personal_group("feed"): sid}
        assert not mette.share_into_permission(gid, plain=True)          # a discussion group
        other = await author.create_group("dk.dyr", "open", min_pow=10)
        mette.subscribe(other)
        await mette.fetch_group(other)
        with pytest.raises(SessionError, match="needs a comment"):
            await mette.share(orig, into=other)
        into = await mette.share(orig, "Til jer med dyr", into=other)
        dests = {d["group"]: d for d in mette.share_destinations(orig)}
        assert dests[other]["shared"] and not dests[other]["plain"]
        assert gid not in dests                                            # its own group

        # a reader who follows both feeds sees the original once, shared by Mette
        reader = author
        for s in (mette, soren):
            await reader.follow_person(s.identity().key_text)
        for g in (mette.personal_group("feed"), soren.personal_group("feed")):
            await reader.fetch_group(g)
        tl = reader.timeline()
        plain_rows = [m for m in tl if m.kind == "share"]
        assert len(plain_rows) == 1 and plain_rows[0].shared_by == ["Mette"]
        assert any(m.message_id == cid and m.share_of == orig.message_id for m in tl)
        reader.set_hide_shares(hide=True)
        assert not [m for m in reader.timeline() if m.kind == "share"]
        reader.set_hide_shares(hide=False)

        # fetching the original, checked by the client (section 6.3)
        got = await soren.fetch_share_target(orig.message_id, gid)
        assert got["state"] == "ok" and got["message"].subject == "Mit marsvin hoster"
        assert (await soren.fetch_share_target("<nope@x>", gid, patience=0))["state"] in (
            "gone", "unavailable")

        # sharing again into the same group replaces the earlier share (4.5)
        await asyncio.sleep(1.1)                                          # a new Date
        sid2 = await mette.share(orig)
        assert mette.my_shares(orig.message_id)[mette.personal_group("feed")] == sid2
        await mette.fetch_group(mette.personal_group("feed"))
        assert not any(m.message_id == sid for m in mette.cache[mette.personal_group("feed")].values())

        # notices (section 8): the author hears of it, and the check holds
        assert await mette.send_share_notice(sid2, delay=0)
        assert not await mette.send_share_notice(sid2, delay=0)           # once
        await author.fetch_group(author.my_inbox)                       # checks them too
        assert await author.check_share_notices() == 0                  # done already
        notes = author.share_notices()
        assert len(notes) == 1 and notes[0].shared_as == sid2

        assert set(await mette.unshare(orig.message_id)) == {mette.personal_group("feed"), other}
        assert mette.my_shares(orig.message_id) == {}
    finally:
        for s in (author, mette, soren):
            await s.close()
        server.close()


async def test_session_will_not_share_what_asks_not_to_be(tmp_path, monkeypatch):
    node, server, (author, reader) = await _sessions(tmp_path, monkeypatch, "author", "reader")
    try:
        gid = await author.create_group("dk.snak", "open", min_pow=10)
        await author.post(gid, "Kun her", "Del ikke\n", extra=[("Sharing", "no")])
        reader.subscribe(gid)
        msg = (await reader.fetch_group(gid))[0]
        p = reader.share_permission(msg)
        assert not p and p.code == "asked_not"
        d = msg.to_dict()
        assert d["sharing"] == "no" and d["share"] is None
    finally:
        for s in (author, reader):
            await s.close()
        server.close()


@pytest.fixture(autouse=True)
def _history_dates(monkeypatch):
    from datetime import timedelta
    from unseenet.node import server as node_server
    monkeypatch.setattr(node_server, "POST_PAST", timedelta(days=3650))
