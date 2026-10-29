"""A Tor left running in our data directory must not block the next start (29 Oct 2026:
an earlier GUI's Tor held the directory, and the new one waited for it forever)."""
import asyncio
import os
import shutil
import subprocess
import sys
import time

import pytest

from unseenet.core.tor import TorProcess

TOR = shutil.which("tor")
pytestmark = pytest.mark.skipif(TOR is None, reason="needs tor")


def _left_running(data_dir):
    """A Tor started as an earlier run did, with no owner: control port and cookie in
    the directory, holding its lock."""
    data_dir.mkdir(mode=0o700)
    (data_dir / "torrc").write_text("")
    p = subprocess.Popen([TOR, "-f", str(data_dir / "torrc"), "--DataDirectory", str(data_dir),
                          "--SocksPort", "0", "--ControlPort", "auto", "--DisableNetwork", "1",
                          "--ControlPortWriteToFile", str(data_dir / "control_port"),
                          "--CookieAuthentication", "1",
                          "--CookieAuthFile", str(data_dir / "control_auth_cookie")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if (data_dir / "control_port").exists() and (data_dir / "control_auth_cookie").exists():
            break
        time.sleep(0.1)
    return p


def test_a_tor_left_running_is_halted(tmp_path):
    d = tmp_path / "tor"
    old = _left_running(d)
    try:
        assert asyncio.run(TorProcess(data_dir=d, binary=TOR).halt_stale()) is True
        old.wait(timeout=15)                       # it is gone
    finally:
        if old.poll() is None:
            old.kill()


def test_nothing_to_halt(tmp_path):
    d = tmp_path / "tor"
    d.mkdir()
    assert asyncio.run(TorProcess(data_dir=d, binary=TOR).halt_stale()) is False
    (d / "control_port").write_text("PORT=127.0.0.1:1\n")
    (d / "control_auth_cookie").write_bytes(b"x" * 32)
    assert asyncio.run(TorProcess(data_dir=d, binary=TOR).halt_stale()) is False


@pytest.mark.skipif(sys.platform == "win32", reason="kills a process the POSIX way")
def test_tor_quits_when_its_program_is_gone(tmp_path):
    """__OwningControllerProcess: a program that dies without stopping its Tor leaves
    none behind."""
    d = tmp_path / "tor"
    script = f"""
import asyncio, os, signal
from pathlib import Path
from unseenet.core.tor import TorProcess
t = TorProcess(data_dir=Path({str(d)!r}), binary={TOR!r})

async def main():
    try:
        await t.start(timeout=20)
    except Exception:
        pass                               # no network needed: started is enough
    print(t.process.pid, flush=True)
    os.kill(os.getpid(), signal.SIGKILL)   # gone without a word to its Tor
asyncio.run(main())
"""
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                         timeout=60).stdout.split()
    assert out, "the program did not start its Tor"
    pid = int(out[0])
    for _ in range(60):                        # Tor checks its owner about once a second
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.5)
    os.kill(pid, 9)
    pytest.fail("Tor kept running after its program was gone")


@pytest.mark.skipif(sys.platform == "win32", reason="starts a program the POSIX way")
def test_a_tor_another_running_program_uses_is_never_stopped(tmp_path):
    """0.6.2 stopped any Tor in the folder's data directory - also one another running
    Unseenet program used (two vaults in one folder), cutting a copy in progress off its
    onion service. Now that Tor is left alone and the start says why."""
    from unseenet.core.tor import TorError
    d = tmp_path / "tor"
    script = f"""
import asyncio, time
from pathlib import Path
from unseenet.core.tor import TorProcess
t = TorProcess(data_dir=Path({str(d)!r}), binary={TOR!r})

async def main():
    try:
        await t.start(timeout=20)
    except Exception:
        pass
    print(t.process.pid, flush=True)
    time.sleep(60)                         # the other program, still running
asyncio.run(main())
"""
    other = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    try:
        tor_pid = int(other.stdout.readline())
        for _ in range(50):                     # its control port is written
            if (d / "control_port").exists():
                break
            time.sleep(0.1)
        with pytest.raises(TorError, match="Another Unseenet program"):
            asyncio.run(TorProcess(data_dir=d, binary=TOR).halt_stale())
        os.kill(tor_pid, 0)                     # its Tor still runs
    finally:
        other.kill()
        other.wait()
