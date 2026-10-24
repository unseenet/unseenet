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


async def _setup(tmp_path, monkeypatch, **node_config):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), **node_config))
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


async def test_a_group_created_and_edited_with_a_files_choice(tmp_path, monkeypatch):
    """#496: ``files`` when creating a group and in its settings (UN-RFC 0046 4.7)."""
    from unseenet.core import blobs as bl
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.create_group({"name": "dk.foto", "type": "open", "files": "pictures"}))["id"]
    assert owner.manifest_data(gid)["attachments"] == bl.PICTURES
    assert api.group(gid)["group"]["files"]
    await api.group_settings(gid, {"files": "pictures+pdf"})
    assert owner.manifest_data(gid)["attachments"] == bl.PICTURES_AND_PDF
    await api.group_settings(gid, {"files": "none"})
    assert "attachments" not in owner.manifest_data(gid)
    with pytest.raises(SessionError, match="files is none"):
        await api.create_group({"name": "dk.x", "type": "open", "files": "everything"})
    await owner.close()
    await other.close()
    server.close()


async def test_create_a_feed_and_a_site(tmp_path, monkeypatch):
    """A group created as a feed or a site (UN-RFC 0034 3.2, 0035 3; UN-RFC 0046 4.7)."""
    server, owner, other, api = await _setup(tmp_path, monkeypatch, sites="accept")
    feed = (await api.create_group({"name": "dk.nyheder", "type": "channel", "view": "feed"}))["id"]
    data = owner.manifest_data(feed)
    assert data["view"] == "feed" and data["comments"] == "open"     # a feed takes comments
    shared = (await api.create_group({"name": "dk.faelles", "type": "open", "view": "feed"}))["id"]
    assert owner.manifest_data(shared)["view"] == "feed"
    site = (await api.create_group({"name": "dk.side", "type": "channel", "view": "pages"}))["id"]
    assert owner.manifest_data(site)["view"] == "pages"
    with pytest.raises(SessionError, match="a site is a channel"):
        await api.create_group({"name": "dk.forkert", "type": "open", "view": "pages"})
    with pytest.raises(SessionError, match="view is"):
        await api.create_group({"name": "dk.forkert", "type": "open", "view": "slides"})
    await owner.close()
    await other.close()
    server.close()
