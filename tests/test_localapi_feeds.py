"""#442: feeds in the local client API (UN-RFC 0046 section 4.14, UN-RFC 0034), against a
real node: starting your feed after the warning, following a person and a feed, the
timeline as ``timeline:`` with the comments under each entry, the profile's feed, and
showing a group as a feed."""

import pytest

from unseenet.client.localapi import LocalAPI
from unseenet.client.localapi.api import TIMELINE
from unseenet.client.session import SessionError

from test_localapi_owner import _setup


async def test_a_feed_followed_and_its_timeline(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    mine = api.my_feed()
    fp = owner.identity().fingerprint
    assert mine["id"] == f"feed@{fp}" and mine["started"] is False
    assert "public" in mine["warning"]
    with pytest.raises(SessionError, match="open or none"):
        await api.start_feed({"comments": "maybe"})
    started = await api.start_feed({"comments": "open", "title": "Mit feed"})
    assert started["id"] == mine["id"] and api.my_feed()["started"] is True
    gid = started["id"]
    entry = await owner.post(gid, "", "Første note\n", kind="chat")
    older = await owner.post(gid, "En overskrift", "Et indlæg\n")

    theirs = LocalAPI(session=other)
    key = owner.identity().key_text
    profile = await theirs.profile(key)
    assert profile["feed"] == gid and profile["following"] is False
    done = await theirs.set_following({"person": key})
    assert done["ok"] and done["new"] == [gid]
    assert (await theirs.profile(key))["following"] is True
    await other.fetch_group(gid)
    comment = await other.post(gid, "", "Fin note\n", kind="chat", references=[entry])
    await other.fetch_group(gid)

    f = theirs.following()
    [p] = f["people"]
    assert p["fingerprint"] == fp and [x["id"] for x in p["feeds"]] == [gid]
    assert [x["id"] for x in f["feeds"]] == [gid] and f["feeds"][0]["personal"] is True
    assert theirs.groups()["timeline"] == {"id": TIMELINE, "feeds": 1}

    t = theirs.group(TIMELINE)
    assert t["group"]["view"] == "feed" and t["group"]["label"] == "Timeline"
    ids = [(r["message"]["id"], r["depth"]) for r in t["rows"]]
    assert ids[0][1] == 0 and {i for i, d in ids if d == 0} == {entry, older}
    assert ids[ids.index((entry, 0)) + 1] == (comment, 1)       # the comment under its entry
    row = t["rows"][0]
    assert row["comment"]["allowed"] and row["group_label"] and row["address"].startswith("unseenet:")
    theirs.mark_read(TIMELINE, [entry])
    assert other.is_read(next(m for m in other.cache[gid].values() if m.message_id == entry))

    g = theirs.group(gid)                                       # the feed itself, as a feed
    assert g["group"]["view"] == "feed" and all("comment" in r for r in g["rows"])

    gone = await theirs.set_following({"person": key, "on": False})
    assert gone["unsubscribed"] == [gid] and theirs.following()["people"] == []
    await theirs.set_following({"feed": gid})                   # the feed on its own
    assert [x["id"] for x in theirs.following()["feeds"]] == [gid]
    await theirs.set_following({"feed": gid, "on": False})
    assert theirs.following()["feeds"] == []
    with pytest.raises(SessionError):
        await theirs.set_following({})
    await owner.close()
    await other.close()
    server.close()


async def test_any_group_may_be_shown_as_a_feed(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.create_group({"name": "dk.noter", "type": "open"}))["id"]
    await owner.post(gid, "Hej", "tekst\n")
    await owner.fetch_group(gid)
    assert "comment" not in api.group(gid)["rows"][0]
    api.set_view(gid, "feed")
    assert api.group(gid)["group"]["view"] == "feed" and "comment" in api.group(gid)["rows"][0]
    api.set_view(gid, None)
    with pytest.raises(SessionError, match="threads, chat, feed or null"):
        api.set_view(gid, "data")
    await owner.close()
    await other.close()
    server.close()
