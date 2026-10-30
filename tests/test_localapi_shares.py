"""Sharing in the local client API (UN-RFC 0046, UN-RFC 0060): ``share`` on every row,
where a post can be shared, sharing as a job, the original, and taking it back."""
import asyncio

import pytest

from unseenet.client.session import SessionError
from unseenet.client.localapi.api import Status

from test_localapi_owner import _setup


def _row(group, mid):
    return next(r for r in group["rows"] if r["message"]["id"] == mid)


async def _until(check, seconds=10.0):
    for _ in range(int(seconds * 20)):
        if check():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_sharing_through_the_api(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.create_group({"name": "dk.snak", "type": "open"}))["id"]
    await other.fetch_group(gid)
    mid = await other.post(gid, "Mit marsvin", "hoster\n")
    await owner.fetch_group(gid)
    row = _row(api.group(gid), mid)
    assert row["share"]["allowed"]
    opts = api.share_options(gid, mid)
    assert opts["target"] == mid and opts["destinations"][0]["own_feed"]
    assert opts["destinations"][0]["reason"] == "Start your feed first"
    with pytest.raises(SessionError, match="Start your feed"):
        api.share(gid, {"id": mid})
    await owner.start_personal_group("feed")
    feed = owner.personal_group("feed")
    assert api.share(gid, {"id": mid, "notify": False})["job"]
    assert await _until(lambda: owner.my_shares(mid))
    assert list(owner.my_shares(mid)) == [feed]
    shares = [m for m in owner.cache.get(feed, {}).values() if m.kind == "share"]
    assert shares and shares[0].share_of == mid

    got = await api.share_target(mid, gid)
    assert got["state"] == "ok" and got["message"]["subject"] == "Mit marsvin"
    assert not got["edited"]
    with pytest.raises(SessionError):
        await api.share_target("nope", gid)

    async def slow(of, group, patience=None):
        return {"state": "fetching", "message": None}
    monkeypatch.setattr(owner, "fetch_share_target", slow)
    with pytest.raises(Status) as e:                                  # 503 later
        await api.share_target("<x@y>", gid)
    assert e.value.status == 503 and e.value.fields == {"later": True}

    share_id = owner.my_shares(mid)[feed]                          # from your own share too
    await owner.fetch_group(feed)
    assert (await api.unshare(feed, {"id": share_id}))["groups"] == [feed]
    assert owner.my_shares(mid) == {}
    s = api.settings()
    assert s["share_notices"] is True and s["hide_shares"] == {"all": False, "groups": []}
    await api.change_settings({"share_notices": False, "hide_shares": {"groups": [feed]}})
    assert api.settings()["share_notices"] is False
    assert api.settings()["hide_shares"]["groups"] == [feed]
    await owner.close()
    await other.close()
    server.close()
