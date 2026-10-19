"""#13: search and filter the group list, locally."""

import pytest

import unseenet.client.session as sess
from unseenet.client import groupfilter as gf
from unseenet.client.session import GroupInfo, Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

FP_ME, FP_OTHER = "aaaa", "bbbb"


def m(f, gid, **kw):
    kw.setdefault("my_fingerprints", (FP_ME,))
    return gf.matches(gf.parse(f), gid, **kw)


def test_parse_understands_filters_and_words():
    f = gf.parse("Marsvin type:CHAT type:closed owner:me subscribed dk.* type:nonsense owner:sonia")
    assert f.words == ["marsvin"] and f.types == {"chat", "closed"} and f.owner_me
    assert f.subscribed is True and f.patterns == ["dk.*"]
    assert f.unknown == ["type:nonsense", "owner:sonia"] and f.needs_manifests
    assert not gf.parse("   ") and gf.parse("-subscribed").subscribed is False
    assert gf.parse("http://x.onion").words == ["http://x.onion"]     # not a filter


def test_words_match_name_title_and_description_in_any_case():
    gid = f"dk.snak.marsvin@{FP_OTHER}"
    assert m("marsvin", gid)
    assert m("gnavere", gid, data={"title": "Om GNAVERE"})
    assert m("hø", gid, description="hø og strå")
    assert not m("marsvin kanin", gid)                     # every word must match


def test_type_owner_subscribed_and_hierarchy():
    gid = f"dk.snak@{FP_ME}"
    assert m("type:open", gid, gtype="open") and not m("type:closed", gid, gtype="open")
    assert not m("type:open", gid)                          # unknown type: no match
    assert m("type:chat", gid, data={"type": "open", "view": "chat"})
    assert m("type:chat", gid, data={"type": "open", "kinds": ["chat"]})
    assert m("type:local", gid, data={"type": "open", "local": True})
    assert m("type:channel type:open", gid, gtype="open")  # any of them
    assert m("owner:me", gid) and not m("owner:me", f"dk.snak@{FP_OTHER}")
    assert m("subscribed", gid, subscribed=True) and not m("subscribed", gid)
    assert m("-subscribed", gid) and not m("-subscribed", gid, subscribed=True)
    assert m("dk.*", gid) and not m("alt.*", gid) and m("*.snak", gid)
    assert m("DK.* snak", gid)


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


async def test_types_of_groups_you_do_not_follow_come_in_one_request(net, monkeypatch):
    owner, reader = net("owner"), net("reader")
    chat = await owner.create_group("dk.snak", "open", min_pow=10, view="chat")
    news = await owner.create_group("dk.nyheder", "channel", min_pow=10)
    secret = await owner.create_group("dk.hemmelig", "closed", min_pow=10)
    groups = [g for g in await reader.list_groups() if g.group_id in (chat, news, secret)]
    assert len(groups) == 3 and not any(g.type for g in groups)
    calls = []
    real = sess.Client.manifests

    async def counting(self, entries):
        calls.append(len(entries))
        return await real(self, entries)
    monkeypatch.setattr(sess.Client, "manifests", counting)
    known: dict = {}
    assert await reader.group_manifests(groups, known) == 3 and calls == [3]
    assert [g.group_id for g in reader.filter_groups(groups, "type:chat", known)] == [chat]
    assert [g.group_id for g in reader.filter_groups(groups, "type:channel", known)] == [news]
    assert {g.group_id for g in reader.filter_groups(groups, "dk.*", known)} == {chat, news, secret}
    assert reader.filter_groups(groups, "owner:me", known) == []
    assert len(owner.filter_groups(groups, "owner:me", known)) == 3
    assert await reader.group_manifests(groups, known) == 0 and calls == [3]   # once


async def test_search_needs_no_whole_group_reads_on_old_nodes(net, monkeypatch):
    owner, reader = net("owner"), net("reader")
    await owner.create_group("dk.snak", "open", min_pow=10)
    groups = [g for g in await reader.list_groups() if g.group_id.startswith("dk.snak@")]
    capability = sess.Client.capability
    monkeypatch.setattr(sess.Client, "capability", lambda self, name: None
                        if name == "UNSEENET-MANIFESTS" else capability(self, name))

    async def no_group(self, gid):
        raise AssertionError("read a whole group to learn its type")
    monkeypatch.setattr(sess.Client, "group", no_group)
    known: dict = {}
    await reader.group_manifests(groups, known)
    assert known == {groups[0].group_id: {}}            # unknown, and not asked again
