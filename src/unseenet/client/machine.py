"""What this machine can give key ripening: memory, and one ripening at a time (#440).

Proving a segment of a key's ripening takes memory in proportion to its length
(``core.ripening.memory_for``), so a client asks how much the machine has free -
inside a container, the container's own limit counts - and keeps the segments
within it. Large segments take a lock, so two programs on one machine (a client and
a bot, several bots) do not ripen at once and exhaust the memory together.
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


class RipeningLock:
    """One large ripening at a time on this machine: an exclusive lock on a file in
    the temporary directory, shared by every Unseenet program of this user."""

    def __init__(self, path: Path | None = None):
        self.path = path or Path(tempfile.gettempdir()) / f"unseenet-ripening-{_user()}.lock"
        self._f = None

    def acquire(self) -> bool:
        """Take the lock if it is free; False if another program holds it."""
        self._f = open(self.path, "a+")
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
