"""Client session against a local node: open and closed groups, invites, read marks."""

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
