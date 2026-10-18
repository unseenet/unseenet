"""UN-RFC 0028: chats and posts in private messages."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.article import Article
from unseenet.core.groups import (KIND_CHAT, KIND_POST, inbox_article, message_kind,
                                  open_inbox_article, personal_inbox_id)
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}


def test_kind_is_sealed_and_signed():
    owner, sender = crypto.Identity.generate(), crypto.Identity.generate()
    gid = personal_inbox_id(owner.public_key)
    chat = inbox_article(gid, owner.public_key, from_name="Sonia", subject="ignored",
                         body="hej\n", sender=sender, kind=KIND_CHAT, pow_bits=BITS)
    assert b"Message-Kind" not in chat.to_bytes()       # a node cannot tell
    inner, who = open_inbox_article(chat, owner)
    assert who == sender.public_key                     # the kind is under the sender's signature
    assert message_kind(inner) == KIND_CHAT and inner["Subject"] == ""

    letter = inbox_article(gid, owner.public_key, from_name="Sonia", subject="Om weekenden",
                           body="Kære far\n", sender=sender, pow_bits=BITS)
    inner, _ = open_inbox_article(letter, owner)
    assert message_kind(inner) == KIND_POST and inner["Subject"] == "Om weekenden"


def test_missing_or_unknown_kind_is_a_post():
    assert message_kind(Article([("Subject", "x")], "")) == KIND_POST
    assert message_kind(Article([("Message-Kind", "postcard")], "")) == KIND_POST
    assert message_kind(Article([("Message-Kind", " Chat ")], "")) == KIND_CHAT
    owner = crypto.Identity.generate()
    with pytest.raises(ValueError):
        inbox_article(personal_inbox_id(owner.public_key), owner.public_key, from_name="x",
                      subject="s", body="b", kind="postcard", pow_bits=BITS)


async def test_chats_and_posts_apart(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    a, b = session("andreas"), session("sonia")
    await a.ensure_inbox(); await b.ensure_inbox()
    a_key, b_key = a.identity().key_text, b.identity().key_text
    b_pk = b.identity().public_key

    await b.send_private(a.my_inbox, "", "hej far\n", kind=KIND_CHAT)
    await b.send_private(a.my_inbox, "Om weekenden", "Kære far\n")
    await a.fetch_group(a.my_inbox)
    assert a.unread_from(b_key, KIND_CHAT) == 1 and a.unread_from(b_key, KIND_POST) == 1
    assert a.unread_private(KIND_POST) == 1

    await a.send_private(personal_inbox_id(b_pk), "would be dropped", "hej skat\n",
                         owner_key=b_pk, kind=KIND_CHAT)
    await a.send_private(personal_inbox_id(b_pk), "Re: Om weekenden", "> Kære far\nJa!\n",
                         owner_key=b_pk)
    assert [m.body for m in a.conversation(b_key, KIND_CHAT)] == ["hej far\n", "hej skat\n"]
    assert [m.subject for m in a.private_messages(KIND_POST)] == ["Om weekenden", "Re: Om weekenden"]
    assert all(m.subject == "" for m in a.conversation(b_key, KIND_CHAT))
    assert len(a.conversation(b_key)) == 4              # no kind: both

    # your own copies keep their kind across a restart
    await a.close()
    again = Session(Vault.open(tmp_path / "andreas.vault", "pw", **KDF), status=lambda *_: None)
    again.load_offline()
    assert [m.kind for m in again.sent_messages(b_key)] == [KIND_CHAT, KIND_POST]
    assert a_key == again.identity().key_text
    await b.close()
    server.close()


# --- groups (UN-RFC 0028 sections 3-5) -----------------------------------------

def test_manifest_kinds_field():
    from unseenet.core.article import ArticleError
    from unseenet.core.groups import Manifest, make_manifest, manifest_article
    owner = crypto.Identity.generate()
    both = Manifest.from_article(make_manifest(owner, "dk.snak", "open", pow_bits=BITS))
    assert both.kinds == (KIND_CHAT, KIND_POST)
    disc = make_manifest(owner, "dk.debat", "open", kinds=["post"], pow_bits=BITS)
    assert '"kinds":["post"]' in disc.body and Manifest.from_article(disc).kinds == ("post",)
    assert "kinds" not in make_manifest(owner, "dk.x", "open", kinds=["chat", "post"],
                                        pow_bits=BITS).body          # the default is left out
    for bad in ([], ["chat", "chat"], ["postcard"], "chat"):
        with pytest.raises(ValueError):
            manifest_article(owner, disc.group, {**__import__("json").loads(disc.body), "kinds": bad},
                             BITS)
    inbox = make_manifest(owner, "inbox", "inbox", kinds=["post"], pow_bits=BITS)
    assert Manifest.from_article(inbox).kinds == (KIND_CHAT, KIND_POST)   # inboxes take both
    assert ArticleError


def test_node_enforces_kinds_in_open_groups():
    from unseenet.core.article import ArticleError, new_article
    from unseenet.core.groups import Manifest, check_permitted, make_manifest
    owner, someone = crypto.Identity.generate(), crypto.Identity.generate()
    disc = Manifest.from_article(make_manifest(owner, "dk.debat", "open", kinds=["post"],
                                               pow_bits=BITS))
    chat = Manifest.from_article(make_manifest(owner, "dk.snak", "open", kinds=["chat"],
                                               pow_bits=BITS))

    def art(group, kind, subject="Emne"):
        extra = [("Message-Kind", kind)] if kind else []
        return new_article(group, subject, "tekst\n", from_name="x", extra=extra).finalize(someone, BITS)

    check_permitted(art(disc.group_id, "post"), disc, {})
    check_permitted(art(disc.group_id, None), disc, {})               # no header: a post
    with pytest.raises(ArticleError, match="chat line"):
        check_permitted(art(disc.group_id, "chat", ""), disc, {})
    check_permitted(art(chat.group_id, "chat", ""), chat, {})
    with pytest.raises(ArticleError, match="post with a subject"):
        check_permitted(art(chat.group_id, None), chat, {})


async def test_chat_lines_and_posts_in_groups(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me"); s.add_node(addr)

    both = await s.create_group("dk.snak", "open", min_pow=BITS)
    await s.post(both, "", "hej alle\n", kind=KIND_CHAT)
    await s.post(both, "Om Unseenet", "Et rigtigt indlæg\n")
    await s.fetch_group(both)
    got = sorted(s.cache[both].values(), key=lambda m: m.number)
    assert [(m.kind, m.subject) for m in got] == [(KIND_CHAT, ""), (KIND_POST, "Om Unseenet")]

    disc = await s.create_group("dk.debat", "open", min_pow=BITS, kinds=["post"])
    assert s.group_kinds(disc) == ("post",)
    with pytest.raises(sess.SessionError):
        await s.post(disc, "", "bare en linje\n", kind=KIND_CHAT)     # the client refuses
    with pytest.raises(sess.SessionError):
        await s.post(disc, "  ", "uden emne\n")                       # a post needs a subject
    await s.update_group(disc, kinds=["chat", "post"])            # the owner changes it
    assert s.group_kinds(disc) == (KIND_CHAT, KIND_POST) and "kinds" not in s.manifest_data(disc)

    closed = await s.create_group("dk.lukket", "closed", min_pow=BITS)
    await s.post(closed, "", "hemmelig hej\n", kind=KIND_CHAT)
    await s.fetch_group(closed)
    (m,) = s.cache[closed].values()
    assert m.encrypted and m.kind == KIND_CHAT and m.body == "hemmelig hej\n"
    await s.close()
    server.close()


async def test_a_chat_with_a_stranger_is_one_conversation(tmp_path, monkeypatch):
    """Chats are kept per person, contact or not; Private posts holds posts only."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    a, b = session("andreas"), session("mikkel")
    await a.ensure_inbox(); await b.ensure_inbox()
    b_key, b_pk = b.identity().key_text, b.identity().public_key
    await b.send_private(a.my_inbox, "", "ohøj, hvordan går det?\n", kind=KIND_CHAT)
    await a.fetch_group(a.my_inbox)
    await a.send_private(personal_inbox_id(b_pk), "", "godt :)\n", owner_key=b_pk, kind=KIND_CHAT)
    assert a.chat_partners() == [b_key]                      # not a contact, still a chat
    assert [m.body for m in a.conversation(b_key, KIND_CHAT)] == ["ohøj, hvordan går det?\n", "godt :)\n"]
    assert a.private_posts() == [] and a.unread_private_posts() == 0
    a.add_contact(b_key, "Mikkel")
    assert a.chat_partners() == [b_key]                      # once, now as a contact
    await a.close(); await b.close()
    server.close()
