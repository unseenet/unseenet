"""Reactions (UN-RFC 0048): one emoji under an article, one per key."""

from datetime import datetime, timedelta, timezone

import pytest

from unseenet.core import crypto
from unseenet.core import reactions as rx
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import Manifest, make_manifest, message_kind
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig

BITS = 8


def make_node() -> Node:
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))


def post(group, author, subject="News", refs=None, now=None):
    return new_article(group, subject, "Body\n", from_name="x", references=refs,
                       now=now).finalize(author, BITS)


def react(group, author, target, emoji="👍", refs=(), supersedes=None, now=None):
    art = rx.build(group, list(refs), target.message_id if hasattr(target, "message_id")
                   else target, emoji, from_name="x", supersedes=supersedes)
    if now is not None:
        art.set("Date", new_article(group, "", "", now=now)["Date"])
    return art.finalize(author, BITS)


def test_emoji():
    for ok in ("👍", "👎", "❤️", "❤", "😂", "🇩🇰", "👍🏽", "🧑‍🚀", "1️⃣"):
        assert rx.is_emoji(ok), ok
    for bad in ("", "x", ":+1:", "👍👍", "+", "ab", "👍🏽🏽"):
        assert not rx.is_emoji(bad), bad
    assert rx.same_emoji("❤️", "❤")


def test_reaction_set_and_defaults():
    assert rx.reaction_set({"view": "feed"}).emoji == rx.DEFAULT_SET
    assert rx.reaction_set({"view": "chat"}).takes("👎")
    assert not rx.reaction_set({"view": "threads"})
    assert not rx.reaction_set({})
    assert rx.reaction_set({"reactions": "any"}).takes("🦫")
    assert not rx.reaction_set({"view": "feed", "reactions": []})
    assert rx.reaction_set({"type": "inbox"}).any
    s = rx.reaction_set({"reactions": ["🎉", "❤"]})
    assert s.takes("❤️") and not s.takes("👍")
    for bad in ([":tada:"], ["👍", "👍"], ["x"], ["👍"] * 13, "all", 3):
        with pytest.raises(ValueError):
            rx.check_field({"reactions": bad})
    with pytest.raises(ValueError):
        rx.check_field({"view": "data", "reactions": []})


def test_manifest_carries_reactions():
    owner = crypto.Identity.generate()
    art = make_manifest(owner, "talk", "open", view="feed", pow_bits=BITS,
                        extra={"reactions": ["🎉"]})
    assert Manifest.from_article(art).raw["reactions"] == ["🎉"]
    with pytest.raises(ValueError):
        make_manifest(owner, "talk", "open", pow_bits=BITS, extra={"reactions": ["nope"]})


def test_form():
    owner, reader = crypto.Identity.generate(), crypto.Identity.generate()
    gid = make_manifest(owner, "t", "open", pow_bits=BITS).group
    root = post(gid, owner)
    r = react(gid, reader, root)
    assert message_kind(r) == "reaction" and rx.target(r) == root.message_id
    assert rx.check_form(r) == "👍"
    bad = rx.build(gid, [], root.message_id, "👍")
    bad.set("Subject", "hi")
    with pytest.raises(ArticleError):
        rx.check_form(bad)
    with pytest.raises(ValueError):
        rx.build(gid, [], root.message_id, "hej")


def test_count_one_per_key_latest_wins():
    items = [("<1@x>", "A", 10, "<t@x>", "👍"), ("<2@x>", "B", 11, "<t@x>", "👍"),
             ("<3@x>", "A", 12, "<t@x>", "❤"), ("<4@x>", "C", 5, "<u@x>", "😂"),
             ("<5@x>", "B", 11, "<t@x>", "nope")]
    c = rx.count(items)
    t = c["<t@x>"]
    assert t.total() == 2 and t.count("👍") == 1 and t.count("❤️") == 1
    assert t.of("A") == "❤️" and t.by_key["A"][1] == "<3@x>"
    assert c["<u@x>"].count("😂") == 1


# --- the node (section 6) ---

def feed(node, owner, poster=None, gtype="channel", **kw):
    m = make_manifest(owner, "news", gtype, view=kw.pop("view", "feed"), pow_bits=BITS,
                      posters=[poster.key_text] if poster else (), **kw)
    node.accept(m.to_bytes())
    return m.group


def test_node_takes_reactions_on_entries_and_comments():
    node = make_node()
    owner, reader, other = (crypto.Identity.generate() for _ in range(3))
    gid = feed(node, owner, comments="open")
    root = post(gid, owner)
    node.accept(root.to_bytes())
    comment = post(gid, other, "", [root.message_id])
    node.accept(comment.to_bytes())

    node.accept(react(gid, reader, root).to_bytes())                       # an entry
    node.accept(react(gid, reader, comment, "😂", [root.message_id]).to_bytes())   # a comment

    with pytest.raises(ArticleError) as e:                      # not in the default set
        node.accept(react(gid, other, root, "🦫").to_bytes())
    assert e.value.reason == "permission"


def test_channel_without_comments_takes_reactions():
    node = make_node()
    owner, reader = crypto.Identity.generate(), crypto.Identity.generate()
    gid = feed(node, owner)                                     # comments: none
    root = post(gid, owner)
    node.accept(root.to_bytes())
    node.accept(react(gid, reader, root).to_bytes())
    with pytest.raises(ArticleError):
        node.accept(post(gid, reader, "Re", [root.message_id]).to_bytes())


def test_threads_take_none_unless_the_owner_says_so():
    node = make_node()
    owner, reader = crypto.Identity.generate(), crypto.Identity.generate()
    gid = feed(node, owner, gtype="open", view="threads")
    root = post(gid, owner)
    node.accept(root.to_bytes())
    with pytest.raises(ArticleError):
        node.accept(react(gid, reader, root).to_bytes())
    node2 = make_node()
    gid2 = feed(node2, owner, gtype="open", view="threads", extra={"reactions": "any"})
    root2 = post(gid2, owner)
    node2.accept(root2.to_bytes())
    node2.accept(react(gid2, reader, root2, "🦫").to_bytes())


def test_one_per_key_change_and_take_back():
    node = make_node()
    owner, reader = crypto.Identity.generate(), crypto.Identity.generate()
    gid = feed(node, owner)
    root = post(gid, owner)
    node.accept(root.to_bytes())
    first = react(gid, reader, root)
    node.accept(first.to_bytes())
    with pytest.raises(ArticleError) as e:                      # a second one
        node.accept(react(gid, reader, root, "❤️").to_bytes())
    assert "Supersedes" in e.value.detail
    change = react(gid, reader, root, "❤️", supersedes=first.message_id)
    node.accept(change.to_bytes())
    assert node.store.get(first.message_id) is None             # withdrawn by the edit
    assert node.store.reaction_by(root.message_id, reader.key_text) == change.message_id


def test_reactions_wait_for_their_article_and_go_with_it():
    node = make_node()
    owner, reader, other = (crypto.Identity.generate() for _ in range(3))
    gid = feed(node, owner, comments="open")
    root = post(gid, owner)
    node.accept(root.to_bytes())
    comment = post(gid, other, "", [root.message_id])
    r = react(gid, reader, comment, refs=[root.message_id])
    with pytest.raises(ArticleError) as e:
        node.accept(r.to_bytes(), from_peer=True)
    assert e.value.reason == "later"
    node.accept(comment.to_bytes(), from_peer=True)             # the comment arrives ...
    assert node.store.get(r.message_id) is not None             # ... and its reaction with it

    node.store.delete(comment.message_id)                       # the comment goes ...
    node.store.drop_orphan_reactions()
    assert node.store.get(r.message_id) is None                 # ... and so does the reaction


def test_no_reactions_to_reactions_or_other_groups():
    node = make_node()
    owner, reader = crypto.Identity.generate(), crypto.Identity.generate()
    gid = feed(node, owner)
    root = post(gid, owner)
    node.accept(root.to_bytes())
    r = react(gid, reader, root)
    node.accept(r.to_bytes())
    with pytest.raises(ArticleError):
        node.accept(react(gid, owner, r, refs=[root.message_id]).to_bytes())


def test_comment_days_close_reactions():
    node = make_node()
    owner, reader = crypto.Identity.generate(), crypto.Identity.generate()
    gid = feed(node, owner, comments="open", comment_days=3)
    then = datetime.now(timezone.utc) - timedelta(days=10)
    root = post(gid, owner, now=then)
    node.accept(root.to_bytes())
    with pytest.raises(ArticleError) as e:
        node.accept(react(gid, reader, root).to_bytes())
    assert "closed" in e.value.detail



# --- the Session (sections 5 and 7) ---

async def test_session_reacts_counts_changes_and_takes_back(tmp_path, monkeypatch):
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

    owner, reader, other = session("owner"), session("reader"), session("other")
    gid = await owner.create_group("news.daily", "channel", min_pow=10, view="feed",
                                   comments="open")
    await owner.post(gid, "Today", "Something happened\n")
    for s in (reader, other):
        s.subscribe(gid)
    entry = (await reader.fetch_group(gid))[0]
    await other.fetch_group(gid)
    assert reader.react_permission(gid, entry)               # a channel: no comment needed
    assert reader.reaction_set(gid).offered == rx.DEFAULT_SET

    await reader.react(entry, "👍")
    await other.react(other.find_message(gid, entry.message_id), "👍")
    await owner.fetch_group(gid)
    shown = owner.find_message(gid, entry.message_id)
    c = owner.reactions_on(shown)
    assert c.count("👍") == 2 and c.total() == 2
    assert len(owner.cache[gid]) == 1                        # never shown as posts

    # a comment can be reacted to as well
    cid = await reader.post(gid, "", "Wow\n", references=[entry.message_id], kind="chat")
    await owner.fetch_group(gid)
    comment = owner.find_message(gid, cid)
    await owner.react(comment, "❤️")
    await reader.fetch_group(gid)
    assert reader.reactions_on(reader.find_message(gid, cid)).count("❤") == 1

    await reader.react(entry, "😂")                          # change ...
    await owner.fetch_group(gid)
    c = owner.reactions_on(shown)
    assert c.count("👍") == 1 and c.count("😂") == 1 and c.total() == 2

    assert await reader.react(entry, "😂") is None           # ... and take back
    await owner.fetch_group(gid)
    c = owner.reactions_on(shown)
    assert c.total() == 1 and c.of(reader.identity().key_text) is None

    with pytest.raises(SessionError):                        # not in the set
        await reader.react(entry, "🦫")
    await owner.update_group(gid, reactions=[])
    await reader.fetch_group(gid)
    assert not reader.react_permission(gid, entry)
    for s in (owner, reader, other):
        await s.close()
    server.close()


async def test_reactions_in_a_closed_group(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    from unseenet.client.session import Session
    from unseenet.core.vault import Vault

    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    s = Session(Vault.open(tmp_path / "o.vault", "pw", ops=1, mem=8192 * 1024),
                status=lambda *_: None)
    s.new_identity("o", "O")
    s.add_node(addr)
    gid = await s.create_group("friends", "closed", min_pow=10, view="feed")
    await s.post(gid, "Hi", "there\n")
    msg = next(m for m in (await s.fetch_group(gid)) if m.subject == "Hi")
    assert s.react_permission(gid, msg).code == "own"           # not your own (#524)
    m = Session(Vault.open(tmp_path / "m.vault", "pw", ops=1, mem=8192 * 1024),
                status=lambda *_: None)
    m.new_identity("m", "M")
    m.add_node(addr)
    await s.invite(gid, m.identity().key_text)
    seen = next(x for x in (await m.fetch_group(gid)) if x.subject == "Hi")
    await m.react(seen, "👍")
    await m.close()
    s.reaction_msgs.clear()
    s.cache.clear()
    s._high.clear()
    await s.fetch_group(gid)
    msg = next(m for m in s.cache[gid].values() if m.subject == "Hi")
    assert s.reactions_on(msg).count("👍") == 1
    assert all(m.kind != "reaction" for m in s.cache[gid].values())
    await s.close()
    server.close()


def test_cli_reaction_options():
    from types import SimpleNamespace
    from unseenet.cli import _group_fields
    for given, want in (("default", None), ("none", []), ("any", "any"), ("🎉, ❤️", ["🎉", "❤️"])):
        _, extra = _group_fields(SimpleNamespace(reactions=given))
        assert extra["reactions"] == want
    assert "reactions" not in _group_fields(SimpleNamespace())[1]
