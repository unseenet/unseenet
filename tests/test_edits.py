"""UN-RFC 0042: editing posts with Supersedes."""

from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Message, Session, SessionError, resolve_edits
from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import MAX_SUPERSEDES, make_manifest, parse_supersedes
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8


def node(**kw) -> Node:
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), **kw))


def group(n: Node, owner, gtype="open", **kw):
    m = make_manifest(owner, "dk.snak", gtype, pow_bits=BITS, **kw)
    n.accept(m.to_bytes())
    return m.group


def post(who, gid, body, subject="Hej", supersedes=None, references=None, kind="post",
         date=None):
    extra = [("Message-Kind", kind)]
    if supersedes:
        extra.append(("Supersedes", " ".join(supersedes)))
    art = new_article(gid, "" if kind == "chat" else subject, body, from_name="x",
                      references=references, extra=extra)
    if date is not None:
        art.set("Date", date)
    return art.finalize(who, BITS)


# --- the header ----------------------------------------------------------------

def test_supersedes_is_checked():
    me = crypto.Identity.generate()
    assert parse_supersedes(post(me, "g@x", "a")) == []
    assert parse_supersedes(post(me, "g@x", "a", supersedes=["<b@x>", "<a@x>"])) == ["<b@x>", "<a@x>"]
    for bad in (["b@x"], ["<a@x>", "<a@x>"], [f"<{i}@x>" for i in range(MAX_SUPERSEDES + 1)]):
        with pytest.raises(ArticleError):
            parse_supersedes(post(me, "g@x", "a", supersedes=bad))


# --- nodes ---------------------------------------------------------------------

def test_node_withdraws_the_earlier_version():
    n, me = node(), crypto.Identity.generate()
    gid = group(n, me)
    v1 = post(me, gid, "tekst med fjel")
    n.accept(v1.to_bytes())
    v2 = post(me, gid, "tekst med fejl rettet", supersedes=[v1.message_id])
    n.accept(v2.to_bytes())
    assert n.store.get(v1.message_id) is None and n.store.get(v2.message_id) is not None
    with pytest.raises(ArticleError, match="duplicate"):        # never back again
        n.accept(v1.to_bytes())


def test_only_the_author_edits_and_kind_and_place_stay():
    n, me, other = node(), crypto.Identity.generate(), crypto.Identity.generate()
    gid = group(n, me)
    root = post(me, gid, "root")
    n.accept(root.to_bytes())
    v1 = post(me, gid, "svar", references=[root.message_id])
    n.accept(v1.to_bytes())
    for art, why in ((post(other, gid, "ha", supersedes=[v1.message_id],
                           references=[root.message_id]), "author"),
                     (post(me, gid, "x", supersedes=[v1.message_id], references=[root.message_id],
                           kind="chat"), "kind"),
                     (post(me, gid, "x", supersedes=[v1.message_id]), "place in its thread")):
        with pytest.raises(ArticleError, match=why):
            n.accept(art.to_bytes())
    assert n.store.get(v1.message_id) is not None


def test_edits_out_of_order_and_chains():
    n, me = node(), crypto.Identity.generate()
    gid = group(n, me)
    v1 = post(me, gid, "1")
    v2 = post(me, gid, "2", supersedes=[v1.message_id])
    v3 = post(me, gid, "3", supersedes=[v2.message_id, v1.message_id])
    n.accept(v3.to_bytes())                                     # the newest first
    for old in (v1, v2):
        with pytest.raises(ArticleError, match="replaced by an edit"):
            n.accept(old.to_bytes())
    assert n.store.get(v3.message_id) is not None


def test_a_forged_pending_edit_does_not_hide_someone_elses_post():
    n, me, troll = node(), crypto.Identity.generate(), crypto.Identity.generate()
    gid = group(n, me)
    mine = post(me, gid, "mit indlæg")
    n.accept(post(troll, gid, "ha", supersedes=[mine.message_id]).to_bytes())
    n.accept(mine.to_bytes())                                   # still taken
    assert n.store.get(mine.message_id) is not None


def test_private_posts_cannot_be_edited():
    from unseenet.core.groups import inbox_article
    n, owner, sender = node(), crypto.Identity.generate(), crypto.Identity.generate()
    inbox = make_manifest(owner, "inbox", "inbox", pow_bits=BITS)
    n.accept(inbox.to_bytes())
    sealed = inbox_article(inbox.group, owner.public_key, from_name="s", subject="hej", body="b",
                           sender=sender, pow_bits=BITS)
    n.accept(sealed.to_bytes())
    art = post(sender, inbox.group, "b", supersedes=[sealed.message_id])   # outer header
    with pytest.raises(ArticleError, match="private posts"):
        n.accept(art.to_bytes())
    assert n.store.get(sealed.message_id) is not None


def test_editing_a_channel_root_does_not_reopen_comments():
    n, owner, reader = node(), crypto.Identity.generate(), crypto.Identity.generate()
    gid = group(n, owner, "channel", comments="open", comment_days=1)
    old_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    root = post(owner, gid, "nyhed", date=old_date)
    n.accept(root.to_bytes())
    edit = post(owner, gid, "nyhed, rettet", supersedes=[root.message_id])
    n.accept(edit.to_bytes())
    for ref in (root.message_id, edit.message_id):              # whichever version they saw
        with pytest.raises(ArticleError, match="closed"):
            n.accept(post(reader, gid, "sent svar", references=[ref]).to_bytes())


def test_comment_on_an_edited_root_that_is_open():
    n, owner, reader = node(), crypto.Identity.generate(), crypto.Identity.generate()
    gid = group(n, owner, "channel", comments="open", comment_days=7)
    root = post(owner, gid, "nyhed")
    n.accept(root.to_bytes())
    n.accept(post(owner, gid, "nyhed, rettet", supersedes=[root.message_id]).to_bytes())
    n.accept(post(reader, gid, "svar", references=[root.message_id]).to_bytes())


# --- clients -------------------------------------------------------------------

def msg(n, mid, body, author="me", refs=(), sup=(), minutes=0, kind="post"):
    return Message(n, mid, "g@x", author_key=author, body=body, references=list(refs),
                   supersedes=list(sup), kind=kind,
                   date=datetime(2026, 10, 19, 20, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes))


def test_newest_version_in_the_first_ones_place_with_replies_under_it():
    v1 = msg(1, "<v1>", "fjel")
    reply = msg(2, "<r>", "svar", author="you", refs=["<v1>"])
    v2 = msg(3, "<v2>", "fejl", sup=["<v1>"], minutes=5)
    v3 = msg(4, "<v3>", "rettet", sup=["<v2>", "<v1>"], minutes=9)
    shown = resolve_edits([v1, reply, v2, v3])
    assert [m.message_id for m in shown] == ["<v3>", "<r>"]
    top = shown[0]
    assert top.number == 1 and top.body == "rettet" and top.edited == v3.date
    assert top.date == v1.date and top.versions[-1] == "<v1>" and set(top.versions) == {"<v1>", "<v2>"}
    assert shown[1].references == ["<v3>"] and reply.references == ["<v1>"]   # copies


def test_client_ignores_an_edit_by_someone_else():
    v1 = msg(1, "<v1>", "mit")
    forged = msg(2, "<f>", "ha", author="troll", sup=["<v1>"])
    assert [m.message_id for m in resolve_edits([v1, forged])] == ["<v1>", "<f>"]


def test_two_edits_at_once_the_later_wins():
    v1 = msg(1, "<v1>", "a")
    a = msg(2, "<a>", "fra telefon", sup=["<v1>"], minutes=1)
    b = msg(3, "<b>", "fra pc", sup=["<v1>"], minutes=2)
    [shown] = resolve_edits([v1, a, b])
    assert shown.message_id == "<b>" and "<a>" in shown.versions


@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    n = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await n.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    made = []

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", ops=1, mem=8192 * 1024),
                    status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        made.append(s)
        return s
    yield session
    for s in made:
        await s.close()
    server.close()


async def test_session_edit_twice_then_withdraw(net):
    me, reader = net("me"), net("reader")
    gid = await me.create_group("dk.snak", "open", min_pow=10)
    await me.post(gid, "Hej", "Første udgave\n")
    reader.subscribe(gid)
    [first] = reader.visible(await reader.fetch_group(gid))
    reader.mark_read(first)
    await reader.post(gid, "Re: Hej", "Svar\n", references=[first.message_id])

    shown = me.visible(await me.fetch_group(gid))
    assert not me.may_edit(next(m for m in shown if m.subject == "Re: Hej"))   # not mine
    v1 = next(m for m in shown if m.subject == "Hej")
    assert me.may_edit(v1)
    await me.edit(v1, "Hej", "Anden udgave\n")
    shown = me.visible(await me.fetch_group(gid))
    v2 = next(m for m in shown if m.subject == "Hej")
    assert v2.body.startswith("Anden") and v2.edited and v2.versions == [first.message_id]
    await me.edit(v2, "Hej igen", "Tredje udgave\n")

    seen = reader.visible(await reader.fetch_group(gid))
    assert [m.subject for m in seen] == ["Hej igen", "Re: Hej"]      # in the first one's place
    top, reply = seen
    assert top.body.startswith("Tredje") and len(top.versions) == 2
    assert reply.references == [top.message_id]                       # under the newest
    assert reader.is_read(top)                                        # read before: still read

    with pytest.raises(SessionError, match="own"):
        await reader.edit(top, "x", "y\n")
    await me.cancel(top)                                              # withdraws the post
    assert [m.subject for m in reader.visible(await reader.fetch_group(gid))] == ["Re: Hej"]


async def test_session_edit_a_chat_line(net):
    me = net("me")
    gid = await me.create_group("dk.snak", "open", min_pow=10, view="chat")
    await me.post(gid, "", "hej allesammen, hvordan gåt det\n", kind="chat")
    [line] = me.visible(await me.fetch_group(gid))
    await me.edit(line, "", "hej allesammen, hvordan går det\n")
    [line] = me.visible(await me.fetch_group(gid))
    assert line.kind == "chat" and "går" in line.body and line.edited
