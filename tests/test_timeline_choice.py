"""UN-RFC 0034 section 6.2: what comes into the timeline. Feeds by default, groups of
threads when you put them in, never chat; the view you read a group in changes nothing;
only entries come in; the choice is kept in your state (UN-RFC 0044 ``timeline``)."""

import pytest

from unseenet.client.localapi import LocalAPI
from unseenet.client.localapi.api import TIMELINE
from unseenet.client.session import SessionError
from unseenet.core import state as st

from test_localapi_owner import _setup


async def test_what_comes_into_the_timeline(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    feed = (await api.create_group({"name": "dk.nyt", "type": "open", "view": "feed"}))["id"]
    talk = (await api.create_group({"name": "dk.snak", "type": "open"}))["id"]
    chat = (await api.create_group({"name": "dk.chat", "type": "open", "view": "chat"}))["id"]
    note = await owner.post(feed, "", "En note\n", kind="chat")
    root = await owner.post(talk, "Et emne", "Hvad siger I?\n")
    reply = await owner.post(talk, "Re: Et emne", "Et svar\n", references=[root])

    theirs = LocalAPI(session=other)
    for gid in (feed, talk, chat):
        other.subscribe(gid)
    await other.fetch_unknown_manifests()
    for gid in (feed, talk, chat):
        await other.fetch_group(gid)

    # the defaults: the feed in, threads and chat out
    assert other.timeline_groups() == [feed]
    assert theirs.group(talk)["group"]["timeline"] == {"on": False, "possible": True, "default": False}
    assert theirs.group(chat)["group"]["timeline"]["possible"] is False
    side = theirs.groups()
    assert side["timeline"]["feeds"] == 1
    assert {g["id"]: g["in_timeline"] for g in side["groups"] if g["id"] in (feed, talk, chat)} \
        == {feed: True, talk: False, chat: False}
    assert {g["id"]: g["timeline_possible"] for g in side["groups"] if g["id"] in (feed, talk, chat)} \
        == {feed: True, talk: True, chat: False}

    # reading a group as a feed does not put it in the timeline
    theirs.set_view(talk, "feed")
    assert other.in_timeline(talk) is False
    theirs.set_view(talk, None)

    # threads put in: only the thread's start comes in, the reply stays under it
    assert theirs.set_in_timeline(talk, True) == {"ok": True, "on": True}
    entries = [m.message_id for m in other.timeline()]
    assert root in entries and note in entries and reply not in entries
    rows = [(r["message"]["id"], r["depth"]) for r in theirs.group(TIMELINE)["rows"]]
    assert (root, 0) in rows and (reply, 0) not in rows

    # the feed taken out, then back to its default
    theirs.set_in_timeline(feed, False)
    assert other.timeline_groups() == [talk]
    theirs.set_in_timeline(feed, None)
    assert set(other.timeline_groups()) == {feed, talk}
    assert other.data["timeline_choice"] == {talk: True}         # only what differs is kept

    # chat never; and a group you do not follow cannot be chosen
    with pytest.raises(SessionError, match="cannot be in the timeline"):
        theirs.set_in_timeline(chat, True)
    with pytest.raises(SessionError, match="true, false or null"):
        theirs.set_in_timeline(talk, "yes")
    other.subscribe(talk, on=False)
    assert other.in_timeline(talk) is False
    with pytest.raises(SessionError, match="follow the group first"):
        other.set_in_timeline(talk, True)
    await owner.close()
    await other.close()
    server.close()


async def test_the_choice_is_in_the_state(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    talk = (await api.create_group({"name": "dk.snak", "type": "open"}))["id"]
    other.subscribe(talk)
    await other.fetch_unknown_manifests()
    other.set_in_timeline(talk, True)
    s = other.local_state()
    assert s["timeline"][talk]["on"] is True
    other.subscribe(talk, on=False)                 # left: the choice goes too
    assert other.local_state()["timeline"][talk].get("removed") is True
    await owner.close()
    await other.close()
    server.close()


def test_timeline_choices_merge_per_group():
    a, b = st.empty(), st.empty()
    a["timeline"] = {"x@a": {"on": True, "at": "2026-10-28T08:00:00Z"},
                     "y@a": {"on": False, "at": "2026-10-28T09:00:00Z"}}
    b["timeline"] = {"x@a": {"removed": True, "at": "2026-10-28T10:00:00Z"},
                     "y@a": {"on": True, "at": "2026-10-28T07:00:00Z"}}
    m = st.merge(a, b)
    assert m["timeline"] == {"x@a": {"removed": True, "at": "2026-10-28T10:00:00Z"},
                             "y@a": {"on": False, "at": "2026-10-28T09:00:00Z"}}
    old = st.empty()
    old.pop("timeline")                               # a state from before: still merges
    assert st.merge(old, a)["timeline"] == a["timeline"]
