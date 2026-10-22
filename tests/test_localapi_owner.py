"""The local API's tools for owners and moderators, against a real node.

Moved from unseenet-gui's tests (unseenet-gui#38): the GUI now uses these."""

import pytest

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI, NotFound
from unseenet.client.session import Session, SessionError
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    owner, other = session("owner"), session("other")
    await owner.ensure_inbox()
    await other.ensure_inbox()
    return server, owner, other, LocalAPI(session=owner)


async def test_settings_ban_roles_withdraw_and_moderate(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.create_group({"name": "dk.test", "type": "open"}))["id"]
    await api.group_settings(gid, {"title": "Om test", "kinds": "post"})
    head = api.group(gid)["group"]
    assert head["title"] == "Om test" and head["kinds"] == ["post"]

    key = other.identity().key_text
    await api.ban(gid, {"key": key, "reason": "spam"})
    assert [(b["key"], b["reason"]) for b in api.group(gid)["group"]["roles"]["banned"]] == [(key, "spam")]
    await api.ban(gid, {"key": key, "on": False})
    await api.role(gid, {"role": "moderators", "key": key})
    assert [p["key"] for p in api.group(gid)["group"]["roles"]["moderators"]] == [key]
    with pytest.raises(SessionError):
        await api.role(gid, {"role": "kings", "key": key})

    msgid = await owner.post(gid, "Et indlæg", "tekst\n")
    await owner.fetch_group(gid)
    await api.withdraw(gid, msgid)
    with pytest.raises(NotFound):
        await api.withdraw(gid, "<nope@unseenet>")

    # a moderated group: a submission waits for the owner, who approves it
    mod = (await api.create_group({"name": "dk.moderated", "type": "moderated"}))["id"]
    other.subscribe(mod)
    await other.fetch_group(mod)
    await other.post(mod, "Må jeg?", "Et forslag\n")
    waiting = (await api.moderation())["waiting"]
    assert [w["subject"] for w in waiting] == ["Må jeg?"] and waiting[0]["tree"]
    await api.moderate({"id": waiting[0]["id"], "approve": True})
    assert (await api.moderation())["waiting"] == []
    assert "Må jeg?" in [m.subject for m in owner.cache[mod].values()]

    with pytest.raises(SessionError):
        await api.remove_group(gid, {})                          # confirm first
    await api.remove_group(gid, {"confirm": "remove"})
    assert gid not in owner.data["groups"]
    await owner.close()
    await other.close()
    server.close()


async def test_ignore_names_and_members(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    key = other.identity().key_text

    api.ignore({"key": key, "label": "Other"})
    assert [p["key"] for p in api.ignored()["ignored"]] == [key]
    api.ignore({"key": key, "on": False})
    assert api.ignored()["ignored"] == []

    data = await api.names()                       # no registrar here: nothing, but no error
    assert data["mine"] == [] and data["parents"] == [] and data["key"] == owner.identity().key_text
    with pytest.raises(ValueError):
        await api.name_action({"action": "claim", "name": "NOT A NAME"})

    gid = (await api.create_group({"name": "dk.lukket", "type": "closed"}))["id"]
    await api.invite(gid, {"key": key})
    assert key in owner.members(gid)
    assert [m["key"] for m in api.group(gid)["group"]["roles"]["members"] if m["key"] == key] == [key]
    epoch = (await api.remove_member(gid, {"key": key}))["epoch"]
    assert epoch >= 2 and key not in owner.members(gid)
    assert api.group(gid)["group"]["roles"]["maintainer"] is False
    await owner.close()
    await other.close()
    server.close()
