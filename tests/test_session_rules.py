"""#615: the Session's side of your rules - keeping them, seen, threads, and the timeline
and a group's threads as the rules have them (and exactly as before without rules)."""
from datetime import datetime, timedelta, timezone

import pytest

from unseenet.client.session import Message, Session, SessionError
from unseenet.core.vault import Vault

KDF = {"ops": 1, "mem": 8192 * 1024}
GID = "dk.snak@abcdabcdabcdabcd"
T0 = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.subscribe(GID)
    yield s
    s.vault.close()


def msg(n, mid, subject, author="ed25519:" + "a" * 52, refs=(), minutes=0):
    return Message(number=n, message_id=mid, group=GID, subject=subject, from_name="X",
                   author_key=author, date=T0 + timedelta(minutes=minutes), references=list(refs),
                   body=subject)


def test_keeping_the_rules(s):
    rs = s.set_feed_rules("+10 if author in following\n+1 if autor in contacts")
    assert len(rs.rules) == 1 and rs.problems[0].line == 2 and s.rule_set() is s.rule_set()
    assert "autor" in s.feed_rules()                      # kept as written
    with pytest.raises(SessionError):
        s.set_feed_rules("# " + "x" * 3000)
    s.set_feed_rules("   ")
    assert s.feed_rules() == "" and not s.rule_set()


def test_seen_never_moves_back_and_threads(s):
    s.mark_seen(GID, T0)
    s.mark_seen(GID, T0 - timedelta(days=1))
    assert s.seen_to(GID) == "2026-10-26T12:00:00Z"
    m = msg(1, "<a@x>", "a", minutes=-5)
    assert s.is_seen(m) and not s.is_seen(msg(2, "<b@x>", "b", minutes=5))
    s.set_thread_mark("<a@x>", "watched")
    assert s.thread_mark("<a@x>") == "watched"
    with pytest.raises(SessionError):
        s.set_thread_mark("<a@x>", "loved")


def test_threads_without_rules_are_as_before_and_with_rules_never_reordered_inside(s):
    s.cache[GID] = {m.message_id: m for m in [
        msg(1, "<k@x>", "kage", minutes=1), msg(2, "<p@x>", "politik", minutes=2),
        msg(3, "<k2@x>", "re: kage", refs=["<k@x>"], minutes=3),
        msg(4, "<k3@x>", "re: re: kage", refs=["<k@x>", "<k2@x>"], minutes=4),
        msg(5, "<p2@x>", "re: politik", refs=["<p@x>"], minutes=5)]}
    before = [(m.message_id, d) for m, d in s.threads(GID)]
    assert [(m.message_id, d) for m, d, _ in s.scored_threads(GID)] == before
    s.set_feed_rules("[groups]\n-50 if subject matches \"politik\"\nhide if score < 0\n"
                     "highlight if subject matches \"re: re:\"\nsort by score")
    rows = s.scored_threads(GID)
    assert [m.message_id for m, _, _ in rows] == ["<k@x>", "<k2@x>", "<k3@x>"]     # politik hidden
    assert [d for _, d, _ in rows] == [0, 1, 2] and "highlight" in rows[2][2].actions


def test_facts(s):
    me = s.identity().key_text
    s.cache[GID] = {m.message_id: m for m in [
        msg(1, "<t@x>", "start", author=me), msg(2, "<r@x>", "re: start", refs=["<t@x>"])]}
    f = s.post_facts(s.cache[GID]["<r@x>"])
    assert f.group == "dk.snak" and f.thread == "<t@x>" and f.i_posted_in_thread
    assert s.post_facts(s.cache[GID]["<t@x>"]).replies == 1
