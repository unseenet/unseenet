"""UN-RFC 0028: chats and letters in private messages."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.article import Article
from unseenet.core.groups import (KIND_CHAT, KIND_LETTER, inbox_article, message_kind,
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
    assert message_kind(inner) == KIND_LETTER and inner["Subject"] == "Om weekenden"


def test_missing_or_unknown_kind_is_a_letter():
    assert message_kind(Article([("Subject", "x")], "")) == KIND_LETTER
    assert message_kind(Article([("Message-Kind", "postcard")], "")) == KIND_LETTER
    assert message_kind(Article([("Message-Kind", " Chat ")], "")) == KIND_CHAT
    owner = crypto.Identity.generate()
    with pytest.raises(ValueError):
        inbox_article(personal_inbox_id(owner.public_key), owner.public_key, from_name="x",
                      subject="s", body="b", kind="postcard", pow_bits=BITS)


async def test_chats_and_letters_apart(tmp_path, monkeypatch):
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
    assert a.unread_from(b_key, KIND_CHAT) == 1 and a.unread_from(b_key, KIND_LETTER) == 1
    assert a.unread_private(KIND_LETTER) == 1

    await a.send_private(personal_inbox_id(b_pk), "would be dropped", "hej skat\n",
                         owner_key=b_pk, kind=KIND_CHAT)
    await a.send_private(personal_inbox_id(b_pk), "Re: Om weekenden", "> Kære far\nJa!\n",
                         owner_key=b_pk)
    assert [m.body for m in a.conversation(b_key, KIND_CHAT)] == ["hej far\n", "hej skat\n"]
    assert [m.subject for m in a.private_messages(KIND_LETTER)] == ["Om weekenden", "Re: Om weekenden"]
    assert all(m.subject == "" for m in a.conversation(b_key, KIND_CHAT))
    assert len(a.conversation(b_key)) == 4              # no kind: both

    # your own copies keep their kind across a restart
    await a.close()
    again = Session(Vault.open(tmp_path / "andreas.vault", "pw", **KDF), status=lambda *_: None)
    again.load_offline()
    assert [m.kind for m in again.sent_messages(b_key)] == [KIND_CHAT, KIND_LETTER]
    assert a_key == again.identity().key_text
    await b.close()
    server.close()
