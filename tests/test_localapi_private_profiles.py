"""#442: private profiles in the local client API (UN-RFC 0046 section 4.16, UN-RFC 0022
section 6), against a real node: sharing with one person or a closed group, the profile
shown only where it was shared, taking it back, and refusing an open group."""

import pytest

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI
from unseenet.client.session import Session, SessionError
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def people(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    made = []

    def person(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        made.append(s)
        return s, LocalAPI(session=s)
    yield person
    for s in made:
        await s.close()
    server.close()


async def test_shared_with_one_person_shown_only_to_them(people):
    (alice, a_api), (bob, b_api) = people("alice"), people("bob")
    await bob.ensure_inbox()
    await alice.ensure_inbox()
    bob_key, key = bob.identity().key_text, alice.identity().key_text
    got = await a_api.share_profile({"to": bob_key, "profile": {"edit": {"about": "Kun til dig"}}})
    assert got["ok"] and got["id"]
    await bob.fetch_group(bob.my_inbox)
    shown = await b_api.profile(key, "me")
    assert shown["shared"]["profile"]["about"] == "Kun til dig"
    assert shown["shared"]["context"] == "me" and shown["shared"]["context_label"] == "you"
    assert (await b_api.profile(key, f"contact:{key}"))["shared"]["context"] == "me"
    assert (await b_api.profile(key))["shared"] is None          # not outside its context
    await a_api.share_profile({"to": bob_key, "withdraw": True})    # taken back
    await bob.fetch_group(bob.my_inbox)
    assert (await b_api.profile(key, "me"))["shared"] is None


async def test_shared_in_a_closed_group_stays_in_it(people):
    (alice, a_api), (bob, b_api) = people("alice"), people("bob")
    fam = await alice.create_group("familie", "closed", min_pow=10)
    await alice.invite(fam, bob.identity().key_text)
    await a_api.share_profile({"to": fam, "profile": {"v": 1, "about": "Mor i familien"}})
    bob.subscribe(fam)
    await bob.fetch_group(fam)
    key = alice.identity().key_text
    assert (await b_api.profile(key, fam))["shared"]["profile"]["about"] == "Mor i familien"
    assert (await b_api.profile(key, "me"))["shared"] is None


async def test_only_to_a_person_or_a_closed_group(people):
    alice, api = people("alice")
    pub = await alice.create_group("dk.snak", "open", min_pow=10)
    with pytest.raises(SessionError, match="person or a closed group"):
        await api.share_profile({"to": pub})
    with pytest.raises(SessionError, match="with whom"):
        await api.share_profile({"to": ""})
    with pytest.raises(SessionError, match="an object"):
        await api.share_profile({"to": pub, "profile": "hej"})
