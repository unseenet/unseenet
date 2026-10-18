"""Comments in channels (UN-RFC 0030): starters begin threads, anyone may comment."""

from datetime import datetime, timedelta, timezone

import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import Manifest, check_permitted, make_manifest, manifest_article
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig

BITS = 8


def make_node() -> Node:
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))


def post(group, author, subject="News", refs=None, now=None):
    return new_article(group, subject, "Body\n", from_name="x", references=refs,
                       now=now).finalize(author, BITS)


def channel(owner, poster, **kw):
    return make_manifest(owner, "news", "channel", posters=[poster.key_text], pow_bits=BITS, **kw)


def test_manifest_fields_are_validated():
    owner = crypto.Identity.generate()
    m = Manifest.from_article(make_manifest(owner, "news", "channel", comments="open",
                                            comment_days=7, pow_bits=BITS))
    assert (m.comments, m.comment_days) == ("open", 7)
    assert Manifest.from_article(make_manifest(owner, "n2", "channel", pow_bits=BITS)).comments == "none"
    gid = make_manifest(owner, "x", "open", pow_bits=BITS).group
    with pytest.raises(ValueError):                # only for channels
        manifest_article(owner, gid, {"v": 1, "name": "x", "type": "open", "owner": owner.key_text,
                                      "serial": 1, "comments": "open"}, BITS)
    with pytest.raises(ValueError):
        make_manifest(owner, "news", "channel", comments="maybe", pow_bits=BITS)
    with pytest.raises(ValueError):
        make_manifest(owner, "news", "channel", comment_days=0, pow_bits=BITS)


def test_core_rule():
    owner, bot, reader = (crypto.Identity.generate() for _ in range(3))
    closed = Manifest.from_article(channel(owner, bot))
    opened = Manifest.from_article(channel(owner, bot, comments="open"))
    root = post(closed.group_id, bot)
    held = {root.message_id: root}
    comment = post(closed.group_id, reader, "Re: News", [root.message_id])

    with pytest.raises(ArticleError):              # comments: none, as before
        check_permitted(comment, closed, {}, thread_root=held.get)
    check_permitted(comment, opened, {}, thread_root=held.get)

    with pytest.raises(ArticleError) as e:         # nobody but starters begins a thread
        check_permitted(post(closed.group_id, reader), opened, {}, thread_root=held.get)
    assert e.value.reason == "permission"

    with pytest.raises(ArticleError) as e:         # the thread has not arrived yet
        check_permitted(comment, opened, {}, thread_root={}.get)
    assert e.value.reason == "later"

    answer = post(closed.group_id, reader, "Re: News", [root.message_id, comment.message_id])
    check_permitted(answer, opened, {}, thread_root=held.get)   # only the first reference counts

    held[comment.message_id] = comment             # a comment is not a thread root
    with pytest.raises(ArticleError) as e:
        check_permitted(post(closed.group_id, reader, "x", [comment.message_id]), opened, {},
                        thread_root=held.get)
    assert e.value.reason == "permission"


def test_comment_days():
    owner, bot, reader = (crypto.Identity.generate() for _ in range(3))
    m = Manifest.from_article(channel(owner, bot, comments="open", comment_days=3))
    then = datetime.now(timezone.utc) - timedelta(days=10)
    root = post(m.group_id, bot, now=then)
    on_time = post(m.group_id, reader, "Re", [root.message_id], now=then + timedelta(days=2))
    late = post(m.group_id, reader, "Re", [root.message_id])
    check_permitted(on_time, m, {}, thread_root={root.message_id: root}.get)
    with pytest.raises(ArticleError) as e:
        check_permitted(late, m, {}, thread_root={root.message_id: root}.get)
    assert "closed" in e.value.detail


def test_node_holds_a_comment_until_its_thread_arrives():
    node = make_node()
    owner, bot, reader = (crypto.Identity.generate() for _ in range(3))
    manifest = channel(owner, bot, comments="open")
    node.accept(manifest.to_bytes())
    root = post(manifest.group, bot)
    comment = post(manifest.group, reader, "Re: News", [root.message_id])

    with pytest.raises(ArticleError) as e:
        node.accept(comment.to_bytes(), from_peer=True)
    assert e.value.reason == "later"
    assert not node.store.seen(comment.message_id)    # so the peer can offer it again

    node.accept(root.to_bytes(), from_peer=True)      # the thread arrives ...
    assert node.store.get(comment.message_id) is not None   # ... and the comment with it


def test_node_refuses_comments_on_a_thread_that_is_gone():
    node = make_node()
    owner, bot, reader = (crypto.Identity.generate() for _ in range(3))
    manifest = channel(owner, bot, comments="open")
    node.accept(manifest.to_bytes())
    gone = post(manifest.group, bot)
    node.store.remember(gone.message_id)              # seen once, no longer stored
    with pytest.raises(ArticleError) as e:
        node.accept(post(manifest.group, reader, "Re", [gone.message_id]).to_bytes())
    assert e.value.reason == "permission"


async def test_session_comments_in_a_channel(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    from unseenet.client.session import Session, SessionError
    from unseenet.core.vault import Vault

    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", ops=1, mem=8192 * 1024),
                    status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    owner, reader = session("owner"), session("reader")
    gid = await owner.create_group("news.daily", "channel", min_pow=10)
    await owner.post(gid, "Today", "Something happened\n")
    reader.subscribe(gid)
    root = (await reader.fetch_group(gid))[0]
    assert not reader.may_post(gid) and not reader.may_reply(gid)
    with pytest.raises(SessionError):
        await reader.post(gid, "Re: Today", "Hm\n", references=[root.message_id])

    await owner.update_group(gid, comments="open", comment_days=7)
    await reader.fetch_group(gid)
    assert not reader.may_post(gid) and reader.may_reply(gid)
    await reader.post(gid, "Re: Today", "Interesting\n", references=[root.message_id])
    with pytest.raises(SessionError):                  # still no new threads
        await reader.post(gid, "My own news", "No\n")
    assert len(await owner.fetch_group(gid)) == 2

    await owner.update_group(gid, comments="none")
    assert "comments" not in owner.manifest_data(gid) and owner.manifest_data(gid)["comment_days"] == 7
    with pytest.raises(SessionError):
        open_gid = await owner.create_group("chat.x", "open", min_pow=10)
        await owner.update_group(open_gid, comments="open")
    for s in (owner, reader):
        await s.close()
    server.close()
