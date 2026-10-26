"""#615: your own rules in the local client API (UN-RFC 0046 section 4.20, UN-RFC 0051):
reading, writing, checking, turning off; seen; watched threads; and the rows of a group
scored only when you have rules."""
from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI
from unseenet.client.localapi import server as srv
from unseenet.client.session import Message, Session, SessionError
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}
GID = "dk.snak@abcdabcdabcdabcd"
T0 = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def api(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    yield LocalAPI(session=s)
    await s.close()
    server.close()


def msg(n, mid, subject, refs=(), minutes=0):
    return Message(number=n, message_id=mid, group=GID, subject=subject, from_name="X",
                   author_key="ed25519:" + "a" * 52, date=T0 + timedelta(minutes=minutes),
                   references=list(refs), body=subject)


async def test_rules_kept_checked_and_turned_off(api):
    first = api.rules()
    assert {k: first[k] for k in ("text", "on", "rules", "problems")} == {"text": "", "on": True, "rules": 0, "problems": []}
    from unseenet.client import scoring
    assert first["suggestion"] == scoring.SUGGESTION and not scoring.parse(scoring.SUGGESTION).problems
    assert not api.session.feed_rules()                               # offered, not taken
    got = api.set_rules({"text": "+10 if author in following  # friends\n+1 if autor in contacts"})
    assert got["rules"] == 1 and got["problems"][0]["line"] == 2 and "author" in got["problems"][0]["message"]
    assert api.check_rules({"text": "show if score >= 0"}) == {"rules": 1, "problems": []}
    assert api.rules()["rules"] == 1                                 # checking kept nothing
    off = api.set_rules({"on": False})
    assert off["on"] is False and off["text"].startswith("+10")      # the text stays
    assert not api.session.rule_set()
    assert api.set_rules({"on": True})["on"] is True
    with pytest.raises(SessionError, match="2048 bytes"):
        api.set_rules({"text": "#" + "x" * 3000})
    routes = {(m, p) for m, p, _ in srv.ROUTES}
    assert {("GET", "/api/rules"), ("POST", "/api/rules"), ("POST", "/api/rules/check"),
            ("POST", "/api/threads"), ("POST", "/api/groups/{gid}/seen")} <= routes


async def test_seen_and_threads(api):
    assert api.mark_seen(GID, {"until": "2026-10-26T18:00:00Z"}) == {"seen_to": "2026-10-26T18:00:00Z"}
    with pytest.raises(SessionError):
        api.mark_seen(GID, {"until": "tomorrow"})
    assert api.thread_mark({"id": "<t@x>", "mark": "watched"}) == {"id": "<t@x>", "mark": "watched"}
    with pytest.raises(SessionError):
        api.thread_mark({"id": "t", "mark": "watched"})


async def test_rows_are_scored_only_with_rules(api):
    s = api.session
    s.subscribe(GID)
    s.cache[GID] = {m.message_id: m for m in [
        msg(1, "<k@x>", "kage", minutes=1), msg(2, "<p@x>", "politik", minutes=2),
        msg(3, "<k2@x>", "re: kage", refs=["<k@x>"], minutes=3)]}
    plain = api.group(GID)["rows"]
    assert all("score" not in r for r in plain)                      # as before, to the byte
    api.set_rules({"text": "[groups]\n-50 if subject matches \"politik\"  # enough\nhide if score < 0"})
    rows = api.group(GID)["rows"]
    by = {r["message"]["id"]: r for r in rows}
    assert by["<k@x>"]["score"] == 0 and by["<k@x>"]["hidden"] is False and by["<k@x>"]["thread_mark"] == ""
    assert "<p@x>" not in by                                          # every post of it hidden
    assert [r["message"]["id"] for r in rows] == ["<k@x>", "<k2@x>"]
    api.set_rules({"on": False})
    assert [r.get("score") for r in api.group(GID)["rows"]] == [None, None, None]


async def test_the_timeline_with_rules(api):
    from unseenet.client.threads import TIMELINE
    api.set_rules({"text": "[feed]\n+10 if author in following\nsort by score, then date"})
    assert api.group(TIMELINE)["rows"] == []                          # nothing followed: as before
