"""Client session against a local node: open and closed groups, invites, read marks."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def test_closed_group_invite_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    a, b, c = session("andreas"), session("sonia"), session("outsider")
    fam = await a.create_group("familie", "closed", min_pow=10)
    await a.invite(fam, b.identity().key_text)
    await a.post(fam, "Hemmeligt", "Kun for familien\n")

    for s in (b, c):
        s.subscribe(fam)
    got_b = await b.fetch_group(fam)
    got_c = await c.fetch_group(fam)
    assert [m.body for m in got_b] == ["Kun for familien\n"]
    assert got_c and not got_c[0].readable and "Kun" not in got_c[0].body

    # b can post back; own posts count as read, others' do not
    await b.post(fam, "Re: Hemmeligt", "Fint!\n", references=[got_b[0].message_id])
    msgs = await b.fetch_group(fam)
    assert b.unread_count(fam) == 1
    assert msgs[-1].references == [got_b[0].message_id]

    # an outsider cannot post into the closed group
    c.group_entry(fam)["keys"] = {}
    try:
        await c.post(fam, "spam", "spam")
        raise AssertionError("outsider could post")
    except sess.SessionError:
        pass

    for s in (a, b, c):
        await s.close()
    server.close()


async def test_offline_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    a = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    a.new_identity("a", "A"); a.add_node(addr)
    b = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    b.new_identity("b", "B"); b.add_node(addr)
    open_g = await a.create_group("dk.snak", "open", min_pow=10)
    closed = await a.create_group("familie", "closed", min_pow=10)
    await a.invite(closed, b.identity().key_text)
    await a.post(open_g, "Offentligt", "Alle kan læse\n")
    await a.post(closed, "Hemmeligt", "Kun familien\n")
    b.subscribe(open_g); b.subscribe(closed)
    await b.fetch_group(open_g); await b.fetch_group(closed)
    await b.close(); await a.close()
    server.close(); await server.wait_closed()

    # the cache file is encrypted
    blob = (tmp_path / "b.vault.cache").read_bytes()
    assert b"Kun familien" not in blob and b"Alle kan" not in blob
    assert oct((tmp_path / "b.vault.cache").stat().st_mode & 0o777) == "0o600"

    # node is gone: everything is still readable from the cache
    again = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    assert again.load_offline() == 2
    bodies = {m.subject: m.body for g in again.cache.values() for m in g.values()}
    assert bodies == {"Offentligt": "Alle kan læse\n", "Hemmeligt": "Kun familien\n"}
    try:
        await again.fetch_group(open_g)
        raise AssertionError("node should be unreachable")
    except (OSError, ConnectionError):
        pass
    assert again.cache[open_g]          # cache untouched by the failed fetch

    # a cache made for another node is ignored (article numbers are per node)
    other = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    other.data["nodes"] = ["127.0.0.1:1"]
    assert other.load_offline() == 0


def test_signatures(tmp_path):
    from unseenet.client.session import split_signature
    assert split_signature("Hej\n-- \nAndreas\n") == ("Hej\n", "Andreas\n")
    assert split_signature("Hej\n--\nikke en signatur\n") == ("Hej\n--\nikke en signatur\n", None)
    assert split_signature("a\n-- \nfirst\n-- \nlast\n") == ("a\n-- \nfirst\n", "last\n")

    s = Session(Vault.open(tmp_path / "s.vault", "pw", **KDF), status=lambda *_: None)
    ident = s.new_identity("a", "Andreas")
    assert s.signature() == ""
    s.set_signature("{name} ({fp})\n{key}")
    assert s.signature() == f"Andreas ({ident.fingerprint[:4]})\n{ident.key_text}"
    try:
        s.set_signature("1\n2\n3\n4\n5")
        raise AssertionError("five lines accepted")
    except sess.SessionError:
        pass


async def test_group_rules_and_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    owner, reader = session("owner"), session("reader")
    gid = await owner.create_group("dk.snak", "open", title="Snak", rules="Vær søde ved hinanden.",
                                   min_pow=10)
    reader.subscribe(gid)
    await reader.fetch_group(gid)
    assert reader.manifest_data(gid)["rules"] == "Vær søde ved hinanden."
    assert reader.rules_unseen(gid)
    reader.mark_rules_seen(gid)
    assert not reader.rules_unseen(gid)

    # only the owner can change it; a change raises the serial and shows the rules again
    with pytest.raises(sess.SessionError):
        await reader.update_group(gid, rules="hacked")
    new = await owner.update_group(gid, rules="Vær søde. Ingen reklamer.", view="chat")
    assert new["serial"] == 2 and new["type"] == "open" and new["title"] == "Snak"
    await reader.fetch_group(gid)
    assert reader.manifest_data(gid)["rules"] == "Vær søde. Ingen reklamer."
    assert reader.manifest_data(gid)["view"] == "chat" and reader.rules_unseen(gid)
    with pytest.raises(sess.SessionError):
        await owner.update_group(gid, type="closed")      # type can never change

    # postage follows the group: a cheap chat group, a node with its own minimum
    chat = await owner.create_group("chat.venner", "open", view="chat", low_latency=True, min_pow=9)
    assert await owner.required_pow(chat) == 9
    assert await owner.required_pow(gid) == 10
    for s in (owner, reader):
        await s.close()
    server.close()


async def test_post_without_cached_manifest_meets_group_postage(tmp_path, monkeypatch):
    """A group joined before manifests were cached (or whose manifest was never
    fetched) must still get enough postage: the group asks more than the node."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    owner, reader = session("owner"), session("reader")
    gid = await owner.create_group("strict", "open", min_pow=11)
    reader.subscribe(gid)
    await reader.fetch_group(gid)
    reader.data["groups"][gid].pop("manifest", None)   # as in an older vault
    await reader.post(gid, "Hej", "Det virker\n")
    assert int(reader.manifest_data(gid)["min_pow"]) == 11   # learned from the node
    await reader.post(gid, "Igen", "Og nu i første forsøg\n")
    bodies = [m.body for m in await owner.fetch_group(gid)]
    assert "Det virker\n" in bodies and "Og nu i første forsøg\n" in bodies
    for s in (owner, reader):
        await s.close()
    server.close()


async def test_old_vault_learns_manifest_and_rules(tmp_path, monkeypatch):
    """A vault from before manifests were cached rereads the group once and so
    learns its rules; the owner can then edit them."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    s = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("owner", "Owner")
    s.add_node(addr)
    gid = await s.create_group("rules", "open", min_pow=8)
    await s.post(gid, "Hej", "Første\n")
    await s.fetch_group(gid)
    entry = s.data["groups"][gid]
    entry.pop("manifest", None)                      # as in an older vault
    assert not s.manifest_data(gid)
    await s.fetch_group(gid)
    assert s.manifest_data(gid).get("serial")
    await s.update_group(gid, rules="Vær søde ved hinanden")
    assert s.manifest_data(gid)["rules"] == "Vær søde ved hinanden"
    await s.close()
    server.close()
