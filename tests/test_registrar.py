"""The registrar (UN-RFC 0019 sections 6 and 6.8), against a real local node."""

from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
import unseenet.core.groups as groups
from unseenet import hierarchies as hz
from unseenet import names as nm
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.groups import make_group_id, make_manifest, manifest_article
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig
from unseenet.registrar import Registrar

KDF = {"ops": 1, "mem": 8192 * 1024}
TLDS = {"com", "dk", "org", "microsoft", "app"}


class World:
    """A node, the project, a registrar group with a claim inbox, and helpers."""

    def __init__(self, node, addr, tmp_path):
        self.node, self.addr, self.tmp = node, addr, tmp_path
        self.project, self.inbox_key = crypto.Identity.generate(), crypto.Identity.generate()
        self.replicas = [crypto.Identity.generate() for _ in range(3)]
        self.dns: dict[str, list[str]] = {}
        self.clock = datetime.now(timezone.utc)
        # claims are sent in batches, 20 minutes apart (clients round Date to 10 minutes)
        self.post_time = datetime.now(timezone.utc) - timedelta(hours=3)
        inbox = make_manifest(self.inbox_key, "inbox", "inbox", retention_days=30, pow_bits=8)
        node.accept(inbox.to_bytes())
        self.claims = inbox.group
        self.group = make_group_id("unseenet.names", self.project.public_key)
        self.manifest(posters=self.replicas[:2])

    def manifest(self, posters, serial=1):
        data = {"v": 1, "name": "unseenet.names", "type": "channel", "owner": self.project.key_text,
                "serial": serial, "posters": [p.key_text for p in posters], "min_pow": 0,
                "retention_days": 90, "claims": self.claims}
        self.node.accept(manifest_article(self.project, self.group, data, pow_bits=8).to_bytes())

    def session(self, name, *identities):
        s = Session(Vault.open(self.tmp / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        for i, ident in enumerate(identities):
            s.data["identities"][f"k{i}"] = {"seed": ident.seed.hex(), "display": name}
        s.data["default_identity"] = "k0"
        s.add_node(self.addr)
        return s

    def registrar(self, i, root=None):
        s = self.session(f"replica{i}", self.replicas[i], self.inbox_key)
        return Registrar(s, self.group, tlds=lambda: TLDS,
                         dns_txt=lambda n: self.dns.get(n, []), now=lambda: self.clock, root=root)

    async def user(self, name):
        s = self.session(name, crypto.Identity.generate())
        await s.ensure_inbox()
        return s

    async def claim(self, user, action, name, to=None):
        return await user.send_private(self.claims, "claim", nm.make_claim(action, name, to),
                                       owner_key=self.inbox_key.public_key,
                                       content_type="application/json")

    async def process(self, *regs):
        """Every replica sees the claims soon after they are sent, then handles them
        when they are more than an hour old (UN-RFC 0019 section 6.8). The next
        claims are sent later."""
        sent = self.post_time
        self.clock = sent + timedelta(minutes=15)
        for r in regs:
            await r.run_once()
        self.clock = sent + timedelta(minutes=75)
        for r in regs:
            await r.run_once()
        self.post_time = sent + timedelta(minutes=20)

    def certs_for(self, reg, name):
        return [c for c in reg.certs if c.name == name]


@pytest.fixture
async def world(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    w = World(node, f"127.0.0.1:{server.sockets[0].getsockname()[1]}", tmp_path)
    real = groups.new_article
    monkeypatch.setattr(groups, "new_article",                  # inbox articles get the batch time
                        lambda *a, **k: real(*a, **{**k, "now": k.get("now") or w.post_time}))
    yield w
    server.close()


async def replies(user):
    msgs = await user.fetch_group(user.my_inbox)
    return [(m.subject, m.body) for m in msgs if m.private and m.readable]


async def test_claim_two_replicas_agree_and_the_user_hears(world):
    alice, bob = await world.user("alice"), await world.user("bob")
    r1, r2 = world.registrar(0), world.registrar(1)
    await world.claim(alice, "claim", "lorensen")
    await world.process(r1, r2)

    certs = world.certs_for(r2, "lorensen")
    assert {c.registrar for c in certs} == {world.replicas[0].key_text, world.replicas[1].key_text}
    assert {c.decision for c in certs} == {("lorensen", alice.identity().key_text, 1)}
    assert nm.current(certs)[0].key == alice.identity().key_text
    got = await replies(alice)
    assert [s for s, _ in got] == ["name lorensen: issued"] * 2      # one from each replica
    assert nm.parse_certificate(got[0][1]).key == alice.identity().key_text

    # taken, top-level domain, reserved, bad syntax
    await world.claim(bob, "claim", "lorensen")
    await world.claim(bob, "claim", "microsoft")
    await world.claim(bob, "claim", "unseenet")
    await world.process(r1)
    refused = {s: b for s, b in await replies(bob)}
    assert "taken" in refused["name lorensen: refused"]
    assert "top-level domain" in refused["name microsoft: refused"]
    assert "reserved" in refused["name unseenet: refused"]
    await alice.close(), await bob.close(), await r1.s.close(), await r2.s.close()


async def test_names_of_others_go_to_their_owners(world):
    """UN-RFC 0019 section 4.5: a hierarchy's name to its maintainer (or nobody),
    a top-level domain to whoever its registry names under nic.<tld>."""
    bob, carol, dave = await world.user("bob"), await world.user("carol"), await world.user("dave")
    root = {**hz.builtin_root_list()[1],
            "openorg": hz.Hierarchy("openorg", "governed", maintainer=carol.identity().key_text)}
    r1 = world.registrar(0, root=root)
    world.dns[nm.tld_record_name("microsoft")] = [nm.dns_record_value(dave.identity().key_text)]
    for name in ("torproject", "matrix", "openorg", "microsoft"):
        await world.claim(bob, "claim", name)
    await world.process(r1)
    refused = {s: b for s, b in await replies(bob)}
    assert "hierarchy torproject.*" in refused["name torproject: refused"]
    assert "hierarchy matrix.*" in refused["name matrix: refused"]
    assert "maintainer" in refused["name openorg: refused"]
    assert "_unseenet.nic.microsoft" in refused["name microsoft: refused"]

    await world.claim(carol, "claim", "openorg")
    await world.claim(dave, "claim", "microsoft")
    await world.process(r1)
    assert nm.current(world.certs_for(r1, "openorg"))[0].key == carol.identity().key_text
    assert nm.current(world.certs_for(r1, "microsoft"))[0].key == dave.identity().key_text

    # the project gets no hierarchy name it does not maintain (section 4.1 item 3)
    project = world.session("project", world.project)
    await project.ensure_inbox()
    await world.claim(project, "claim", "torproject")
    await world.process(r1)
    assert not world.certs_for(r1, "torproject")

    # a hierarchy that changes hands: carol's name is not renewed (section 6.3)
    r1.root["openorg"] = hz.Hierarchy("openorg", "governed", maintainer=dave.identity().key_text)
    await world.claim(carol, "renew", "openorg")
    await world.process(r1)
    assert "maintainer" in {s: b for s, b in await replies(carol)}["name openorg: refused"]
    for s in (bob, carol, dave, project, r1.s):
        await s.close()


async def test_project_may_hold_reserved_names_and_limits_apply(world):
    project = world.session("project", world.project)
    await project.ensure_inbox()
    r1 = world.registrar(0)
    await world.claim(project, "claim", "unseenet")
    alice = await world.user("alice")
    for name in ("one", "two", "three", "four"):
        await world.claim(alice, "claim", name)
    await world.process(r1)
    assert nm.current(world.certs_for(r1, "unseenet"))[0].key == world.project.key_text
    held = {c.name for c in r1.certs if c.key == alice.identity().key_text}
    assert len(held) == nm.MAX_NAMES_PER_KEY          # which three: the order of section 6.8
    (left,) = {"one", "two", "three", "four"} - held
    assert any("at most" in b for s, b in await replies(alice) if s == f"name {left}: refused")
    await alice.close(), await project.close(), await r1.s.close()


async def test_domain_needs_its_txt_record(world):
    alice = await world.user("alice")
    r1 = world.registrar(0)
    await world.claim(alice, "claim", "lorensen.dk")
    await world.process(r1)
    assert not world.certs_for(r1, "lorensen.dk")
    world.dns["_unseenet.lorensen.dk"] = [nm.dns_record_value(alice.identity().key_text)]
    await world.claim(alice, "claim", "lorensen.dk")
    await world.process(r1)
    (cert,) = world.certs_for(r1, "lorensen.dk")
    assert cert.kind == "domain" and cert.expires - cert.issued == timedelta(days=35)
    await alice.close(), await r1.s.close()


async def test_transfer_and_release(world):
    alice, bob = await world.user("alice"), await world.user("bob")
    r1 = world.registrar(0)
    await world.claim(alice, "claim", "lorensen")
    await world.process(r1)
    await world.claim(bob, "transfer", "lorensen", bob.identity().key_text)     # not his to give
    await world.process(r1)
    assert any("do not hold" in b for _, b in await replies(bob))
    await world.claim(alice, "transfer", "lorensen", bob.identity().key_text)
    await world.process(r1)
    assert ("lorensen", 1) in r1.revoked
    live = [c for c in world.certs_for(r1, "lorensen") if (c.name, c.serial) not in r1.revoked]
    assert nm.current(live)[0].key == bob.identity().key_text and nm.current(live)[0].serial == 2
    await world.claim(bob, "release", "lorensen")
    await world.process(r1)
    assert ("lorensen", 2) in r1.revoked
    await world.claim(alice, "claim", "lorensen")                  # free again
    await world.process(r1)
    live = [c for c in world.certs_for(r1, "lorensen") if (c.name, c.serial) not in r1.revoked]
    assert nm.current(live)[0].key == alice.identity().key_text and nm.current(live)[0].serial == 3
    await alice.close(), await bob.close(), await r1.s.close()


async def test_new_replica_rebuilds_from_the_network(world):
    alice = await world.user("alice")
    r1 = world.registrar(0)
    await world.claim(alice, "claim", "lorensen")
    await world.process(r1)
    world.manifest(posters=world.replicas, serial=2)          # the owner adds a third replica
    r3 = world.registrar(2)                                    # new machine, empty vault
    await r3.run_once()
    certs = world.certs_for(r3, "lorensen")
    assert {c.registrar for c in certs} == {world.replicas[0].key_text, world.replicas[2].key_text}
    assert len({c.to_json() for c in certs}) == 2 and len({c.decision for c in certs}) == 1
    await alice.close(), await r1.s.close(), await r3.s.close()


async def test_late_claim_is_refused(world):
    alice = await world.user("alice")
    r1 = world.registrar(0)
    world.post_time = datetime.now(timezone.utc)
    world.clock = world.post_time
    await r1.run_once()                                        # running, has seen nothing
    await world.claim(alice, "claim", "lorensen")
    world.clock = world.post_time + timedelta(hours=3)         # first seen long after its Date
    await r1.run_once()
    assert not world.certs_for(r1, "lorensen")
    assert ("late", "Your claim arrived late; send it again.\n") in await replies(alice)
    await alice.close(), await r1.s.close()


async def test_unsettled_claims_wait(world):
    alice = await world.user("alice")
    r1 = world.registrar(0)
    world.post_time = datetime.now(timezone.utc)
    await world.claim(alice, "claim", "lorensen")
    world.clock = world.post_time + timedelta(minutes=15)      # not an hour old yet
    await r1.run_once()
    assert not world.certs_for(r1, "lorensen")
    world.clock += timedelta(hours=1)
    await r1.run_once()
    assert world.certs_for(r1, "lorensen")
    await alice.close(), await r1.s.close()


async def test_a_key_not_in_the_manifest_cannot_run(world):
    rogue = world.session("rogue", crypto.Identity.generate(), world.inbox_key)
    reg = Registrar(rogue, world.group, tlds=lambda: TLDS, dns_txt=lambda n: [],
                    now=lambda: world.clock)
    with pytest.raises(sess.SessionError, match="not a poster"):
        await reg.run_once()
    await rogue.close()


async def test_client_claims_a_name_and_others_see_it(world, monkeypatch):
    """The client side (UN-RFC 0019 sections 5.2, 6.1 and 8): claim from the client,
    see the name, send it with posts, and show it for others."""
    from unseenet import known_nodes as kn
    from unseenet.client import naming
    monkeypatch.setattr(nm, "NAMES_GROUP", world.group)
    monkeypatch.setattr(kn, "PROJECT_KEY", world.project.key_text)
    alice, bob = await world.user("alice"), await world.user("bob")
    alice_key = alice.identity().key_text
    assert alice.identity_label(alice_key, "@Andreas").startswith("Andreas~")   # no fake @

    await alice.refresh_naming()
    await naming.claim(alice, "lorensen")
    assert [p[0] for p in naming.pending(alice)] == ["lorensen"]
    await world.process(world.registrar(0), world.registrar(1))

    await alice.refresh_naming()
    assert [c.name for c in naming.my_names(alice)] == ["lorensen"]
    assert alice.identity_label(alice_key) == "@lorensen"

    talk = await alice.create_group("dk.snak", "open", min_pow=8)
    await alice.post(talk, "Hej", "Første\n")
    await alice.post(talk, "Igen", "Anden\n")             # within a week: no certificate again
    bob.subscribe(talk)
    msgs = await bob.fetch_group(talk)
    assert len(naming._store(bob)["seen"][alice_key]) == 1             # sent once, with the first
    assert naming.header_for(alice, talk) is None
    assert bob.identity_label(alice_key, "Andreas").startswith("Andreas~")   # registrar unknown yet
    await bob.refresh_naming()
    assert bob.identity_label(msgs[0].author_key, msgs[0].from_name) == "@lorensen"
    bob.add_contact(alice_key, "Søster")
    assert bob.identity_label(alice_key) == "Søster √"     # your own name for her comes first
    for s in (alice, bob):
        await s.close()


async def test_person_at_domain_through_dns_and_no_sub_names(world):
    """UN-RFC 0019 section 6.4: andlo@lorensen.dk needs andlo._unseenet.lorensen.dk;
    a name under a registered name is the holder's to give, not the registrar's."""
    alice = await world.user("alice")
    r1 = world.registrar(0)
    world.dns["andlo._unseenet.lorensen.dk"] = [nm.dns_record_value(alice.identity().key_text)]
    await world.claim(alice, "claim", "andlo@lorensen.dk")
    await world.claim(alice, "claim", "sonia@lorensen")
    await world.process(r1)
    (cert,) = world.certs_for(r1, "andlo@lorensen.dk")
    assert cert.kind == "domain" and cert.key == alice.identity().key_text
    refused = {s: b for s, b in await replies(alice)}
    assert "holder" in refused["name sonia@lorensen: refused"]
    await alice.close(), await r1.s.close()


@pytest.fixture(autouse=True)
def _history_dates(monkeypatch):
    """These tests build history with old Dates, or move the clock, as nodes see articles
    over time; the rule that a POST is not more than an hour in the past (UN-RFC 0049
    section 3.2) has its own tests in test_origins.py."""
    from datetime import timedelta
    from unseenet.node import server as node_server
    monkeypatch.setattr(node_server, "POST_PAST", timedelta(days=3650))


async def test_the_registrar_renews_its_claim_inbox(world):
    """#607: the claim inbox is renewed like any client's own inbox (UN-RFC 0029, 4)."""
    data = {"v": 1, "name": "inbox", "type": "inbox", "owner": world.inbox_key.key_text,
            "serial": 2, "min_pow": 8, "retention_days": 30}
    world.node.accept(manifest_article(world.inbox_key, world.claims, data, pow_bits=8,
                                       now=world.clock, lifetime=timedelta(days=5)).to_bytes())
    r1 = world.registrar(0)
    await r1.run_once()

    alice = await world.user("alice")
    await alice.fetch_group(world.claims)
    m = alice.manifest_data(world.claims)
    assert m["serial"] == 3
    assert groups.stored_expires(m) - world.clock > timedelta(days=30)
    # and a replica without the inbox key leaves it alone
    r2 = Registrar(world.session("keyless", world.replicas[1]), world.group,
                   tlds=lambda: TLDS, dns_txt=lambda n: [], now=lambda: world.clock)
    await r2.read_group()
    assert not r2.s.group_entry(world.claims).get("owner")
    await alice.close(), await r1.s.close(), await r2.s.close()
