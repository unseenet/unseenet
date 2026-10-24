"""Reactions in the local client API (UN-RFC 0046, UN-RFC 0048): the set in a group's
head, the counts and ``react`` on every row, and reacting as a job."""
import asyncio

import pytest

from unseenet.client.session import SessionError

from test_localapi_owner import _setup


def _row(group, mid):
    return next(r for r in group["rows"] if r["message"]["id"] == mid)


async def _until(check, seconds=10.0):
    for _ in range(int(seconds * 20)):
        if check():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_reactions_on_rows_and_reacting(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.create_group({"name": "dk.noter", "type": "open"}))["id"]
    await api.group_settings(gid, {"view": "feed"})
    mid = await owner.post(gid, "Hej", "tekst\n")
    await owner.fetch_group(gid)
    g = api.group(gid)
    assert g["group"]["reactions"] == {"offered": ["👍", "👎", "❤️", "😂", "😮", "😢"],
                                       "any": False}
    row = _row(g, mid)
    assert row["reactions"] == [] and row["react"]["allowed"]

    job = api.react(gid, {"id": mid, "emoji": "👍"})
    assert job["job"]
    assert await _until(lambda: _row(api.group(gid), mid)["reactions"])
    assert _row(api.group(gid), mid)["reactions"] == [{"emoji": "👍", "count": 1, "mine": True}]
    assert api.react(gid, {"id": mid, "emoji": "👍", "who": True})["who"]

    api.react(gid, {"id": mid, "emoji": "👍"})                 # the same again: taken back
    assert await _until(lambda: not _row(api.group(gid), mid)["reactions"])

    with pytest.raises(SessionError):
        api.react(gid, {"id": mid, "emoji": "🦫"})
    await api.group_settings(gid, {"reactions": ["🦫"]})          # the owner's own set
    assert api.group(gid)["group"]["reactions"]["offered"] == ["🦫"]
    await api.group_settings(gid, {"reactions": "none"})
    assert not _row(api.group(gid), mid)["react"]["allowed"]
    with pytest.raises(SessionError):
        await api.group_settings(gid, {"reactions": "lots"})
    await owner.close()
    await other.close()
    server.close()


async def test_discussion_groups_take_none_by_default(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.create_group({"name": "dk.debat", "type": "open"}))["id"]
    mid = await owner.post(gid, "Emne", "tekst\n")
    await owner.fetch_group(gid)
    g = api.group(gid)
    assert g["group"]["reactions"]["offered"] == []
    assert not _row(g, mid)["react"]["allowed"]
    with pytest.raises(SessionError):
        api.react(gid, {"id": mid, "emoji": "👍"})
    await owner.close()
    await other.close()
    server.close()
