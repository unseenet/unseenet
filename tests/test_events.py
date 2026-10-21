"""Typed events from the session (unseenet #139)."""
import asyncio
import json

import pytest

from unseenet.client import events as ev
from unseenet.client.session import Session
from unseenet.core import pow as postage
from unseenet.core.tor import bootstrap_progress
from unseenet.core.vault import Vault

KDF = {"ops": 1, "mem": 8192 * 1024}
G = "dk.snak@aaaaaaaaaaaaaaaa"


@pytest.fixture
def session(tmp_path):
    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me")
    yield s
    s.vault.close()


def test_every_event_has_a_json_form_with_its_name():
    for e in (ev.Status("hi"), ev.GroupUpdated(G, 2), ev.GroupsChanged(),
              ev.PowProgress(10, 100), ev.NodeState("x.onion:119", False, "refused"),
              ev.TorState(45, "Loading relay descriptors")):
        d = e.to_dict()
        assert d["event"] == e.name != "event"
        assert json.loads(json.dumps(d)) == d


def test_pow_fraction_never_claims_done_too_early():
    assert ev.PowProgress(0, 1000).fraction == 0
    assert 0.6 < ev.PowProgress(1000, 1000).fraction < 0.7
    assert ev.PowProgress(10**9, 1000).fraction == 0.99
    assert ev.PowProgress(5, 1000, done=True).fraction == 1


def test_solve_reports_to_the_hook_of_its_own_thread_only():
    seen = []
    with postage.reporting(lambda *a: seen.append(a)):
        header = postage.solve(b"canonical", 18)          # ~262144 attempts: a few reports
    assert postage.verify(header, b"canonical") == 18
    assert seen[-1][2] is True and seen[-1][1] == 1 << 18
    assert all(not done for _, _, done in seen[:-1])
    seen.clear()
    postage.solve(b"canonical", 8)                        # no hook set: nothing
    assert seen == []


def test_tor_bootstrap_phase_is_read():
    line = 'status/bootstrap-phase=NOTICE BOOTSTRAP PROGRESS=45 TAG=loading SUMMARY="Loading relay descriptors"'
    assert bootstrap_progress(line) == (45, "Loading relay descriptors")
    assert bootstrap_progress("nonsense") == (0, "")


def test_listeners_get_status_and_group_changes_and_can_stop(session):
    got = []
    off = session.on(got.append)
    session.say("Connecting ...")
    session.subscribe(G)
    session.subscribe(G)                                  # no change, no event
    session.forget_group(G)
    off()
    session.say("not seen")
    assert [type(e) for e in got] == [ev.Status, ev.GroupsChanged, ev.GroupsChanged]
    assert got[0].text == "Connecting ..."


def test_a_broken_listener_does_not_stop_the_others(session):
    got = []

    def broken(_):
        raise RuntimeError("client bug")
    session.on(broken)
    session.on(got.append)
    session.say("still here")
    assert got == [ev.Status("still here")]


def test_compute_sends_pow_progress_on_the_loop(session):
    got = []
    session.on(got.append)

    async def run():
        return await session._compute(lambda: postage.solve(b"x", 17))
    asyncio.run(run())
    progress = [e for e in got if isinstance(e, ev.PowProgress)]
    assert progress and progress[-1].done and progress[-1].fraction == 1
