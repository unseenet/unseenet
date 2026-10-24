"""#257 step 4: sent private posts with two envelopes (UN-RFC 0009 2.3, 0044 6) - the
sender can read them from another device, and nobody can tell whether it kept a copy."""
from datetime import timedelta

import pytest

from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.article import ArticleError
from unseenet.core.groups import (INBOX_SCHEME, INBOX_SCHEME2, inbox_article, open_inbox_article,
                                  personal_inbox_id)
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


def test_two_envelopes_open_for_the_owner_and_the_sender_only():
    owner, me, stranger = (crypto.Identity.generate() for _ in range(3))
    gid = personal_inbox_id(owner.public_key)
    def make(copy_to):
        return inbox_article(gid, owner.public_key, from_name="Me", subject="Hej", body="Hemmeligt\n",
                             sender=me, pow_bits=8, two_envelopes=True, copy_to=copy_to)
    kept, not_kept = make(me.public_key), make(None)
    assert kept["Encrypted"] == INBOX_SCHEME2
    for who in (owner, me):
        inner, sender = open_inbox_article(kept, who)
        assert inner.body == "Hemmeligt\n" and sender == me.public_key
    with pytest.raises(ArticleError):
        open_inbox_article(kept, stranger)
    with pytest.raises(ArticleError):
        open_inbox_article(not_kept, me)                       # no copy kept: not for me
    assert open_inbox_article(not_kept, owner)[0].body == "Hemmeligt\n"
    assert len(kept.body) == len(not_kept.body)               # the same size: nobody can tell


def test_nodes_take_both_forms_and_say_so():
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    owner, me = crypto.Identity.generate(), crypto.Identity.generate()
    from unseenet.core.groups import make_manifest
    m = make_manifest(owner, "inbox", "inbox", pow_bits=8)
    node.accept(m.to_bytes())
    for two in (False, True):
        art = inbox_article(m.group, owner.public_key, from_name="Me", subject="x", body="y\n",
                            sender=me, pow_bits=8, two_envelopes=two, copy_to=me.public_key)
        node.accept(art.to_bytes())
        assert node.store.get(art.message_id)


@pytest.fixture
async def people(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    import unseenet.client.session as sess
    import unseenet.client.session.state as sstate
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    monkeypatch.setattr(sstate, "WRITE_EVERY", 0.0)
    monkeypatch.setattr(Node, "STATE_EVERY", timedelta(0))
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = "127.0.0.1:%d" % server.sockets[0].getsockname()[1]
    sessions = []

    def person(name, seed=None):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        if seed:
            s.data["identities"][name] = {"seed": seed, "display": name}
            s.data["default_identity"] = name
        else:
            s.new_identity(name, name)
        s.add_node(addr)
        sessions.append(s)
        return s
    yield node, person
    for s in sessions:
        await s.close()
    server.close()


async def test_a_sent_post_follows_the_sender_to_another_device(people):
    node, person = people
    bob, alice = person("bob"), person("alice")
    await bob.ensure_inbox()                                   # offers sealedbox2: the node takes it
    assert bob.manifest_data(bob.my_inbox).get("sealedbox2") is True
    await alice.ensure_inbox()
    mid = await alice.send_private(bob.my_inbox, "Hej Bob", "Kun til dig\n")
    assert node.store.get(mid) and b"Encrypted: sealedbox2" in node.store.get(mid)
    await bob.fetch_group(bob.my_inbox)
    assert any(m.body.strip() == "Kun til dig" for m in bob.cache[bob.my_inbox].values())
    assert await alice.sync_state() == "written"               # the sent list goes with the state

    phone = person("alice-phone", seed=alice.identity().seed.hex())
    await phone.sync_state()
    assert await phone.fetch_sent_copies() == 1
    copy = next(e for e in phone.sent if e["msgid"] == mid)
    assert copy["body"].strip() == "Kun til dig" and copy["subject"] == "Hej Bob"


async def test_the_old_form_where_the_inbox_does_not_offer_the_new(people):
    node, person = people
    bob, alice = person("bob"), person("alice")
    await bob.ensure_inbox()
    entry = bob.group_entry(bob.my_inbox)                       # as an older client's inbox
    alice.group_entry(bob.my_inbox)["manifest"] = {k: v for k, v in entry["manifest"].items()
                                                   if k != "sealedbox2"}
    alice.group_entry(bob.my_inbox)["owner_key"] = bob.identity().key_text
    await alice.ensure_inbox()
    mid = await alice.send_private(bob.my_inbox, "Hej", "Gammel form\n",
                                   owner_key=bob.identity().public_key)
    assert b"Encrypted: sealedbox\r\n" in node.store.get(mid) or b"Encrypted: sealedbox\n" in node.store.get(mid)
    assert not alice.data.get("sent_copies")                    # kept in the vault only, as before
    assert any(e["msgid"] == mid for e in alice.sent)
