"""#181: a client knows before writing whether it may, and says why."""

from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Permission, Session, SessionError
from unseenet.core.groups import KIND_CHAT, KIND_POST
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig


@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    made = []

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", ops=1, mem=8192 * 1024),
                    status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        made.append(s)
        return s
    yield session
    for s in made:
        await s.close()
    server.close()


async def refused(s, gid, **kw) -> bool:
    try:
        await s.post(gid, kw.pop("subject", "Hej"), "tekst\n", **kw)
    except SessionError:
        return True
    return False


async def test_unknown_group_and_own_inbox(net):
    me = net("me")
    assert me.write_permission("dk.nowhere") == Permission(True)
    p = me.write_permission(me.my_inbox)
    assert not p and p.code == "own_inbox" and "contact" in p.reason


async def test_kinds_say_which_kind(net):
    owner = net("owner")
    gid = await owner.create_group("dk.snak", "open", min_pow=10, kinds=["chat"])
    p = owner.write_permission(gid, kind=KIND_POST)
    assert not p and p.code == "kind" and "chat lines only" in p.reason
    assert owner.write_permission(gid, kind=KIND_CHAT)
    assert owner.may_post(gid)                       # any kind: yes


async def test_banned_user_is_told_before_writing(net):
    owner, troll = net("owner"), net("troll")
    gid = await owner.create_group("dk.snak", "open", min_pow=10)
    troll.subscribe(gid)
    await troll.fetch_group(gid)
    assert troll.write_permission(gid)
    await owner.ban(gid, troll.identity().key_text, "trusler")
    await troll.fetch_group(gid)
    p = troll.write_permission(gid, kind=KIND_CHAT)
    assert not p and p.code == "banned" and p.reason.endswith(": trusler")
    assert await refused(troll, gid)                  # the node agrees


async def test_channel_threads_comments_and_comment_days(net):
    owner, reader = net("owner"), net("reader")
    gid = await owner.create_group("news.daily", "channel", min_pow=10)
    await owner.post(gid, "Today", "Something happened\n")
    reader.subscribe(gid)
    root = (await reader.fetch_group(gid))[0]
    p = reader.write_permission(gid, kind=KIND_CHAT)
    assert not p and p.code == "channel" and "posters" in p.reason
    assert not reader.write_permission(gid, reply_to=root)

    await owner.update_group(gid, comments="open", comment_days=7)
    await reader.fetch_group(gid)
    assert reader.write_permission(gid, kind=None).code == "channel_thread"
    assert reader.write_permission(gid, reply_to=root)
    assert reader.may_reply(gid) and reader.may_reply(gid, root) and not reader.may_post(gid)
    later = datetime.now(timezone.utc) + timedelta(days=8)
    p = reader.write_permission(gid, reply_to=root, now=later)
    assert not p and p.code == "comments_closed"
    assert owner.write_permission(gid, reply_to=root, now=later)   # the owner always


async def test_closed_group_needs_membership(net):
    owner, outsider = net("owner"), net("outsider")
    gid = await owner.create_group("dk.hemmelig", "closed", min_pow=10)
    assert owner.write_permission(gid)
    outsider.subscribe(gid)
    await outsider.fetch_group(gid)
    p = outsider.write_permission(gid)
    assert not p and p.code == "not_member"


def test_permission_is_falsy_when_not_allowed():
    assert not Permission(False, "nej", "x") and Permission(True)
