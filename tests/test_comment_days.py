"""UN-RFC 0030 amendment (#732): an entry's own time for comments, closing and opening
comments on one entry, and comment_days in every group but inboxes and local groups."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session, SessionError
from unseenet.core import comments as cm
from unseenet.core.article import ArticleError
from unseenet.core.groups import Manifest, make_manifest, _comments
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def start_node():
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    return node, server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def session(tmp_path, name, node):
    s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity(name, name.title())
    s.add_node(node)
    return s


def test_comment_days_in_every_group_but_inboxes_and_local():
    for t in ("open", "moderated", "closed", "channel"):
        assert _comments({"type": t, "comment_days": 7}) == ("none", 7)
    for bad in ({"type": "inbox", "comment_days": 7},
                {"type": "open", "local": True, "comment_days": 7},
                {"type": "open", "comments": "open"},
                {"type": "open", "comment_days": 0}):
        with pytest.raises(ValueError):
            _comments(bad)


def test_parse_days_and_the_shorter_deadline():
    assert cm.parse_days("0") == 0 and cm.parse_days(" 14 ") == 14
    for bad in ("-1", "1.5", "x", "", "007"):
        with pytest.raises(ValueError):
            cm.parse_days(bad)
    assert cm.shorter(None, 5, 3) == 3 and cm.shorter(None, None) is None


async def test_an_entrys_own_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, srv, addr = await start_node()
    owner, reader = session(tmp_path, "owner", addr), session(tmp_path, "reader", addr)
    try:
        gid = await owner.create_group("dk.snak", "open", min_pow=8, comment_days=10)
        assert owner.manifest_data(gid)["comment_days"] == 10
        with pytest.raises(SessionError, match="at most"):
            await owner.post(gid, "for længe", "x\n", comment_days=11)
        quiet = await owner.post(gid, "ingen svar", "Bare læs\n", comment_days=0)
        talk = await owner.post(gid, "snak løs", "Svar gerne\n")
        reader.subscribe(gid)
        msgs = {m.message_id: m for m in await reader.fetch_group(gid)}
        assert msgs[quiet].comment_days == 0 and msgs[talk].comment_days is None
        p = reader.write_permission(gid, reply_to=msgs[quiet])
        assert not p.allowed and p.code == "comments_closed"
        assert reader.write_permission(gid, reply_to=msgs[talk]).allowed
        await reader.post(gid, "Re: snak løs", "Ja\n", references=[talk])
        with pytest.raises(SessionError, match="closed"):          # the node says no too
            await reader._send_article(_reply(reader, gid, quiet))
        assert reader.comments_state(gid, talk)["until"] is not None   # the group's 10 days
    finally:
        for s in (owner, reader):
            await s.close()
        srv.close()


def _reply(s, gid, root):
    from unseenet.core.article import new_article
    art = new_article(gid, "Re: x", "y\n", references=[root], from_name="Reader",
                      extra=[("Message-Kind", "post"), ("Content-Type", "text/plain")])
    return art.finalize(s.identity(), 8)


async def test_close_and_open_two_chains(tmp_path, monkeypatch):
    """The author closes and opens their own entry; an owner's close the author cannot
    open; a reader cannot close at all (section 3.2)."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, srv, addr = await start_node()
    owner, author, reader = (session(tmp_path, n, addr) for n in ("owner", "author", "reader"))
    try:
        gid = await owner.create_group("dk.debat", "open", min_pow=8)
        for s in (author, reader):
            s.subscribe(gid)
        await author.fetch_group(gid)
        root = await author.post(gid, "Mit indlæg", "Hvad synes I?\n")
        await author.close_comments(gid, root, "Nok for nu")
        await reader.fetch_group(gid)
        p = reader.write_permission(gid, reply_to=reader.find_message(gid, root))
        assert not p.allowed and "Nok for nu" in p.reason
        with pytest.raises(SessionError, match="closed"):
            await reader._send_article(_reply(reader, gid, root))
        assert not reader.may_close_comments(gid, root)
        with pytest.raises(SessionError, match="author, the owner or a moderator"):
            await reader.close_comments(gid, root)

        await author.close_comments(gid, root, reopen=True)
        await reader.fetch_group(gid)
        assert reader.comments_state(gid, root)["open"]
        await reader.post(gid, "Re: Mit indlæg", "Godt\n", references=[root])

        await owner.fetch_group(gid)
        await owner.close_comments(gid, root, "Lukket af ejeren")
        await author.fetch_group(gid)
        with pytest.raises(SessionError, match="only they can open it"):
            await author.close_comments(gid, root, reopen=True)
        # an open the author signs anyway does not open what the owner closed
        art = cm.marker_article(author.identity(), gid, root, close=False, pow_bits=8)
        await author._send_article(art)
        with pytest.raises(SessionError, match="closed"):
            await reader._send_article(_reply(reader, gid, root))
        await owner.close_comments(gid, root, reopen=True)
        await reader.fetch_group(gid)
        assert reader.comments_state(gid, root)["open"]
    finally:
        for s in (owner, author, reader):
            await s.close()
        srv.close()


async def test_markers_are_checked_by_the_node(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, srv, addr = await start_node()
    owner, reader = session(tmp_path, "owner", addr), session(tmp_path, "reader", addr)
    try:
        gid = await owner.create_group("dk.x", "open", min_pow=8)
        root = await owner.post(gid, "Emne", "Tekst\n")
        reply = await owner.post(gid, "Re: Emne", "Svar\n", references=[root])
        with pytest.raises(SessionError, match="thread root"):      # not on a reply
            await owner._send_article(cm.marker_article(owner.identity(), gid, reply,
                                                        close=True, pow_bits=8))
        with pytest.raises(SessionError, match="author, the owner or a moderator"):
            await reader._send_article(cm.marker_article(reader.identity(), gid, root,
                                                         close=True, pow_bits=8))
        with pytest.raises(SessionError, match="not on this node yet"):
            await owner._send_article(cm.marker_article(owner.identity(), gid, "<nope@x>",
                                                        close=True, pow_bits=8))
        with pytest.raises(ValueError):
            cm.marker_article(owner.identity(), gid, root, close=True, note="x" * 300)
    finally:
        for s in (owner, reader):
            await s.close()
        srv.close()


async def test_a_marker_before_its_entry_comes_later(tmp_path, monkeypatch):
    """Replication order: a node that gets the close before the entry answers 'later'
    (section 4.1), and takes it once the entry is there."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    n1, s1, a1 = await start_node()
    n2, s2, a2 = await start_node()
    owner = session(tmp_path, "owner", a1)
    try:
        gid = await owner.create_group("dk.y", "open", min_pow=8)
        root = await owner.post(gid, "Emne", "Tekst\n")
        mid = await owner.close_comments(gid, root, "Lukket")
        raw = {m: n1.store.get(m) for m in (root, mid)}
        n2.accept(n1.store.get(n1.store.manifest(gid).message_id), source="peer")
        with pytest.raises(ArticleError) as exc:
            n2.accept(raw[mid], source=None)
        assert exc.value.reason == "later"
        n2.accept(raw[root], source=None)
        n2.accept(raw[mid], source=None)
        assert n2.store.comments_closed(gid, root, owner.identity().key_text) is not None
    finally:
        await owner.close()
        s1.close()
        s2.close()


async def test_an_edit_shortens_never_lengthens(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, srv, addr = await start_node()
    owner = session(tmp_path, "owner", addr)
    try:
        gid = await owner.create_group("dk.z", "open", min_pow=8, comment_days=30)
        root = await owner.post(gid, "Emne", "Tekst\n", comment_days=10)
        await owner.fetch_group(gid)
        msg = owner.find_message(gid, root)
        with pytest.raises(SessionError, match="not lengthen"):
            await owner.edit(msg, "Emne", "Tekst 2\n", comment_days=20)
        await owner.edit(msg, "Emne", "Tekst 2\n", comment_days=3)
        assert node.store.root_days(root) == 3
        await owner.fetch_group(gid)
        assert owner.comments_state(gid, root)["own_days"] == 3
    finally:
        await owner.close()
        srv.close()


def test_manifest_with_comment_days_in_an_open_group(tmp_path):
    from unseenet.core import crypto
    me = crypto.Identity.generate()
    art = make_manifest(me, "dk.a", "open", comment_days=14, pow_bits=0)
    assert Manifest.from_article(art).comment_days == 14


async def test_local_api_comments(tmp_path, monkeypatch):
    """Section 4.24 of UN-RFC 0046: a row's comments state and who may close, and
    closing and opening through the API."""
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from test_localapi_owner import _setup
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    try:
        gid = (await api.create_group({"name": "dk.api", "type": "open",
                                       "comment_days": 14}))["id"]
        assert owner.manifest_data(gid).get("comment_days") == 14
        mid = await owner.post(gid, "Emne", "Tekst\n", comment_days=2)
        await owner.fetch_group(gid)
        row = next(r for r in api.group(gid)["rows"] if r["message"]["id"] == mid)
        assert row["comments"]["open"] and row["comments"]["own_days"] == 2
        assert row["may_close_comments"] is True
        done = await api.comments(gid, {"id": mid, "note": "Slut"})
        assert done["ok"] and done["comments"]["reason"] == "closed"
        assert done["comments"]["note"] == "Slut"
        done = await api.comments(gid, {"id": mid, "close": False})
        assert done["comments"]["open"]
        with pytest.raises(SessionError):
            await api.comments(gid, {"id": ""})
        with pytest.raises(SessionError):
            await api.comments(gid, {"id": mid, "close": "ja"})
    finally:
        await owner.close()
        await other.close()
        server.close()


async def test_cli_comments(tmp_path, monkeypatch, capsys):
    import json
    from argparse import Namespace
    from unseenet import cli
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(cli, "DEFAULT_POW", 8)
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, srv, addr = await start_node()
    a = cli.App(Vault.open(tmp_path / "me.vault", "pw", **KDF))
    a.data["nodes"].append(addr)
    await cli.c_id_new(a, Namespace(name="me", display=None))

    def args(**kw):
        base = dict(identity=None, json=True, subject=None, body="Tekst\n", kind="post",
                    reply_to=None, edit=None, format=None, attach=None, publish_outside_tor=False,
                    local=False, moderator=None, poster=None, title=None, description=None,
                    min_pow=8, retention_days=None, view=None, kinds=None, charter=None,
                    comments=None, comment_days=None, attachments=None, types=None,
                    max_pins=None, max_pages=None, home=None, note=None, yes=True)
        return Namespace(**(base | kw))

    def out():
        return json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    try:
        await cli.c_group_create(a, args(name="dk.cli", type="open", comment_days=7))
        gid = out()["group"]
        await cli.c_post(a, args(group=gid, subject="Emne", comment_days=3))
        mid = out()["message_id"]
        await cli.c_comments(a, args(cmd="comments-close", group=gid, message_id=mid, note="Nu"))
        assert out()["open"] is False
        await cli.c_comments(a, args(cmd="comments-open", group=gid, message_id=mid))
        assert out()["open"] is True
        with pytest.raises(SystemExit, match="at most"):
            await cli.c_post(a, args(group=gid, subject="For længe", comment_days=8))
    finally:
        if a._session is not None:
            await a._session.close()
        srv.close()
