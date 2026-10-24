"""#442: pinned posts in the local client API (UN-RFC 0046 section 4.12, UN-RFC 0033),
against a real node: the pins in a group's head and on its rows, pinning and unpinning
by the owner, refusing everyone else, and warning before a post beyond the window goes."""
from datetime import datetime, timedelta, timezone

import pytest

from unseenet.client.localapi import LocalAPI, NotFound
from unseenet.client.localapi import server as srv
from unseenet.client.session import SessionError

from test_localapi_owner import _setup


def _row(group, mid):
    return next(r for r in group["rows"] if r["message"]["id"] == mid)


async def test_pin_and_unpin_as_the_owner(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.create_group({"name": "dk.pins", "type": "open"}))["id"]
    mid = await owner.post(gid, "Velkommen", "Læs denne først\n")
    later = await owner.post(gid, "Noget andet", "tekst\n")
    await owner.fetch_group(gid)

    g = api.group(gid)
    assert g["group"]["pins"] == [] and g["group"]["max_pins"] == 5 and g["group"]["may_pin"]
    assert _row(g, mid)["pinned"] is False

    done = await api.pin(gid, {"id": mid, "note": "Til nye"})
    assert done["ok"] and done["marker"].startswith("<")
    [p] = done["pins"]
    assert p["id"] == mid and p["note"] == "Til nye" and p["subject"] == "Velkommen"
    assert p["by"] == owner.identity().key_text and p["who"] and p["beyond_window"] is False
    g = api.group(gid)
    assert [p["id"] for p in g["group"]["pins"]] == [mid]
    assert _row(g, mid)["pinned"] is True and _row(g, later)["pinned"] is False

    await api.pin(gid, {"id": later})       # the order is core.pins.in_force's (test_pins.py):
    assert {p["id"] for p in api.group(gid)["group"]["pins"]} == {later, mid}   # same second here

    await api.pin(gid, {"id": mid, "unpin": True})
    g = api.group(gid)
    assert [p["id"] for p in g["group"]["pins"]] == [later] and _row(g, mid)["pinned"] is False
    with pytest.raises(SessionError, match="not pinned"):
        await api.pin(gid, {"id": mid, "unpin": True})
    with pytest.raises(SessionError):
        await api.pin(gid, {"id": ""})
    with pytest.raises(ValueError):                         # a note is at most 256 characters
        await api.pin(gid, {"id": mid, "note": "x" * 300})
    with pytest.raises(NotFound):
        await api.pin("dk.nope@aaaaaaaa", {"id": mid})
    await owner.close()
    await other.close()
    server.close()


async def test_only_the_owner_and_moderators_pin(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.create_group({"name": "dk.ejet", "type": "open"}))["id"]
    mid = await owner.post(gid, "Velkommen", "tekst\n")
    other.subscribe(gid)
    await other.fetch_group(gid)
    theirs = LocalAPI(session=other)
    assert theirs.group(gid)["group"]["may_pin"] is False
    with pytest.raises(SessionError, match="owner or a moderator"):
        await theirs.pin(gid, {"id": mid})

    await api.role(gid, {"role": "moderators", "key": other.identity().key_text})
    await other.fetch_group(gid)
    assert theirs.group(gid)["group"]["may_pin"] is True
    await theirs.pin(gid, {"id": mid})
    await owner.fetch_group(gid)
    assert [p["id"] for p in api.group(gid)["group"]["pins"]] == [mid]
    await owner.close()
    await other.close()
    server.close()


async def test_a_pin_beyond_the_window_is_marked(tmp_path, monkeypatch):
    """Unpinning a post older than the group keeps posts removes it at once
    (UN-RFC 0033 section 7.1): the answer says so, for a client to warn first."""
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.create_group({"name": "dk.kort", "type": "open"}))["id"]
    await api.group_settings(gid, {"retention_days": 1})
    mid = await owner.post(gid, "Gammel", "tekst\n")
    await owner.fetch_group(gid)
    await api.pin(gid, {"id": mid})
    m = next(x for x in owner.cache[gid].values() if x.message_id == mid)
    m.date = datetime.now(timezone.utc) - timedelta(days=3)
    assert api.group(gid)["group"]["pins"][0]["beyond_window"] is True
    await owner.close()
    await other.close()
    server.close()


def test_the_route():
    assert ("POST", "/api/groups/{gid}/pin") in [(m, p) for m, p, _ in srv.ROUTES]
