"""#440/#444/#677: key ripening keeps within the machine's memory, one large ripening
at a time on the whole machine."""
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
    assert rp.fitting_segment_length(0, 0, None, low=False) == rp.next_segment_length(0)
    t = rp.LEVELS[2][1]
    assert rp.fitting_segment_length(t, 20, 64 << 30, low=False) == rp.next_segment_length(t)


def test_shorter_segments_or_a_stop_when_it_is_not():
    t = rp.LEVELS[2][1]                                   # level 2: segments of 2^31 next
    assert rp.memory_for(rp.next_segment_length(t), low=False) > 1024 * MB
    short = rp.fitting_segment_length(t, 12, 1024 * MB, low=False)
    assert short and rp.memory_for(short, low=False) <= 1024 * MB and short < rp.next_segment_length(t)
    assert rp.fitting_segment_length(t, 60, 300 * MB, low=False) == 0     # level 3 out of reach
    assert rp.fitting_segment_length(0, 0, rp.MEMORY_BASE, low=False) == 0  # no room at all


@pytest.mark.parametrize("mb, level", [(None, 4), (4096, 4), (1024, 3), (400, 2), (100, 1)])
def test_how_far_a_machine_can_go(mb, level):
    assert rp.reachable_level(0, 0, None if mb is None else mb * MB, low=False) == level


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
    monkeypatch.setattr(rp, "low_memory", lambda: False)                      # #440's model
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


# --- #444: the low-memory prover ---------------------------------------------------

@pytest.mark.parametrize("mb", [None, 4096, 1024, 400, 100])
def test_with_the_low_memory_prover_every_machine_reaches_the_top(mb):
    assert rp.reachable_level(0, 0, None if mb is None else mb * MB, low=True) == 4
    t = rp.LEVELS[2][1]
    assert rp.memory_for(rp.next_segment_length(t), low=True) == rp.MEMORY_BASE
    assert rp.fitting_segment_length(t, 12, 300 * MB, low=True) == rp.next_segment_length(t)
    assert rp.fitting_segment_length(t, 12, rp.MEMORY_BASE - 1, low=True) == 0   # nothing fits


class _FakeVdf:
    def __init__(self, low):
        self.calls = []
        if low:
            self.prove_low_memory = lambda *a: self._prove("low", *a)

    def prove(self, *a):
        return self._prove("prove", *a)

    def _prove(self, which, *a):
        self.calls.append((which, a[3], a[4]))
        return bytes(rp.FORM_SIZE) + b"pi"


@pytest.mark.parametrize("low, used", [(True, "low"), (False, "prove")])
def test_prove_segment_uses_the_low_memory_prover_when_there(monkeypatch, low, used):
    fake = _FakeVdf(low)
    monkeypatch.setattr(rp, "_vdf", lambda: fake)
    assert rp.low_memory() is low
    seg = rp.prove_segment(bytes(32), rp.GENERATOR, 1000, "/run/file")
    assert fake.calls == [(used, 1000, "/run/file")]       # run_file still stops it
    assert seg.t == 1000 and seg.pi == b"pi"


def test_without_chiavdf_the_old_model_counts(monkeypatch):
    def missing():
        raise rp.RipeningUnavailable("no chiavdf")
    monkeypatch.setattr(rp, "_vdf", missing)
    assert rp.low_memory() is False
    assert rp.memory_for(1 << 30) > 512 * MB


def test_the_real_low_memory_prover_gives_the_same_segment():
    chiavdf = pytest.importorskip("chiavdf")
    if not hasattr(chiavdf, "prove_low_memory"):
        pytest.skip("chiavdf before 1.2.1")
    pk = bytes(range(32))
    a = chiavdf.prove(rp.seed(pk), rp.GENERATOR, rp.DISC_BITS, 20000, "")
    b = chiavdf.prove_low_memory(rp.seed(pk), rp.GENERATOR, rp.DISC_BITS, 20000, "")
    assert a == b
    seg = rp.Segment(20000, bytes(b[:rp.FORM_SIZE]), bytes(b[rp.FORM_SIZE:]))
    assert rp.verify(pk, rp.Chain([seg])) == 1


# --- #677: one lock for the whole machine -------------------------------------------

def test_the_lock_is_shared_by_every_user(monkeypatch, tmp_path):
    monkeypatch.delenv("UNSEENET_RIPENING_LOCK", raising=False)
    monkeypatch.setattr(machine.sys, "platform", "linux")
    shared = tmp_path / "run-lock"
    shared.mkdir()
    monkeypatch.setattr(machine, "SHARED_LOCK_DIRS", (str(tmp_path / "missing"), str(shared)))
    assert machine.lock_path() == shared / machine.LOCK_NAME   # no user in the name
    monkeypatch.setenv("UNSEENET_RIPENING_LOCK", str(tmp_path / "own.lock"))
    assert machine.lock_path() == tmp_path / "own.lock"


def test_the_lock_falls_back_to_the_users_own(monkeypatch, tmp_path):
    monkeypatch.delenv("UNSEENET_RIPENING_LOCK", raising=False)
    monkeypatch.setattr(machine, "SHARED_LOCK_DIRS", (str(tmp_path / "missing"),))
    assert machine.lock_path() == machine._user_lock_path()
    monkeypatch.setattr(machine.sys, "platform", "darwin")
    monkeypatch.setattr(machine, "SHARED_LOCK_DIRS", (str(tmp_path),))
    assert machine.lock_path() == machine._user_lock_path()  # Linux only


@pytest.mark.skipif(machine.sys.platform == "win32", reason="flock")
def test_a_lock_file_someone_else_made_is_opened_without_creating(tmp_path):
    path = tmp_path / machine.LOCK_NAME
    path.write_text("")
    path.chmod(0o444)                       # as another user's file looks to us
    a, b = machine.RipeningLock(path), machine.RipeningLock(path)
    assert a.acquire()
    assert not b.acquire()
    a.release()
    assert b.acquire()
    b.release()


async def test_the_budget_is_read_again_once_the_lock_is_held(tmp_path, monkeypatch):
    """#677: two programs saw the same free memory and both planned for it."""
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setenv("UNSEENET_RIPENING_LOCK", str(tmp_path / "r.lock"))
    s = Session(Vault.open(tmp_path / "v.vault", "pw", ops=1, mem=8192 * 1024))
    s.new_identity("me")
    monkeypatch.setattr(rp, "low_memory", lambda: False)
    budgets = iter([64 << 30, rp.MEMORY_BASE])          # plenty, then gone once locked
    monkeypatch.setattr(machine, "ripening_budget", lambda: next(budgets))
    monkeypatch.setattr(machine, "LOCK_ABOVE", 0)       # every segment takes the lock
    proved = []

    async def prove(*a):
        proved.append(a)
    monkeypatch.setattr(s, "_prove_segment", prove)
    assert await s.ripen_segment() is False
    assert proved == []                                  # nothing planned on stale memory
    lock = machine.RipeningLock()
    assert lock.acquire()                                # and the lock was given back
    lock.release()
    await s.close()
