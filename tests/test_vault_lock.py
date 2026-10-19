"""The vault lock (#141): two programs cannot open one vault at once."""

import socket
import subprocess
import sys
import textwrap

import pytest

from unseenet.core import vault as vault_mod
from unseenet.core.vault import Vault, VaultError, VaultLocked

KDF = {"ops": 1, "mem": 8192 * 1024}


def _other_program(path, hold_seconds: float = 0) -> subprocess.Popen:
    """Open the vault in another process and print what happened."""
    code = textwrap.dedent(f"""
        import sys, time
        from unseenet.core.vault import Vault, VaultLocked
        try:
            v = Vault.open({str(path)!r}, "pw", ops=1, mem=8192 * 1024)
        except VaultLocked:
            print("locked", flush=True); sys.exit(0)
        print("opened", flush=True)
        time.sleep({hold_seconds})
    """)
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)


def test_second_program_is_refused_and_can_open_after_close(tmp_path):
    path = tmp_path / "me.vault"
    v = Vault.open(path, "pw", **KDF)
    v.save()
    other = _other_program(path)
    assert other.communicate(timeout=60)[0].strip() == "locked"
    v.close()
    other = _other_program(path)
    assert other.communicate(timeout=60)[0].strip() == "opened"


def test_lock_dies_with_the_program(tmp_path):
    path = tmp_path / "me.vault"
    v = Vault.open(path, "pw", **KDF)
    v.save()
    v.close()
    holder = _other_program(path, hold_seconds=30)
    assert holder.stdout.readline().strip() == "opened"
    with pytest.raises(VaultLocked):
        Vault.open(path, "pw", **KDF)
    holder.kill()                                   # a crash: nobody releases anything
    holder.wait(timeout=30)
    Vault.open(path, "pw", **KDF).close()           # the OS lock went with the process


def test_same_program_may_open_twice(tmp_path):
    path = tmp_path / "me.vault"
    a = Vault.open(path, "pw", **KDF)
    b = Vault.open(path, "pw", **KDF)
    a.close()
    other = _other_program(path)
    assert other.communicate(timeout=60)[0].strip() == "locked"     # b still has it
    b.close()
    b.close()                                                         # twice is harmless
    other = _other_program(path)
    assert other.communicate(timeout=60)[0].strip() == "opened"


def test_wrong_passphrase_releases_the_lock(tmp_path):
    path = tmp_path / "me.vault"
    v = Vault.open(path, "pw", **KDF)
    v.save()
    v.close()
    with pytest.raises(VaultError) as info:
        Vault.open(path, "wrong", **KDF)
    assert not isinstance(info.value, VaultLocked)
    other = _other_program(path)
    assert other.communicate(timeout=60)[0].strip() == "opened"


def test_locked_message_says_what_to_do():
    assert "already open in another Unseenet program" in str(VaultLocked(vault_mod.LOCKED_MESSAGE))


def test_file_systems_without_locks_use_pid_and_host(tmp_path, monkeypatch):
    """FAT on macOS: no OS locks, so "pid host" in the file decides."""
    monkeypatch.setattr(vault_mod, "_os_lock", lambda fd: None)
    path = tmp_path / "me.vault"
    lock_file = tmp_path / "me.vault.lock"

    lock_file.write_text(f"999999999 {socket.gethostname()}\n")      # a crashed program here
    v = Vault.open(path, "pw", **KDF)
    assert lock_file.read_text().split()[0] != "999999999"
    v.close()
    assert not lock_file.exists()

    lock_file.write_text("1 some-other-computer\n")                 # the stick moved
    Vault.open(path, "pw", **KDF).close()

    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lock_file.write_text(f"{holder.pid} {socket.gethostname()}\n")   # alive, here
        with pytest.raises(VaultLocked):
            Vault.open(path, "pw", **KDF)
    finally:
        holder.kill()
        holder.wait(timeout=30)
