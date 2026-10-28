"""#440: key ripening keeps within the machine's memory, one large ripening at a time."""
import pytest

from unseenet.client import events as ev
from unseenet.client import machine
from unseenet.client.runtime import RIPEN_TO
from unseenet.client.session import Session
from unseenet.core import ripening as rp
from unseenet.core.vault import Vault

MB = 1 << 20


@pytest.fixture(autouse=True)
def real_levels(monkeypatch):
    """The real levels and first segment (the suite scales them down to be quick)."""
    monkeypatch.setattr(rp, "LEVELS", rp._REAL_LEVELS)
    monkeypatch.setattr(rp, "TOP", rp._REAL_LEVELS[-1][1])
    monkeypatch.setattr(rp, "FIRST_SEGMENT", 1 << 24)


def test_the_usual_lengths_when_memory_is_plenty():
    assert rp.fitting_segment_length(0, 0, None) == rp.next_segment_length(0)
    t = rp.LEVELS[2][1]
    assert rp.fitting_segment_length(t, 20, 64 << 30) == rp.next_segment_length(t)


def test_shorter_segments_or_a_stop_when_it_is_not():
    t = rp.LEVELS[2][1]                                   # level 2: segments of 2^31 next
    assert rp.memory_for(rp.next_segment_length(t)) > 1024 * MB
    short = rp.fitting_segment_length(t, 12, 1024 * MB)
    assert short and rp.memory_for(short) <= 1024 * MB and short < rp.next_segment_length(t)
    assert rp.fitting_segment_length(t, 60, 300 * MB) == 0     # level 3 out of reach
    assert rp.fitting_segment_length(0, 0, rp.MEMORY_BASE) == 0  # no room at all


@pytest.mark.parametrize("mb, level", [(None, 4), (4096, 4), (1024, 3), (400, 2), (100, 1)])
def test_how_far_a_machine_can_go(mb, level):
    assert rp.reachable_level(0, 0, None if mb is None else mb * MB) == level


def test_clients_ripen_to_level_3():
    assert RIPEN_TO == 3


def test_the_budget_follows_the_environment(monkeypatch):
    monkeypatch.setenv("UNSEENET_RIPENING_MEMORY", "500")
    assert machine.ripening_budget() == 500 * MB
    monkeypatch.delenv("UNSEENET_RIPENING_MEMORY")
    monkeypatch.setattr(machine, "free_memory", lambda: 1000 * MB)
    assert machine.ripening_budget() == int(1000 * MB * machine.SHARE)


def test_one_large_ripening_at_a_time(tmp_path):
    a, b = machine.RipeningLock(tmp_path / "l"), machine.RipeningLock(tmp_path / "l")
    assert a.acquire()
    assert not b.acquire()                                # another program holds it
    a.release()
    assert b.acquire()
    b.release()


async def test_session_stops_and_says_how_far(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    s = Session(Vault.open(tmp_path / "v.vault", "pw", ops=1, mem=8192 * 1024))
    s.new_identity("me")
    said = []
    s.on(lambda e: said.append(e.text) if isinstance(e, ev.Status) else None)
    monkeypatch.setattr(machine, "ripening_budget", lambda: rp.MEMORY_BASE)    # no room
    assert await s.ripen_segment() is False
    assert s.ripening_limit is None or s.ripening_limit == rp.level(0)
    assert any("This machine can ripen this key to level" in t for t in said)
    await s.close()


def _cg(path, limit, used):
    path.mkdir(parents=True, exist_ok=True)
    (path / "memory.max").write_text(f"{limit}\n")
    (path / "memory.current").write_text(f"{used}\n")


def test_a_service_limit_inside_a_container_counts(tmp_path):
    """gateway#47: a systemd MemoryMax inside a container is the limit, not the
    container's own - read from this process's cgroup up to the root."""
    from unseenet.client.machine import _cgroup_room
    root = tmp_path / "cg"
    _cg(root, "max", 100 << 20)                                     # the container's root view
    _cg(root / "system.slice", "max", 90 << 20)
    _cg(root / "system.slice" / "gw.service", 250 << 20, 200 << 20)  # MemoryMax=250M
    own = tmp_path / "self.cgroup"
    own.write_text("0::/system.slice/gw.service\n")
    assert _cgroup_room(root, own) == 50 << 20
    _cg(root, 1 << 30, 900 << 20)                                   # a tighter one above wins
    assert _cgroup_room(root, own) == min(50 << 20, (1 << 30) - (900 << 20))
    own.write_text("0::/\n")                                        # only the root
    assert _cgroup_room(root, own) == (1 << 30) - (900 << 20)
    _cg(root, "max", 0)
    assert _cgroup_room(root, own) is None                           # no limit anywhere
    assert _cgroup_room(root, tmp_path / "missing") is None
