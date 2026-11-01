"""Servers that update themselves (UN-RFC 0062 section 6.1, #827): only signed, never
older, not all at once, back if broken."""

import hashlib
import sys

import pytest

from unseenet import service_update as su
from unseenet import update as up
from unseenet.core import crypto

HOUR = 3600.0


def _release(monkeypatch, version="0.7.0", req=None, sign=True):
    key = crypto.Identity.generate()
    monkeypatch.setattr(up, "TRUSTED", {"stable": (key.key_text,)})
    name = f"unseenet-{version}-server-requirements.txt"
    req = req if req is not None else (f"pynacl==1.6.2 --hash=sha256:{'a' * 64}\n"
                                       f"unseenet=={version} --hash=sha256:{'b' * 64}\n").encode()
    sums = f"{hashlib.sha256(req).hexdigest()}  {name}\n{'c' * 64}  unseenet-{version}.tar.gz\n".encode()
    signer = key if sign else crypto.Identity.generate()
    files = {up.SUMS: sums, up.SIG: up.signature_text(sums, signer).encode(), name: req}
    return lambda url: files[url.rsplit("/", 1)[1]]


def test_only_a_signed_release_with_its_requirements(monkeypatch):
    rel = su.newest_release(_release(monkeypatch))
    assert rel.version == "0.7.0" and b"--hash=" in rel.requirements
    with pytest.raises(su.Problem, match="not trusted"):
        su.newest_release(_release(monkeypatch, sign=False))
    fetch = _release(monkeypatch)
    tampered = lambda url: (b"x" + fetch(url)) if url.endswith("requirements.txt") else fetch(url)  # noqa: E731
    with pytest.raises(su.Problem, match="does not match"):
        su.newest_release(tampered)
    with pytest.raises(su.Problem, match="does not name"):
        su.newest_release(_release(monkeypatch, req=b"pynacl==1.6.2 --hash=sha256:aa\n"))


class FakeMachine:
    def __init__(self, have="0.6.9", comes_up=True):
        self.have, self.comes_up, self.did = have, comes_up, []

    def installed(self):
        return self.have

    def copy(self):
        self.did.append("copy")

    def install(self, requirements, workdir):
        self.did.append("install")
        self.new = requirements

    def restart(self):
        self.did.append("restart")

    def healthy(self):
        return self.comes_up

    def restore(self):
        self.did.append("restore")


def test_waits_a_random_time_then_updates(tmp_path):
    clock = [1000.0]
    st = su.State.load(tmp_path / "state.json")
    m = FakeMachine()
    rel = lambda: su.Release("0.7.0", b"unseenet==0.7.0 --hash=sha256:x\n")  # noqa: E731
    first = su.run(m, st, rel, now=lambda: clock[0], say=lambda _: None)
    due = st.due_at("0.7.0", clock[0])
    assert first == "waiting" and clock[0] <= due <= clock[0] + 48 * HOUR and m.did == []
    clock[0] = due + 1
    assert su.run(m, su.State.load(tmp_path / "state.json"), rel, now=lambda: clock[0],
                  say=lambda _: None) == "updated"
    assert m.did == ["copy", "install", "restart"]
    m.have = "0.7.0"
    assert su.run(m, su.State.load(tmp_path / "state.json"), rel, say=lambda _: None) == "current"


def test_never_older(tmp_path):
    m = FakeMachine(have="0.7.1")
    out = su.run(m, su.State.load(tmp_path / "s.json"), lambda: su.Release("0.7.0", b""),
                 say=lambda _: None)
    assert out == "current" and m.did == []


def test_back_if_broken_and_that_version_skipped(tmp_path):
    m = FakeMachine(comes_up=False)
    st = su.State.load(tmp_path / "s.json")
    rel = lambda: su.Release("0.7.0", b"")  # noqa: E731
    said = []
    assert su.run(m, st, rel, say=said.append, at_once=True) == "rolled-back"
    assert m.did == ["copy", "install", "restart", "restore", "restart"]
    assert any(s.startswith("ERROR") for s in said)
    m.did.clear()
    st = su.State.load(tmp_path / "s.json")
    assert su.run(m, st, rel, say=said.append, at_once=True) == "skipped" and m.did == []
    assert "Skipped (broke here): 0.7.0" in su.explain(st)


def test_off_still_tells_the_operator(tmp_path):
    clock = [0.0]
    st = su.State.load(tmp_path / "s.json")
    st.note(off=True)
    m, said = FakeMachine(), []
    rel = lambda: su.Release("0.7.0", b"")  # noqa: E731
    assert su.run(m, st, rel, now=lambda: clock[0], say=said.append) == "off"
    assert not said[-1].startswith("WARNING")
    clock[0] = 31 * 86400
    assert su.run(m, st, rel, now=lambda: clock[0], say=said.append) == "off"
    assert said[-1].startswith("WARNING") and m.did == []


@pytest.mark.skipif(sys.platform == "win32", reason="servers run Linux; cp -a")
def test_a_real_environment_is_copied_and_put_back(tmp_path):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "marker").write_text("old")
    m = su.Machine("x", venv)
    m.copy()
    (venv / "bin" / "marker").write_text("new")
    m.restore()
    assert (venv / "bin" / "marker").read_text() == "old" and not m.prev.exists()


def test_a_replica_updates_through_it(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from unseenet.replica import cli
    monkeypatch.setattr(cli, "read_config", lambda d: {"channel": "stable"})
    monkeypatch.setattr(su, "STATE_ROOT", tmp_path)
    seen = []
    monkeypatch.setattr(su, "run", lambda m, st: seen.append((m.service, st.data["off"])) or "current")
    assert cli.update(SimpleNamespace(dir=str(tmp_path))) == 0
    assert seen == [(cli.SERVICE, False)]
