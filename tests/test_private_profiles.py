"""#182: private profiles (UN-RFC 0022 section 6) - shared with one person or a closed
group, shown only there, and taken back with an empty one."""
import pytest

import unseenet.client.session as sess
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
        return s
    yield person
    for s in made:
        await s.close()
    server.close()


async def test_a_profile_shared_with_one_person_only(people):
    alice, bob = people("alice"), people("bob")
    await bob.ensure_inbox()
    await alice.ensure_inbox()
    await alice.share_profile(bob.my_inbox, {"v": 1, "about": "Kun til dig: jeg er Alice"})
    await bob.fetch_group(bob.my_inbox)
    key = alice.identity().key_text
    assert bob.private_profile(key, "me")["about"] == "Kun til dig: jeg er Alice"
    assert bob.shared_contexts(key) == ["me"]
    assert not any(m.private_profile for m, _ in bob.threads(bob.my_inbox))   # not a post
    await alice.withdraw_shared_profile(bob.my_inbox)                         # taken back
    await bob.fetch_group(bob.my_inbox)
    assert bob.private_profile(key, "me") is None


async def test_a_profile_shared_in_a_closed_group_stays_in_it(people):
    alice, bob = people("alice"), people("bob")
    fam = await alice.create_group("familie", "closed", min_pow=10)
    await alice.invite(fam, bob.identity().key_text)
    await alice.share_profile(fam, {"v": 1, "about": "Mor i familien"})
    bob.subscribe(fam)
    await bob.fetch_group(fam)
    key = alice.identity().key_text
    assert bob.private_profile(key, fam)["about"] == "Mor i familien"
    assert bob.private_profile(key, "me") is None                 # never outside its context
    assert all(not m.private_profile for m, _ in bob.threads(fam))


async def test_only_to_a_person_or_a_closed_group(people):
    alice = people("alice")
    pub = await alice.create_group("dk.snak", "open", min_pow=10)
    with pytest.raises(SessionError, match="person or a closed group"):
        await alice.share_profile(pub, {"v": 1, "about": "Hej"})
