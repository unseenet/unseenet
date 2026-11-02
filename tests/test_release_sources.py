"""#902: where releases are fetched from, set in the network by the project key."""

import hashlib
import json

import pytest

from unseenet import release_sources as rs
from unseenet import service_update as su
from unseenet import update as up
from unseenet.core import crypto

ONION = "a" * 56 + ".onion"
MIRROR = f"http://{ONION}/releases/{{repo}}/{{tag}}/{{name}}"


@pytest.fixture
def project(monkeypatch):
    key = crypto.Identity.generate()
    monkeypatch.setitem(up.TRUSTED, "stable", (key.key_text,))
    return key


def sources(updated="2026-11-02T20:00:00Z", files=(MIRROR, rs.GITHUB), index=(rs.PYPI,)):
    return rs.from_dict({"v": 1, "files": list(files), "index": list(index), "updated": updated})


def test_a_signed_list_round_trips(project):
    s = sources()
    subject, body = rs.make_post(s, project)
    assert subject == rs.HEAD and rs.parse_post(body) == s
    assert rs.parse_post(body.replace("pypi.org", "evil.example")) is None     # changed
    _, forged = rs.make_post(s, crypto.Identity.generate())
    assert rs.parse_post(forged) is None                                        # not the project's
    assert rs.parse_post("Unseenet 0.8.0, stable\n") is None


@pytest.mark.parametrize("bad", [
    {"files": ["http://plain.example/{name}"]},                # plain http, not an onion
    {"files": ["https://x.example/fixed.zip"]},                 # no {name}
    {"files": ["https://x.example/{name}/{evil}"]},             # an unknown field
    {"index": ["ftp://x.example/simple/"]},
    {"files": []},
    {"updated": "yesterday"},
])
def test_bad_lists_are_refused(bad):
    data = {"v": 1, "files": [MIRROR], "index": [rs.PYPI], "updated": "2026-11-02T20:00:00Z", **bad}
    with pytest.raises(rs.SourcesError):
        rs.from_dict(data)


def test_the_newest_list_wins_and_is_kept(project):
    old, new = sources("2026-11-01T00:00:00Z"), sources("2026-11-03T00:00:00Z", files=(MIRROR,))
    bodies = [rs.make_post(old, project)[1], rs.make_post(new, project)[1]]
    assert rs.newest(bodies) == new
    assert rs.newest([rs.make_post(old, project)[1]], new.to_dict()) == new   # kept, newer
    assert rs.newest([]) == rs.BUILT_IN
    assert rs.newest([], {"v": 1, "files": "x"}) == rs.BUILT_IN


def test_file_addresses_end_with_github():
    urls = sources(files=(MIRROR,)).file_urls("unseenet-portable", "v0.8.0", "x.zip")
    assert urls == [f"http://{ONION}/releases/unseenet-portable/v0.8.0/x.zip",
                    "https://github.com/unseenet/unseenet-portable/releases/download/v0.8.0/x.zip"]
    clients = up.release_urls("stable", "x.zip", "0.8.0", sources(files=(MIRROR,)))
    assert clients[0].startswith(f"http://{ONION}/") and any("github.com" in u for u in clients)
    assert up.release_urls("stable", "x.zip", "0.8.0") == [
        up.release_url("stable", "x.zip", "0.8.0", r) for r in up.RELEASE_REPOS]


def test_clients_keep_the_newest_list_on_the_stick(tmp_path):
    media = tmp_path / "stick"
    assert up.kept_sources(media) == rs.BUILT_IN
    up.keep_sources(media, sources())
    assert up.kept_sources(media) == sources()
    up.keep_sources(media, rs.BUILT_IN)                      # never replaced by the built-in
    assert up.kept_sources(media) == sources()


def test_pip_gets_the_indexes():
    args = su.index_args((f"http://{ONION}/simple/", rs.PYPI))
    assert args == ["--index-url", f"http://{ONION}/simple/", "--trusted-host", ONION,
                    "--extra-index-url", rs.PYPI]


def test_a_wheel_not_on_pypi_comes_from_the_sources(tmp_path, monkeypatch):
    wheel = b"the help bot's wheel"
    digest = hashlib.sha256(wheel).hexdigest()
    gh = "https://github.com/unseenet/unseenet-helpbot/releases/download/v0.6.0/unseenet_helpbot-0.6.0-py3-none-any.whl"
    asked = []

    def fetch(url, socks, dest=None, progress=None):
        asked.append(url)
        if "github.com" in url:
            raise up.UpdateError("GitHub is gone")
        dest.write_bytes(wheel)
        return b""
    monkeypatch.setattr(up, "fetch", fetch)
    m = su.Machine("unseenet-helpbot", tmp_path, package="unseenet-helpbot", socks_port=9050,
                   sources=sources(files=(MIRROR,)))
    req = f"six==1.16 --hash=sha256:{'c' * 64}\nunseenet-helpbot @ {gh} --hash=sha256:{digest}\n"
    out = m.localize(req.encode(), tmp_path).decode()
    assert asked[0].startswith(f"http://{ONION}/releases/unseenet-helpbot/v0.6.0/")
    assert "unseenet-helpbot @ file://" in out and f"--hash=sha256:{digest}" in out
    assert out.startswith("six==1.16")
    # a wrong file anywhere: the line stays as it was, and pip checks it
    monkeypatch.setattr(up, "fetch", lambda url, socks, dest=None, progress=None:
                        dest.write_bytes(b"something else") or b"")
    assert m.localize(req.encode(), tmp_path).decode() == req


def test_servers_keep_the_newest_list(tmp_path, monkeypatch, project):
    body = rs.make_post(sources(), project)[1]
    monkeypatch.setattr(su, "posts_in_network", lambda package, socks, node=None: [body])
    monkeypatch.setattr(su, "newest_release", lambda *a, network=None, **k: network() and
                        su.Release("0.0.1", b""))
    seen = []
    monkeypatch.setattr(su, "run", lambda machine, state, find, **kw: find() and
                        seen.append(machine.sources) or "current")
    st = su.State.load(tmp_path / "state.json")
    su.update_service("x", tmp_path, st, direct=True)
    assert seen == [sources()] and st.data["sources"] == sources().to_dict()
    monkeypatch.setattr(su, "posts_in_network", lambda package, socks, node=None: [])
    su.update_service("x", tmp_path, st, direct=True)         # the network is gone: kept
    assert seen[-1] == sources()
