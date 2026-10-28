"""#728: opening a vault and listing its groups stay quick with large groups - the offline
cache is not checked again, and For you is not gone through once per group."""

import json

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core import article as art_mod
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def _reader(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    a = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    a.new_identity("a", "A"); a.add_node(addr)
    b = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    b.new_identity("b", "B"); b.add_node(addr)
    gid = await a.create_group("dk.snak", "open", min_pow=10)
    for i in range(3):
        await a.post(gid, f"Indlæg {i}", "tekst\n")
    b.subscribe(gid)
    await b.fetch_group(gid)
    return server, a, b, gid


async def test_the_offline_cache_is_not_checked_again(tmp_path, monkeypatch):
    server, a, b, gid = await _reader(tmp_path, monkeypatch)
    n = max(b._raw[gid])                              # one article that did not pass
    b.cache[gid][n] = sess.Message(n, f"<invalid-{n}>", gid, readable=False, error="bad")
    b.save_offline()
    await b.close(); await a.close(); server.close()

    payload = json.loads(Vault.open(tmp_path / "b.vault", "pw", **KDF).read_sidecar(sess.CACHE_SIDECAR))
    assert payload["v"] == 3
    assert str(n) not in payload["groups"][gid]["articles"]     # never kept

    checks = []
    real = art_mod.validate_structure
    monkeypatch.setattr("unseenet.client.session.reading.validate_structure",
                        lambda *x, **k: checks.append(1) or real(*x, **k))
    again = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    assert again.load_offline() >= 2
    assert checks == []                                # a version 3 cache: not checked again
    assert {m.subject for m in again.cache[gid].values()} >= {"Indlæg 0", "Indlæg 1"}


async def test_an_older_cache_is_still_checked(tmp_path, monkeypatch):
    server, a, b, gid = await _reader(tmp_path, monkeypatch)
    b.save_offline()
    await b.close(); await a.close(); server.close()
    v = Vault.open(tmp_path / "b.vault", "pw", **KDF)
    payload = json.loads(v.read_sidecar(sess.CACHE_SIDECAR))
    payload["v"] = 2
    v.write_sidecar(sess.CACHE_SIDECAR, json.dumps(payload).encode())

    checks = []
    real = art_mod.validate_structure
    monkeypatch.setattr("unseenet.client.session.reading.validate_structure",
                        lambda *x, **k: checks.append(1) or real(*x, **k))
    again = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    assert again.load_offline() >= 3
    assert len(checks) >= 3


async def test_listing_groups_asks_for_quiet_once(tmp_path, monkeypatch):
    server, a, b, gid = await _reader(tmp_path, monkeypatch)
    for i in range(2):
        b.subscribe(await a.create_group(f"dk.g{i}", "open", min_pow=10))
    asked = []
    real = Session.for_you_quiet
    monkeypatch.setattr(Session, "for_you_quiet", lambda self: asked.append(1) or real(self))
    groups = b.subscribed_groups()
    assert len(groups) >= 3 and len(asked) == 1
    assert real(b) == set()                                        # no [foryou] rules: none
    await b.close(); await a.close(); server.close()
