"""Portable layout: data beside the programs, the bundled Tor first."""

import sys
from pathlib import Path

import unseenet.portable as portable
from unseenet.core.tor import TorProcess


def fake_build(tmp_path: Path, monkeypatch, os_dir="linux") -> Path:
    """A portable tree with the program in <root>/<os>/ and pretend it is running."""
    root = tmp_path / "Unseenet"
    prog = root / os_dir
    (prog / "tor").mkdir(parents=True)
    tor = prog / "tor" / ("tor.exe" if sys.platform == "win32" else "tor")
    tor.write_text("")
    (root / portable.MARKER).write_text("")
    monkeypatch.setattr(portable, "program_dir", lambda: prog)
    monkeypatch.delenv("UNSEENET_HOME", raising=False)
    monkeypatch.delenv("UNSEENET_TOR", raising=False)
    return root


def test_not_portable_uses_the_current_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(portable, "program_dir", lambda: tmp_path / "site-packages" / "unseenet")
    monkeypatch.delenv("UNSEENET_HOME", raising=False)
    assert portable.portable_root() is None
    assert portable.default_vault_path() == Path("unseenet.vault")


def test_portable_keeps_data_beside_the_programs(monkeypatch, tmp_path):
    root = fake_build(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)                 # started from somewhere else
    assert portable.portable_root() == root
    assert portable.default_vault_path() == root / "data" / "unseenet.vault"
    assert (root / "data").is_dir()


def test_bundled_tor_comes_before_the_system_one(monkeypatch, tmp_path):
    root = fake_build(tmp_path, monkeypatch, "windows")
    found = Path(TorProcess.find_binary())
    assert found.parent == root / "windows" / "tor"
    monkeypatch.setenv("UNSEENET_TOR", str(found))   # an explicit choice still wins
    assert Path(TorProcess.find_binary(str(found))) == found


def test_unseenet_home_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("UNSEENET_HOME", str(tmp_path / "elsewhere"))
    assert portable.default_vault_path() == (tmp_path / "elsewhere").resolve() / "data" / "unseenet.vault"
