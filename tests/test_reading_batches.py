"""Reading a group in turns (#721): the node is free between them, and a large group read
for the first time comes newest first, older articles with later refreshes."""

import asyncio

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.nntp import Client
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def _net(tmp_path, monkeypatch, posts: int):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    monkeypatch.setattr(Session, "FETCH_BATCH", 3)
    monkeypatch.setattr(Session, "NEW_GROUP_WINDOW", 5)
    monkeypatch.setattr(Session, "OLDER_BATCH", 4)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    owner = session("owner")
    gid = await owner.create_group("stor", "open", min_pow=10)
    for i in range(posts):
        await owner.post(gid, f"Indlæg {i}", f"tekst {i}\n")
    return server, owner, session("reader"), gid


async def test_the_node_is_free_between_turns(tmp_path, monkeypatch):
    server, owner, reader, gid = await _net(tmp_path, monkeypatch, 8)
    monkeypatch.setattr(Session, "NEW_GROUP_WINDOW", 100)       # everything in one read
    article = Client.article

    async def slow(self, n):
        await asyncio.sleep(0.02)
        return await article(self, n)
    monkeypatch.setattr(Client, "article", slow)

    reader.subscribe(gid)
    done = []

    async def other():                       # what the GUI asks meanwhile (emoji, pictures)
        await asyncio.sleep(0.05)
        await reader._call(lambda c: c.group(gid))
        done.append("other")

    async def read():
        await reader.fetch_group(gid)
        done.append("read")

    await asyncio.gather(read(), other())
    assert done == ["other", "read"]         # it got in before the read was over
    assert len(reader.cache[gid]) == 8
    for s in (owner, reader):
        await s.close()
    server.close()


async def test_a_large_group_comes_newest_first(tmp_path, monkeypatch):
    server, owner, reader, gid = await _net(tmp_path, monkeypatch, 12)
    reader.subscribe(gid)

    first = await reader.fetch_group(gid)
    assert [m.subject for m in first] == [f"Indlæg {i}" for i in range(7, 12)]   # the newest 5
    assert reader.group_entry(gid).get("manifest")       # settings known from the start
    assert reader.group_entry(gid).get("older")

    second = await reader.fetch_group(gid)               # 4 older ones each time
    assert [m.subject for m in second] == [f"Indlæg {i}" for i in range(3, 12)]
    third = await reader.fetch_group(gid)
    assert [m.subject for m in third] == [f"Indlæg {i}" for i in range(12)]
    assert not reader.group_entry(gid).get("older")       # all here

    await owner.post(gid, "Nyt", "nyt\n")                 # new ones still come as before
    assert (await reader.fetch_group(gid))[-1].subject == "Nyt"
    for s in (owner, reader):
        await s.close()
    server.close()


async def test_a_small_group_is_read_whole(tmp_path, monkeypatch):
    server, owner, reader, gid = await _net(tmp_path, monkeypatch, 4)
    reader.subscribe(gid)
    got = await reader.fetch_group(gid)
    assert [m.subject for m in got] == [f"Indlæg {i}" for i in range(4)]
    assert not reader.group_entry(gid).get("older")
    for s in (owner, reader):
        await s.close()
    server.close()
