"""Threads and views from the core, the same in every client (unseenet #139)."""
import pytest

from unseenet.client.session import Message, Session, SessionError
from unseenet.client.threads import CONTACT, FOR_YOU, threaded
from unseenet.core.groups import KIND_CHAT
from unseenet.core.vault import Vault

KDF = {"ops": 1, "mem": 8192 * 1024}
G = "dk.snak@aaaaaaaaaaaaaaaa"


def m(n, refs=(), kind="post", private=False):
    return Message(number=n, message_id=f"<{n}@x>", group=G, references=[f"<{r}@x>" for r in refs],
                   kind=kind, private=private)


def ids(rows):
    return [(int(r.message_id[1:].split("@")[0]), d) for r, d in rows]


def test_replies_go_under_their_thread_newest_thread_first():
    rows = threaded([m(1), m(2), m(3, [1]), m(4, [1, 3])])
    assert ids(rows) == [(1, 0), (3, 1), (4, 2), (2, 0)]


def test_a_reply_to_a_post_we_do_not_have_starts_its_own_thread():
    assert ids(threaded([m(1), m(2, [99])])) == [(2, 0), (1, 0)]


def test_consecutive_chat_lines_stay_together_and_depth_is_capped():
    rows = threaded([m(1, kind=KIND_CHAT), m(2, kind=KIND_CHAT), m(3), m(4, kind=KIND_CHAT)])
    assert ids(rows) == [(4, 0), (3, 0), (1, 0), (2, 0)]
    deep = threaded([m(1), m(2, [1, 1, 1, 1, 1, 1, 1])])
    assert deep[1][1] == 4


@pytest.fixture
def session(tmp_path):
    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me")
    yield s
    s.vault.close()


def test_session_threads_a_group_from_its_cache(session):
    session.cache[G] = {x.message_id: x for x in (m(2, [1]), m(1))}
    assert ids(session.threads(G)) == [(1, 0), (2, 1)]
    assert session.threads(FOR_YOU) == []
    assert session.threads(CONTACT + "ed25519:nobody") == []


def test_view_your_choice_then_the_owners_then_threads(session):
    assert session.view_of(G) == "threads"
    session.data["groups"][G] = {"manifest": {"view": "chat"}}
    assert session.view_of(G) == "chat"
    session.set_view(G, "threads")
    assert session.view_of(G) == "threads"
    session.set_view(G, None)                   # back to the owner's
    assert session.view_of(G) == "chat"
    assert session.view_of(CONTACT + "ed25519:x") == "chat"
    assert session.view_of(FOR_YOU) == session.view_of(session.my_inbox) == "threads"


def test_set_view_refuses_what_no_client_can_show(session):
    with pytest.raises(ValueError):
        session.set_view(G, "gallery")
    with pytest.raises(SessionError):
        session.set_view(FOR_YOU, "chat")


def test_a_contacts_chat_leaves_out_ignored_keys(session):
    """threads() of a contact's chat goes through visible(), like every other view."""
    other = "ed25519:" + "a" * 52
    got = []
    session.visible = lambda msgs: got.append(list(msgs)) or []
    assert session.threads(CONTACT + other) == []
    assert got, "visible() was not asked"
