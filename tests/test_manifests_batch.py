"""UN-RFC 0041: fetching many manifests at once (XUN-MANIFESTS)."""

import pytest

import unseenet.client.session as sess
import unseenet.node.server as srv
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core import profiles as prof
from unseenet.core.groups import Manifest, inbox_article, make_manifest
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.nntp import MANIFESTS_MAX, Client, NNTPError
from unseenet.node import pulling
from unseenet.node.pulling import Puller
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}


def make_node(name="n", **kw) -> Node:
    return Node(Store(), NodeConfig(name=name, min_pow=BITS, forward_delay=(0, 0), **kw))


async def serve(node):
    server = await node.serve("127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def profiles(node, n):
    out = []
    for i in range(n):
        ident = crypto.Identity.generate()
        m = prof.profile_manifest(ident, prof.make_profile(f"nr {i}"), pow_bits=BITS)
        node.accept(m.to_bytes())
        out.append((ident, m))
    return out


async def connect(addr) -> Client:
    c = await Client.connect(addr)
    await c.fetch_capabilities()
    return c


async def test_answers_in_order_with_every_kind():
    node = make_node()
    (a, ma), (b, mb) = profiles(node, 2)
    server, addr = await serve(node)
    c = await connect(addr)
    try:
        assert c.capability("UNSEENET-MANIFESTS") == str(MANIFESTS_MAX)
        nobody = prof.profile_id(crypto.Identity.generate().public_key)
        answers = await c.manifests([(ma.group, ma.message_id), (nobody, None), (mb.group, None)])
        assert [(x.code, x.group_id) for x in answers] == [
            (223, ma.group), (411, nobody), (220, mb.group)]
        assert answers[0].raw is None and answers[0].message_id == ma.message_id
        assert answers[2].raw == node.store.get(mb.message_id)     # byte-for-byte
        assert b"Path:" not in answers[2].raw and b"Xref:" not in answers[2].raw
        held_old = await c.manifests([(ma.group, "<old@x>")])        # not current: sent
        assert held_old[0].code == 220
        assert (await c.article(mb.message_id)) is not None         # connection in step
    finally:
        await c.quit()
        server.close()


async def test_bad_requests_are_refused_whole():
    node = make_node()
    [(a, ma)] = profiles(node, 1)
    server, addr = await serve(node)
    c = await connect(addr)
    try:
        for entries in ([(ma.group, None), (ma.group, None)],                  # twice
                        [(f"g{i}", None) for i in range(MANIFESTS_MAX + 1)]):  # too many
            with pytest.raises(NNTPError) as err:
                await c.manifests(entries)
            assert err.value.code == 501
        with pytest.raises(NNTPError) as err:
            await c.manifests([(ma.group, "not-a-message-id")])
        assert err.value.code == 501
        assert (await c.manifests([(ma.group, None)]))[0].code == 220   # still usable
    finally:
        await c.quit()
        server.close()


async def test_size_limit_and_asking_again(monkeypatch):
    node = make_node()
    made = profiles(node, 5)
    size = len(node.store.get(made[0][1].message_id))
    monkeypatch.setattr(srv, "MANIFESTS_ANSWER_BYTES", size * 2 + size // 2)  # two fit
    server, addr = await serve(node)
    c = await connect(addr)
    try:
        answers = await c.manifests([(m.group, None) for _, m in made])
        assert [x.code for x in answers] == [220, 220, 431, 431, 431]
        everything = await c.manifests_all([(m.group, None) for _, m in made])
        assert {g: x.code for g, x in everything.items()} == {m.group: 220 for _, m in made}
        monkeypatch.setattr(srv, "MANIFESTS_ANSWER_BYTES", 1)        # one is always sent
        assert [x.code for x in await c.manifests([(made[0][1].group, None)] * 1)] == [220]
    finally:
        await c.quit()
        server.close()


async def test_readers_are_rate_limited(monkeypatch):
    monkeypatch.setattr(srv.Session, "MANIFESTS_PER_MINUTE", 2)
    node = make_node()
    [(a, ma)] = profiles(node, 1)
    server, addr = await serve(node)
    c = await connect(addr)
    try:
        for _ in range(2):
            await c.manifests([(ma.group, None)])
        with pytest.raises(NNTPError) as err:
            await c.manifests([(ma.group, None)])
        assert err.value.code == 400
    finally:
        await c.quit()
        server.close()


async def test_peer_fetches_a_missing_manifest_in_one_request(monkeypatch):
    """UN-RFC 0041 section 4.3: an article in a key-bound group whose manifest we lack."""
    a = make_node("a")
    owner, sender = crypto.Identity.generate(), crypto.Identity.generate()
    m = make_manifest(owner, "inbox", "inbox", pow_bits=BITS)
    a.accept(m.to_bytes())
    msg = inbox_article(m.group, owner.public_key, from_name="s", subject="hej", body="b",
                        sender=sender, pow_bits=BITS)
    a.accept(msg.to_bytes())
    capability = pulling.Client.capability
    monkeypatch.setattr(pulling.Client, "capability",
                        lambda self, name: None if name == "UNSEENET-RECONCILE"
                        else capability(self, name))

    async def no_group(self, group_id):
        raise AssertionError("GROUP used although the peer has XUN-MANIFESTS")
    monkeypatch.setattr(pulling.Client, "group", no_group)
    server, addr = await serve(a)
    try:
        b = make_node("b", peers=[PeerConfig(name="a", address=addr)])
        await Puller(b, b.config.peers[0])._fetch_manifest(
            await connect(addr), msg.to_bytes(), {"fetched": 0, "accepted": 0})
        assert b.store.known_group(m.group)
    finally:
        server.close()


# --- clients --------------------------------------------------------------------

def session(tmp_path, name, addr):
    s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity(name, name.title())
    s.add_node(addr)
    return s


async def test_prefetch_reads_all_authors_in_one_request(tmp_path, monkeypatch):
    node = make_node()
    made = profiles(node, 40)
    server, addr = await serve(node)
    reader = session(tmp_path, "reader", addr)
    calls = []
    real = Client.manifests

    async def counting(self, entries):
        calls.append(len(entries))
        return await real(self, entries)
    monkeypatch.setattr(Client, "manifests", counting)

    async def no_group(self, group_id):
        raise AssertionError("single lookup used")
    monkeypatch.setattr(Client, "group", no_group)
    try:
        nobody = crypto.Identity.generate().key_text
        keys = [i.key_text for i, _ in made] + [nobody]
        assert await reader.prefetch_profiles(keys) == 41
        assert calls == [41]
        assert (await reader.profile_of(made[7][0].key_text)).about == "nr 7"   # cached
        assert await reader.profile_of(nobody) is None                          # cached too
        assert await reader.prefetch_profiles(keys) == 0 and calls == [41]      # fresh
        reader.hide_profile(made[0][0].key_text)
        reader._profile_cache().clear()
        assert await reader.prefetch_profiles(keys) == 40                      # hidden skipped
    finally:
        await reader.close()
        server.close()


async def test_falls_back_to_single_lookups_without_the_command(tmp_path, monkeypatch):
    node = make_node()
    made = profiles(node, 3)
    server, addr = await serve(node)
    capability = Client.capability
    monkeypatch.setattr(Client, "capability", lambda self, name: None
                        if name == "UNSEENET-MANIFESTS" else capability(self, name))

    async def no_batch(self, entries):
        raise AssertionError("XUN-MANIFESTS used without the capability")
    monkeypatch.setattr(Client, "manifests", no_batch)
    reader = session(tmp_path, "reader", addr)
    try:
        found = await reader.fetch_manifests([m.group for _, m in made])
        assert {g: x.message_id for g, x in found.items()} == {m.group: m.message_id
                                                                for _, m in made}
    finally:
        await reader.close()
        server.close()


async def test_a_forged_manifest_is_not_taken(tmp_path, monkeypatch):
    """Section 3.1: a node is not trusted - a tampered article fails its signature."""
    node = make_node()
    [(a, ma)] = profiles(node, 1)
    server, addr = await serve(node)
    real = Client.manifests

    async def tampering(self, entries):
        out = await real(self, entries)
        for x in out:
            if x.raw:
                x.raw = x.raw.replace(b"nr 0", b"nr 9")
        return out
    monkeypatch.setattr(Client, "manifests", tampering)
    reader = session(tmp_path, "reader", addr)
    try:
        assert (await reader.fetch_manifests([ma.group]))[ma.group] is None
    finally:
        await reader.close()
        server.close()


async def test_cache_never_steps_back_to_an_older_serial(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = make_node()
    server, addr = await serve(node)
    me, reader = session(tmp_path, "me", addr), session(tmp_path, "reader", addr)
    try:
        ident = me.identity()
        old = prof.profile_manifest(ident, prof.make_profile("gammel"), pow_bits=BITS)
        await me.publish_profile(prof.make_profile("ny"))
        await me.publish_profile(prof.make_profile("nyere"))        # serial 2
        key = ident.key_text
        assert (await reader.profile_of(key)).about == "nyere"
        reader._cache_profile(key, Manifest.from_article(old), 0)    # a node serving serial 1
        assert reader._profile_cache()[key]["profile"]["about"] == "nyere"
    finally:
        for s in (me, reader):
            await s.close()
        server.close()
