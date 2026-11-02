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


def _service_release(monkeypatch, package="unseenet-gateway", version="0.6.0"):
    key = crypto.Identity.generate()
    monkeypatch.setattr(up, "TRUSTED", {"stable": (key.key_text,)})
    name = f"{package}-{version}-server-requirements.txt"
    req = (f"unseenet==0.8.0 --hash=sha256:{'a' * 64}\n"
           f"{package}=={version} --hash=sha256:{'b' * 64}\n").encode()
    sums = f"{hashlib.sha256(req).hexdigest()}  {name}\n".encode()
    files = {up.SUMS: sums, up.SIG: up.signature_text(sums, key).encode(), name: req}
    asked = []

    def fetch(url):
        asked.append(url)
        return files[url.rsplit("/", 1)[1]]
    return fetch, asked


def test_any_service_from_its_own_repository(monkeypatch):
    fetch, asked = _service_release(monkeypatch)
    rel = su.newest_release(fetch, package="unseenet-gateway")
    assert rel.version == "0.6.0"
    assert all(u.startswith("https://github.com/unseenet/unseenet-gateway/releases/") for u in asked)
    # the core does not take a service's requirements as its own, nor the reverse
    fetch, _ = _service_release(monkeypatch)
    with pytest.raises(su.Problem, match="no server requirements"):
        su.newest_release(fetch)
    fetch, _ = _service_release(monkeypatch, package="unseenet-gateway")
    with pytest.raises(su.Problem, match="no server requirements"):
        su.newest_release(fetch, package="unseenet-watchman")
    fetch, asked = _service_release(monkeypatch, package="unseenet-bots")
    su.newest_release(fetch, package="unseenet-bots", repo="someone/fork")
    assert asked[0].startswith("https://github.com/someone/fork/")
    with pytest.raises(su.Problem, match="not a repository"):
        su.repo_url("a/b/../c?x")


def test_requirements_names():
    assert su.requirements_version("unseenet-0.8.0-server-requirements.txt", "unseenet") == "0.8.0"
    assert su.requirements_version("unseenet-gateway-0.6.0-server-requirements.txt",
                                   "unseenet") is None                  # not a version
    assert su.requirements_version("unseenet-gateway-0.6.0rc1-server-requirements.txt",
                                   "unseenet-gateway") == "0.6.0rc1"
    assert su.requirements_version("unseenet-gateway-0.6.0.tar.gz", "unseenet-gateway") is None


def test_http_check(tmp_path):
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/ok" else 500)
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        assert su.Machine("x", tmp_path, f"http://127.0.0.1:{port}/ok").answers()
        assert not su.Machine("x", tmp_path, f"http://127.0.0.1:{port}/bad").answers()
        assert not su.Machine("x", tmp_path, "http://127.0.0.1:9/").answers()
    finally:
        srv.shutdown()


def test_cli_refuses_other_packages(capsys, tmp_path):
    assert su.main(["run", "--service", "x", "--package", "requests",
                    "--state", str(tmp_path)]) == 1
    assert "not an Unseenet package" in capsys.readouterr().out


def test_a_oneshot_service_is_not_restarted_and_must_load(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(su.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or
                        type("R", (), {"returncode": 0 if "import unseenet_bots" in cmd[-1] else 1,
                                       "stdout": "", "stderr": ""})())
    m = su.Machine("unseenet-bots", tmp_path, package="unseenet-bots", oneshot=True)
    m.restart()
    assert calls == []                                       # its timer runs it
    assert m.healthy()
    assert calls[-1][-1] == "import unseenet_bots"
    m = su.Machine("unseenet-x", tmp_path, package="unseenet-x", oneshot=True)
    assert not m.healthy()


def test_waits_while_the_service_is_busy(tmp_path):
    import os
    busy = tmp_path / "busy"
    st = su.State.load(tmp_path / "state.json")
    rel = lambda: su.Release("0.7.0", b"unseenet==0.7.0 --hash=sha256:x\n")  # noqa: E731
    m = FakeMachine()
    m.busy = lambda: su.Machine("x", tmp_path, busy=busy).busy()
    busy.write_text("ripening")
    assert su.run(m, st, rel, say=lambda _: None, at_once=True) == "waiting" and m.did == []
    old = busy.stat().st_mtime - su.BUSY_FOR - 1               # left over: not busy
    os.utime(busy, (old, old))
    assert su.run(m, st, rel, say=lambda _: None, at_once=True) == "updated"


def test_a_service_not_on_pypi_names_its_own_wheel():
    base = "https://github.com/unseenet/unseenet-helpbot"
    wheel = f"{base}/releases/download/v0.6.0/unseenet_helpbot-0.6.0-py3-none-any.whl"
    assert su.names_itself(f"x==1 --hash=sha256:a\nunseenet-helpbot @ {wheel} --hash=sha256:b\n",
                           "unseenet-helpbot", "0.6.0", base)
    other = wheel.replace("unseenet/unseenet-helpbot", "someone/else")
    assert not su.names_itself(f"unseenet-helpbot @ {other} --hash=sha256:b\n",
                               "unseenet-helpbot", "0.6.0", base)
    older = wheel.replace("0.6.0", "0.5.0")
    assert not su.names_itself(f"unseenet-helpbot @ {older} --hash=sha256:b\n",
                               "unseenet-helpbot", "0.6.0", base)
