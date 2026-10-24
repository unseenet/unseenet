"""#257 step 3: your state in the network (UN-RFC 0044) - sealed, merged, and following
you from one device to another."""
from datetime import timedelta

import pytest

from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core import state as st
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


# --- the protocol (core/state.py) ---------------------------------------------

def test_sealed_to_a_fixed_size_and_only_for_its_owner():
    seed, gid = bytes(32), "state@abcdabcdabcdabcd"
    small, big = st.empty(), st.empty()
    small["subscribed"]["dk.a@x"] = "2026-10-24T10:00:00Z"
    for i in range(100):
        big["subscribed"][f"dk.group{i}@xxxxxxxxxxxxxxxx"] = "2026-10-24T10:00:00Z"
    assert len(st.seal(small, seed, gid)) == len(st.seal(st.empty(), seed, gid))   # 4 KiB both
    assert len(st.seal(big, seed, gid)) > len(st.seal(small, seed, gid))           # 8 KiB
    assert st.same(st.unseal(st.seal(big, seed, gid), seed, gid), big)
    for other_seed, other_gid in ((bytes([1]) * 32, gid), (seed, "state@other")):
        with pytest.raises(st.StateError):
            st.unseal(st.seal(small, seed, gid), other_seed, other_gid)


def test_merging_lets_the_newest_entry_win():
    a, b = st.empty(), st.empty()
    a["subscribed"]["dk.a@x"] = "2026-10-24T10:00:00Z"
    b["unsubscribed"]["dk.a@x"] = "2026-10-24T11:00:00Z"        # left later, elsewhere
    a["contacts"]["k1"] = {"name": "Sonia", "at": "2026-10-24T09:00:00Z"}
    b["contacts"]["k1"] = {"removed": True, "at": "2026-10-24T08:00:00Z"}
    a["starter"], b["starter"] = 1, 2
    a["read"]["dk.a@x"] = {"to": "2026-10-20T00:00:00Z", "also": ["<m1@x>"]}
    b["read"]["dk.a@x"] = {"to": "2026-10-22T00:00:00Z", "also": ["<m2@x>"]}
    m = st.merge(a, b)
    assert "dk.a@x" not in m["subscribed"] and "dk.a@x" in m["unsubscribed"]
    assert m["contacts"]["k1"]["name"] == "Sonia"               # the removal was older
    assert m["starter"] == 2
    assert m["read"]["dk.a@x"] == {"to": "2026-10-22T00:00:00Z", "also": ["<m1@x>", "<m2@x>"]}
    assert st.same(st.merge(a, b), st.merge(b, a))              # either way round


def test_a_state_too_big_drops_read_marks_first():
    s = st.empty()
    s["subscribed"]["dk.a@x"] = "2026-10-24T10:00:00Z"
    for i in range(400):
        s["read"][f"dk.old{i}@xxxxxxxxxxxxxxxx"] = {"to": "2026-10-01T00:00:00Z", "also": []}
    fitted = st.fit(s)
    assert "dk.a@x" in fitted["subscribed"] and len(fitted["read"]) < 400
    assert len(st.seal(s, bytes(32), "state@x")) <= 22 * 1024


# --- two devices (client/session/state.py) ------------------------------------

@pytest.fixture
async def network(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(Node, "STATE_EVERY", timedelta(0))         # two devices, minutes apart
    import unseenet.client.session as sess
    import unseenet.client.session.state as sstate
    monkeypatch.setattr(sstate, "WRITE_EVERY", 0.0)
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = "127.0.0.1:%d" % server.sockets[0].getsockname()[1]
    seed = crypto.Identity.generate().seed.hex()
    sessions = []

    def device(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.data["identities"]["me"] = {"seed": seed, "display": "Me"}   # as id-import does
        s.data["default_identity"] = "me"
        s.add_node(addr)
        sessions.append(s)
        return s
    yield node, device
    for s in sessions:
        await s.close()
    server.close()


async def test_your_groups_contacts_and_follows_follow_you_to_another_device(network):
    node, device = network
    a = device("stick")
    a.subscribe("dk.snak@abcdabcdabcdabcd")
    a.add_contact("ed25519:" + "a" * 52, "Sonia")
    a.data.setdefault("following", {}).setdefault("people", {})["fpfpfpfpfpfpfpfp"] = {
        "key": "ed25519:" + "b" * 52, "feeds": ["feed@fpfpfpfpfpfpfpfp"]}
    a.set_hide_bots(True)
    assert await a.sync_state() == "written"
    gid = st.state_id(a.identity().public_key)
    assert node.store.manifest(gid).type == "state"

    b = device("phone")                          # the same key, nothing else
    assert await b.sync_state() == "read"
    assert "dk.snak@abcdabcdabcdabcd" in b.data["subscribed"]
    assert b.data["contacts"]["ed25519:" + "a" * 52]["name"] == "Sonia"
    assert "fpfpfpfpfpfpfpfp" in b.data["following"]["people"]
    assert b.hide_bots() is True

    b.subscribe("dk.snak@abcdabcdabcdabcd", False)          # left on the phone
    assert await b.sync_state() == "written"
    assert await a.sync_state() in ("read", "written")
    assert "dk.snak@abcdabcdabcdabcd" not in a.data["subscribed"]   # and so on the stick


async def test_nothing_new_writes_nothing_and_read_marks_alone_do_not(network):
    _, device = network
    a = device("stick")
    a.subscribe("dk.snak@abcdabcdabcdabcd")
    assert await a.sync_state() == "written"
    assert await a.sync_state() == "read"                   # the same: not written again
    a.data["read_to"] = {"dk.snak@abcdabcdabcdabcd": "2026-10-24T10:00:00Z"}
    assert await a.sync_state() == "read"                   # read marks alone: no write


async def test_kept_local_writes_nothing(network):
    node, device = network
    a = device("stick")
    await a.set_state_kept_local(True)
    a.subscribe("dk.snak@abcdabcdabcdabcd")
    assert await a.sync_state() == "local"
    assert node.store.manifest(st.state_id(a.identity().public_key)) is None


async def test_read_up_to_a_date_never_covers_an_unread_post(network):
    """Found by the TUI's tests: Date is rounded to 10 minutes, so your post and the
    unread reply to it can carry the same time - "read up to" stops before it."""
    from datetime import datetime, timezone
    from unseenet.client.session import Message
    _, device = network
    a = device("stick")
    gid = "dk.snak@abcdabcdabcdabcd"
    a.subscribe(gid)
    when = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    def msg(mid, n):
        return Message(number=n, message_id=mid, group=gid, subject="x", from_name="X",
                       author_key="k", date=when, references=(), body="x")
    a.cache[gid] = {"<mine@x>": msg("<mine@x>", 1), "<reply@x>": msg("<reply@x>", 2)}
    a.mark_read(a.cache[gid]["<mine@x>"])
    marks = a._read_marks()[gid]
    assert marks["to"] < "2026-10-24T10:00:00Z" and marks["also"] == ["<mine@x>"]
    assert not a.is_read(a.cache[gid]["<reply@x>"])


async def test_a_clients_own_settings_follow_you_too(network):
    """The TUI's theme (and the GUI's) is kept per client, and goes with your state."""
    _, device = network
    a = device("stick")
    a.set_client_setting("tui", "theme", "nord")
    a.set_client_setting("gui", "theme", "dark")
    assert await a.sync_state() == "written"
    b = device("phone")
    await b.sync_state()
    assert b.client_setting("tui", "theme") == "nord" and b.client_setting("gui", "theme") == "dark"
    assert b.client_setting("tui", "font", "normal") == "normal"
