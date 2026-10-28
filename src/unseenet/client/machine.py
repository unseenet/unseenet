"""What this machine can give key ripening: memory, and one ripening at a time (#440).

With chiavdf's low-memory prover (1.2.1, #444) a segment takes about the same
memory whatever its length. Without it - an older chiavdf, a browser build - memory
grows with the length (``core.ripening.memory_for``), so a client asks how much the
machine has free - inside a container, the container's own limit counts - and keeps
the segments within it. Large segments take one lock for the whole machine
(``lock_path``, #677), so two programs (a client and a bot, several bots, under
different users) do not ripen at once and exhaust the memory together.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

SHARE = 0.6                       # of the free memory, for ripening
UNKNOWN = 1 << 30                 # when nothing can be learnt: 1 GiB
BROWSER = 256 << 20               # a browser worker (Pyodide)
LOCK_ABOVE = 256 << 20            # segments needing more than this take the lock


def free_memory() -> int | None:
    """Octets of memory free for a new program now, as far as can be learnt."""
    if sys.platform == "emscripten":
        return BROWSER
    if sys.platform.startswith("linux"):
        free = None
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    free = int(line.split()[1]) * 1024
        except OSError:
            pass
        limit = _cgroup_room()
        if limit is not None:
            free = limit if free is None else min(free, limit)
        return free
    if sys.platform == "darwin":
        try:
            import subprocess
            total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                       text=True, timeout=5).stdout.strip())
            return total // 2                 # macOS does not say "available" simply
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    if sys.platform == "win32":
        try:
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                            ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong),
                            ("ve", ctypes.c_ulonglong)]
            st = Status(length=ctypes.sizeof(Status))
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.avail)
        except (OSError, AttributeError):
            pass
    return None


def _cgroup_room(root: Path = Path("/sys/fs/cgroup"),
                 own: Path = Path("/proc/self/cgroup")) -> int | None:
    """The room left under this process's tightest memory limit: the limit less what is
    used, for its own cgroup and every one above it - a systemd service's ``MemoryMax``
    inside a container counts as well as the container's (gateway#47). cgroup v2, else
    v1. None without a limit."""
    rooms = []
    rel = None
    try:
        for line in own.read_text().splitlines():
            if line.startswith("0::"):                 # cgroup v2: one unified path
                rel = line[3:].strip()
    except OSError:
        pass
    if rel is not None:
        here = root / rel.lstrip("/")
        while True:
            room = _room(here / "memory.max", here / "memory.current")
            if room is not None:
                rooms.append(room)
            if here == root or root not in here.parents:
                break
            here = here.parent
    if not rooms:                                      # v1, or v2 seen from the root only
        for limit_f, used_f in ((root / "memory.max", root / "memory.current"),
                                (root / "memory" / "memory.limit_in_bytes",
                                 root / "memory" / "memory.usage_in_bytes")):
            room = _room(limit_f, used_f)
            if room is not None:
                rooms.append(room)
                break
    return min(rooms) if rooms else None


def _room(limit_f: Path, used_f: Path) -> int | None:
    """``limit - used`` from a cgroup's files; None when unlimited or unreadable."""
    try:
        limit = limit_f.read_text().strip()
        used = int(used_f.read_text().strip())
    except (OSError, ValueError):
        return None
    if limit == "max" or not limit.isdigit() or int(limit) >= 1 << 60:
        return None
    return max(0, int(limit) - used)


def ripening_budget() -> int:
    """Octets key ripening may use: ``UNSEENET_RIPENING_MEMORY`` (MiB) if set, else a
    share of what the machine has free."""
    env = os.environ.get("UNSEENET_RIPENING_MEMORY")
    if env:
        try:
            return int(float(env) * (1 << 20))
        except ValueError:
            pass
    free = free_memory()
    return int((free if free is not None else UNKNOWN) * SHARE)


LOCK_NAME = "unseenet-ripening.lock"
SHARED_LOCK_DIRS = ("/run/lock", "/dev/shm")   # not made private by systemd's PrivateTmp


def lock_path() -> Path:
    """Where the ripening lock lives: one file for every user and service on this
    machine (#677) - ``UNSEENET_RIPENING_LOCK`` if set, else the first writable of
    ``/run/lock`` and ``/dev/shm`` on Linux. Elsewhere (Windows, macOS, phones), or
    where neither can be written, a file of this user's in the temporary directory."""
    env = os.environ.get("UNSEENET_RIPENING_LOCK")
    if env:
        return Path(env)
    if sys.platform.startswith("linux"):
        for d in SHARED_LOCK_DIRS:
            if os.path.isdir(d) and os.access(d, os.W_OK | os.X_OK):
                return Path(d) / LOCK_NAME
    return _user_lock_path()


def _user_lock_path() -> Path:
    return Path(tempfile.gettempdir()) / f"unseenet-ripening-{_user()}.lock"


class RipeningLock:
    """One large ripening at a time on this machine: an exclusive lock on one file
    shared by every Unseenet program of every user (``lock_path``, #677)."""

    def __init__(self, path: Path | None = None):
        self.path = path or lock_path()
        self._f = None

    def _open(self):
        """Open the lock file without O_CREAT when it is there, so a file another user
        made can be locked too in a sticky directory (Linux' protected_regular); made
        world-readable when we create it. flock needs no write access."""
        if sys.platform == "win32":
            return open(self.path, "a+")
        try:
            fd = os.open(self.path, os.O_RDONLY)
        except FileNotFoundError:
            try:
                fd = os.open(self.path, os.O_RDONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:                    # made by another meanwhile
                fd = os.open(self.path, os.O_RDONLY)
        return os.fdopen(fd, "r")

    def acquire(self) -> bool:
        """Take the lock if it is free; False if another program holds it."""
        try:
            self._f = self._open()
        except OSError:
            if self.path == _user_lock_path():
                raise
            self.path = _user_lock_path()             # the shared file can't be opened here
            self._f = self._open()
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self._f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._f.close()
            self._f = None
            return False

    def release(self) -> None:
        if self._f is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
            finally:
                self._f.close()
                self._f = None


def _user() -> str:
    try:
        return str(os.getuid())
    except AttributeError:                    # Windows
        return os.environ.get("USERNAME", "user")
