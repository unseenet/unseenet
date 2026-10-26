"""#513: reactions to private chats and posts (UN-RFC 0048 section 4.3) - sealed to the
sender's inbox, the latest per verified sender counting, an empty one taking it back,
any emoji, never shown as a message."""

from datetime import timedelta

import pytest

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI
from unseenet.client.session import Session, SessionError
from unseenet.core import reactions as rx
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


def test_a_take_back_counts_as_the_latest():
    items = [("<a@x>", "k1", 100, "<t@x>", "👍"), ("<b@x>", "k1", 200, "<t@x>", ""),
             ("<c@x>", "k2", 100, "<t@x>", "❤️")]
    counts = rx.count(items, takebacks=True)["<t@x>"]
    assert counts.of("k1") is None and counts.of("k2") == "❤️" and counts.total() == 1
    assert rx.count(items)["<t@x>"].of("k1") == "👍"            # groups: no take-backs


@pytest.fixture
async def two(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(Node, "STATE_EVERY", timedelta(0))
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = "127.0.0.1:%d" % server.sockets[0].getsockname()[1]
    made = []

    def person(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        made.append(s)
        return s
    person.node = node
    yield person
    for s in made:
        await s.close()
    server.close()


async def test_react_change_and_take_back_a_chat_line(two):
    me, sonia = two("me"), two("sonia")
    await me.ensure_inbox()
    await sonia.ensure_inbox()
    line = await sonia.send_chat("contact:" + me.identity().key_text, "Hej")
    msgs = await me.fetch_group(me.my_inbox)
    hej = next(m for m in msgs if m.message_id == line)
    assert me.react_permission(me.my_inbox, hej)
    assert me.reaction_set(me.my_inbox).takes("🦔")                     # any emoji

    await me.react(hej, "👍")
    assert me.reactions_on(hej).of(me.identity().key_text) == "👍"       # mine, from my sent list
    assert all(m.kind != rx.KIND_REACTION for m in me.private_messages())  # not a message
    await sonia.fetch_group(sonia.my_inbox)
    mine_there = next(m for m in sonia.private_messages() if m.message_id == line)
    assert sonia.reactions_on(mine_there).of(me.identity().key_text) == "👍"
    assert all(m.kind != rx.KIND_REACTION for m in sonia.private_messages())
    from unseenet.core.article import Article
    sent = next(e for e in reversed(me.sent) if e.get("kind") == "reaction")
    outer = Article.from_bytes(two.node.store.get(sent["msgid"]))
    assert outer.get("References") is None and outer.get("Reaction") is None   # sealed (4.3)

    await me.react(hej, "❤️")                                          # change: a new one
    await sonia.fetch_group(sonia.my_inbox)
    assert sonia.reactions_on(mine_there).of(me.identity().key_text) == "❤️"
    assert me.reactions_on(hej).total() == 1

    assert await me.react(hej, "❤️") is None                          # again: taken back
    await sonia.fetch_group(sonia.my_inbox)
    assert sonia.reactions_on(mine_there).total() == 0
    assert me.reactions_on(hej).total() == 0


async def test_what_cannot_be_reacted_to(two):
    me, sonia = two("me"), two("sonia")
    await me.ensure_inbox()
    await sonia.ensure_inbox()
    await me.send_chat("contact:" + sonia.identity().key_text, "Mit eget")
    own = next(m for m in me.private_messages() if m.to_key)
    assert me.react_permission(me.my_inbox, own).code == "own"
    with pytest.raises(SessionError, match="own"):
        await me.react(own, "👍")
    await sonia.send_private(me.my_inbox, "Hvem?", "Anonymt\n", anonymous=True,
                             owner_key=me.identity().public_key)
    anon = next(m for m in await me.fetch_group(me.my_inbox) if not m.sender_key and m.readable)
    assert me.react_permission(me.my_inbox, anon).code == "anonymous"


async def test_the_local_api_offers_it_on_private_rows(two):
    me, sonia = two("me"), two("sonia")
    await me.ensure_inbox()
    await sonia.ensure_inbox()
    line = await sonia.send_chat("contact:" + me.identity().key_text, "Hej igen")
    await me.fetch_group(me.my_inbox)
    api = LocalAPI(session=me)
    rows = api.group("contact:" + sonia.identity().key_text)["rows"]
    row = next(r for r in rows if r["message"]["id"] == line)
    assert row["react"]["allowed"] is True and row["react_offered"]["any"] is True
