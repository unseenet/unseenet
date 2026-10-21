"""The dict form of Message and GroupInfo, and the list of your groups (unseenet #139)."""
import json
from datetime import datetime, timezone

import pytest

from unseenet.client.session import DICT_VERSION, GroupInfo, Message, Session
from unseenet.core.vault import Vault

KDF = {"ops": 1, "mem": 8192 * 1024}
G = "dk.snak@aaaaaaaaaaaaaaaa"
H = "alt.marsvin@bbbbbbbbbbbbbbbb"


def test_message_dict_is_json_and_splits_the_signature():
    m = Message(number=3, message_id="<3@x>", group=G, subject="Hej",
                date=datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc),
                body="Første linje\n-- \nAndreas\n", references=["<1@x>", "<2@x>"], raw=b"\x00")
    d = m.to_dict()
    assert json.loads(json.dumps(d)) == d                # nothing that JSON can't carry
    assert d["v"] == DICT_VERSION and d["id"] == "<3@x>" and "raw" not in d
    assert d["date"] == "2026-10-21T18:00:00+00:00" and d["edited"] is None
    assert d["text"] == "Første linje" and d["signature"] == "Andreas"
    assert d["thread_root"] == "<1@x>"


def test_an_unreadable_message_gives_no_text():
    d = Message(number=1, message_id="<1@x>", group=G, body="sealed", readable=False).to_dict()
    assert d["text"] == "" and d["signature"] is None


def test_group_dict_names_its_hierarchy():
    d = GroupInfo("dk.snak.marsvin@aaaaaaaaaaaaaaaa", "Marsvin").to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["label"] == "dk.snak.marsvin" and d["hierarchy"] == "dk"
    assert d["unread"] is None and d["listed"] is None      # not counted, not known


@pytest.fixture
def session(tmp_path):
    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me")
    s.data["subscribed"] += [G, H]
    s.data["groups"][G] = {"type": "public", "owner": True, "keys": {},
                           "manifest": {"view": "chat", "title": "Snak"}}
    yield s
    s.vault.close()


def test_subscribed_groups_in_your_order_with_view_and_counts(session):
    session.cache[G] = {"<1@x>": Message(number=1, message_id="<1@x>", group=G)}
    groups = {g.group_id: g for g in session.subscribed_groups()}
    assert [g.group_id for g in session.subscribed_groups()] == session.data["subscribed"]
    g = groups[G]
    assert (g.type, g.owner, g.title, g.view, g.owner_view) == ("public", True, "Snak", "chat", "chat")
    assert g.unread == 1 and g.replies == 0 and g.mentions == 0
    assert groups[H].view == "threads" and groups[H].unread == 0
    session.set_view(G, "threads", save=False)
    assert {g.group_id: g for g in session.subscribed_groups()}[G].view == "threads"


def test_subscribed_groups_says_what_your_nodes_do_not_carry(session):
    session.data["subscribed"].append(session.my_inbox)    # as once the inbox is made
    offline = {g.group_id: g for g in session.subscribed_groups(counts=False)}
    assert offline[G].listed is None and offline[G].unread is None
    listed = {g.group_id: g for g in session.subscribed_groups({G: GroupInfo(G, "listed")})}
    assert listed[G].listed is True and listed[G].description == "listed"
    assert listed[H].listed is False
    assert listed[session.my_inbox].listed is True       # key-bound: never listed (UN-RFC 0040)
