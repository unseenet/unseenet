"""UN-RFC 0009 (inbox and local groups) and 0011 (node information)."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import (Manifest, check_permitted, inbox_article, make_manifest,
                                  open_inbox_article, personal_inbox_id)
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.nntp import Client
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}


def test_inbox_article_roundtrip_and_privacy():
    owner, sender, other = (crypto.Identity.generate() for _ in range(3))
    gid = personal_inbox_id(owner.public_key)
    art = inbox_article(gid, owner.public_key, from_name="Sonia", subject="Hej",
                        body="Kun til dig\n", sender=sender, reply_inbox="inbox@aaaaaaaaaaaaaaaa",
                        pow_bits=BITS)
    raw = art.to_bytes()
    assert b"Kun til dig" not in raw and b"Sonia" not in raw
    assert sender.key_text.encode() not in raw          # sender hidden from nodes
    assert art["Author-Key"] != sender.key_text          # outer key is one-time

    inner, who = open_inbox_article(art, owner)
    assert who == sender.public_key
    assert inner["Subject"] == "Hej" and inner.body == "Kun til dig\n"
    assert inner["Reply-Inbox"] == "inbox@aaaaaaaaaaaaaaaa"
    with pytest.raises(ArticleError):
        open_inbox_article(art, other)                  # only the owner can read


def test_anonymous_and_forged_sender():
    owner, sender = crypto.Identity.generate(), crypto.Identity.generate()
    gid = personal_inbox_id(owner.public_key)
    anon = inbox_article(gid, owner.public_key, from_name="x", subject="s", body="b", pow_bits=BITS)
    inner, who = open_inbox_article(anon, owner)
    assert who is None and "Sender-Key" not in inner

    # a sender signature made for another inbox does not verify here
    other_owner = crypto.Identity.generate()
    lifted = inbox_article(personal_inbox_id(other_owner.public_key), other_owner.public_key,
                           from_name="x", subject="s", body="b", sender=sender, pow_bits=BITS)
    with pytest.raises(ArticleError):
        open_inbox_article(lifted, owner)


def test_node_only_accepts_sealed_articles_in_inbox():
    owner, writer = crypto.Identity.generate(), crypto.Identity.generate()
    m = Manifest.from_article(make_manifest(owner, "inbox", "inbox", pow_bits=BITS))
    plain = new_article(m.group_id, "plain", "visible", from_name="w").finalize(writer, BITS)
    with pytest.raises(ArticleError):
        check_permitted(plain, m, {})
    sealed = inbox_article(m.group_id, owner.public_key, from_name="w", subject="s",
                           body="b", pow_bits=BITS)
    check_permitted(sealed, m, {})


async def test_local_group_never_crosses_nodes():
    b = Node(Store(), NodeConfig(name="b", min_pow=BITS, forward_delay=(0, 0)))
    server_b = await b.serve("127.0.0.1", 0)
    addr_b = f"127.0.0.1:{server_b.sockets[0].getsockname()[1]}"
    a = Node(Store(), NodeConfig(name="a", min_pow=BITS, forward_delay=(0, 0),
                                 peers=[PeerConfig(name="b", address=addr_b)]))
    owner = crypto.Identity.generate()
    local = make_manifest(owner, "operator", "inbox", local=True, pow_bits=BITS)
    normal = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    a.accept(local.to_bytes())
    a.accept(normal.to_bytes())
    assert a.store.due("b") == [normal.message_id]       # the local one is not queued

    # even if pushed directly, a peer refuses it
    c = await Client.connect(addr_b)
    await c.command("MODE STREAM", (203,))
    from unseenet.nntp import dot_stuff
    c.writer.write(f"TAKETHIS {local.message_id}\r\n".encode() + dot_stuff(local.to_bytes()))
    await c.writer.drain()
    code, _ = await c._response()
    assert code == 439
    await c.quit()
    # ... while a client may still create it on its own node
    assert (await _post(addr_b, local.to_bytes()))[0] == 240
    server_b.close()


async def _post(addr, raw):
    c = await Client.connect(addr)
    try:
        return await c.post(raw)
    finally:
        await c.quit()


async def test_private_messages_and_operator_contact(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    operator = crypto.Identity.generate()
    contact = make_manifest(operator, "operator", "inbox", local=True, pow_bits=10)
    node = Node(Store(), NodeConfig(name="testnode", min_pow=BITS, forward_delay=(0, 0),
                                    operator={"key": operator.key_text, "contact": contact.group,
                                              "description": "Test node"}))
    node.accept(contact.to_bytes())
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    a, b = session("andreas"), session("sonia")
    await a.ensure_inbox()
    await b.ensure_inbox()

    # b writes privately to a, knowing only a's key
    await b.send_private(personal_inbox_id(a.identity().public_key), "Hej far", "Hemmelig besked\n")
    msgs = await a.fetch_group(a.my_inbox)
    assert len(msgs) == 1 and msgs[0].private
    m = msgs[0]
    assert (m.subject, m.body, m.from_name) == ("Hej far", "Hemmelig besked\n", "Sonia")
    assert m.sender_key == b.identity().key_text
    assert a.reply_target(m) == b.my_inbox

    # a replies; b reads it; a cannot read b's inbox
    await a.send_private(a.reply_target(m), "Re: Hej far", "Hej skat\n", references=[m.message_id])
    got = await b.fetch_group(b.my_inbox)
    assert got[0].body == "Hej skat\n" and got[0].references == [m.message_id]
    spy = await a.fetch_group(b.my_inbox)
    assert spy and not spy[0].readable

    # node information and writing to the operator
    info = await b.node_info()
    assert info["name"] == "testnode" and info["contact"] == contact.group
    assert info["operator"] == operator.key_text and info["policy"]["min_pow"] == BITS
    await b.send_private(info["contact"], "Misbrug", "Gruppe X er spam\n",
                         owner_key=crypto.key_from_text(info["operator"]))
    stored = [r for r in node.store.numbers(contact.group)]
    assert len(stored) == 2                                # manifest + the message
    raw = node.store.by_number(contact.group, stored[-1])[1]
    assert b"spam" not in raw                               # the node cannot read it

    for s in (a, b):
        await s.close()
    server.close()


async def test_contacts_and_conversation(tmp_path, monkeypatch):
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
    b_key = b.identity().key_text
    a.add_contact(b_key, "Min datter")
    with pytest.raises(sess.SessionError):
        a.add_contact(a.identity().key_text, "mig selv")

    await b.send_private(a.my_inbox, "Hej far", "Første\n")
    await a.fetch_group(a.my_inbox)
    assert a.unread_from(b_key) == 1
    await a.send_private(personal_inbox_id(b.identity().public_key), "Re: Hej far", "Svar\n",
                         owner_key=b.identity().public_key)
    conv = a.conversation(b_key)
    assert [(m.from_name, m.body) for m in conv] == [("Sonia", "Første\n"), ("You", "Svar\n")]
    assert a.is_read(conv[1])                       # your own message is read

    # sent copies survive a restart, encrypted on disk
    await a.close()
    assert not (tmp_path / "andreas.vault.sent").exists()        # one file: the vault
    assert b"Svar" not in (tmp_path / "andreas.vault").read_bytes()
    again = Session(Vault.open(tmp_path / "andreas.vault", "pw", **KDF), status=lambda *_: None)
    again.load_offline()
    assert [m.body for m in again.conversation(b_key)] == ["Første\n", "Svar\n"]
    assert again.contact_name(b_key) == "Min datter"
    await b.close()
    server.close()


async def test_push_and_low_latency(tmp_path, monkeypatch):
    """UN-RFC 0008: watchers hear about new articles at once; chat groups skip the delay."""
    import asyncio
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(30, 60),
                                    peers=[PeerConfig(name="p", address="127.0.0.1:1")]))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    a = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    a.new_identity("a", "A"); a.add_node(addr)
    b = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    b.new_identity("b", "B"); b.add_node(addr)
    chat = await a.create_group("chat.venner", "open", view="chat", low_latency=True, min_pow=9)
    slow = await a.create_group("dk.snak", "open", min_pow=9)

    heard = []
    got = asyncio.Event()

    async def on_new(gid, msgid):
        heard.append((gid, msgid))
        got.set()
    watcher = asyncio.create_task(b.watch(on_new))
    await asyncio.sleep(0.3)
    msgid = await a.post(chat, "hej", "Hej!\n")
    await asyncio.wait_for(got.wait(), timeout=3)
    assert (chat, msgid) in heard

    import time
    queue = dict(node.store.db.execute("SELECT message_id, not_before FROM peer_queue WHERE peer='p'"))
    assert queue[msgid] <= time.time() + 0.5            # chat: forwarded at once
    slow_id = await a.post(slow, "hej", "Hej\n")
    queue = dict(node.store.db.execute("SELECT message_id, not_before FROM peer_queue WHERE peer='p'"))
    assert queue[slow_id] >= time.time() + 25            # discussion: random delay kept

    watcher.cancel()
    for s in (a, b):
        await s.close()
    server.close()
