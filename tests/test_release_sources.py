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


def test_a_known_list_alone_says_where():
    """UN-RFC 0062 6.3 (#917): the built-in sources (GitHub) are only where a new client
    starts; once a list is known, it alone says where - so a council can take GitHub
    off the list when it is gone or used against the network."""
    urls = sources(files=(MIRROR,)).file_urls("unseenet-portable", "v0.8.0", "x.zip")
    assert urls == [f"http://{ONION}/releases/unseenet-portable/v0.8.0/x.zip"]
    clients = up.release_urls("stable", "x.zip", "0.8.0", sources(files=(MIRROR,)))
    assert clients[0].startswith(f"http://{ONION}/") and not any("github.com" in u for u in clients)
    both = up.release_urls("stable", "x.zip", "0.8.0", sources())
    assert both[0].startswith(f"http://{ONION}/") and "github.com" in both[-1]
    assert up.release_urls("stable", "x.zip", "0.8.0") == [
        up.release_url("stable", "x.zip", "0.8.0", r) for r in up.RELEASE_REPOS]
    assert up.release_urls("stable", "x.zip", "0.8.0", rs.BUILT_IN)[-1].startswith(
        "https://github.com/")


def test_clients_keep_the_newest_list_on_the_stick(tmp_path):
    media = tmp_path / "stick"
    assert up.kept_sources(media) == rs.BUILT_IN
    up.keep_sources(media, sources())
    assert up.kept_sources(media) == sources()
    up.keep_sources(media, rs.BUILT_IN)                      # never replaced by the built-in
    assert up.kept_sources(media) == sources()
    assert up.kept_council(media) is None
    up.keep_sources(media, sources(), "{\"v\":1}")                # and the council's list beside
    assert up.kept_council(media) == "{\"v\":1}" and up.kept_sources(media) == sources()


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


def test_the_list_needs_the_key_lists_threshold(monkeypatch):
    """UN-RFC 0062 6.3: signed like a release - two of three once the key list is pinned."""
    from unseenet import release_keys as rk
    keys = [crypto.Identity.generate() for _ in range(3)]
    kl = rk.parse(rk.make_body(1, [k.key_text for k in keys], 2, {"dev": 1}))
    monkeypatch.setattr(rk, "PROJECT_FIRST", kl.body)
    _, body = rs.make_post(sources(), keys[0])
    assert rs.parse_post(body) is None                       # one of two
    both = rs.add_signature(body, keys[1])
    assert rs.parse_post(both) == sources()
    assert rs.add_signature(both, keys[1]) == both           # once per key
    stranger = crypto.Identity.generate()
    assert rs.parse_post(rs.add_signature(body, stranger)) is None
    # a later key list, given, is the one checked against
    later = rk.parse(rk.make_body(2, [stranger.key_text], 1, prev=kl))
    assert rs.parse_post(rs.make_post(sources(), stranger)[1], later) == sources()
    with pytest.raises(rs.SourcesError):
        rs.add_signature("Unseenet 0.8.0, stable\n", keys[0])


def test_the_last_list_moves_to_a_council(project):
    """moved_to: from the first such list on, the publisher's later lists are not used."""
    council = "unseenet.lists@" + "a" * 16
    moved = rs.from_dict({**sources("2026-11-03T08:00:00Z").to_dict(), "moved_to": council})
    assert moved.moved_to == council and moved.to_dict()["moved_to"] == council
    later = sources("2026-12-01T00:00:00Z", files=("https://evil.example/{name}",))
    bodies = [rs.make_post(sources(), project)[1], rs.make_post(moved, project)[1],
              rs.make_post(later, project)[1]]
    assert rs.newest(bodies) == moved
    assert rs.newest([rs.make_post(later, project)[1]], moved.to_dict()) == moved   # kept
    with pytest.raises(rs.SourcesError, match="moved_to"):
        rs.from_dict({**sources().to_dict(), "moved_to": "no group"})


async def test_the_council_keeps_the_sources(tmp_path, monkeypatch, project):
    """UN-RFC 0020 6.8 / 0062 6.3: once the project's list names ``moved_to``, sticks and
    servers read the council's sources list through a node - signatures, members and
    publishers checked there - and go by it; a list a non-member posts does not count."""
    from datetime import date

    import unseenet.client.session as sess
    from unseenet.client.session import Session
    from unseenet.core import lists as ls
    from unseenet.core.store import Store
    from unseenet.core.vault import Vault
    from unseenet.known_nodes import RELEASES_GROUP
    from unseenet.nntp import Client
    from unseenet.node.server import Node, NodeConfig
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    made = []
    for name in ("a", "b", "stranger"):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", ops=1, mem=8192 * 1024),
                    status=lambda *_: None)
        s.new_identity(name, name)
        s.add_node(addr)
        made.append(s)
    a, b, stranger = made
    keys = [a.identity().key_text, b.identity().key_text]
    groups = {}
    for part, kind in (("claims", "open"), ("reports", "channel"), ("sources", "channel")):
        g, body = a.council_genesis(f"unseenet.lists.{part}", kind, keys, fields={"min_pow": 0})
        for s in (a, b):
            await s.council_sign(g, body)
        groups[part] = g
    gid, body = a.council_genesis("unseenet.lists", "channel", keys, fields={
        "min_pow": 0, "lists": {"sources": groups["sources"]}, "claims": groups["claims"],
        "reports": groups["reports"], "publishers": [RELEASES_GROUP]})
    for s in (a, b):
        await s.council_sign(gid, body)
    codeberg = {"files": ["https://codeberg.org/unseenet/{repo}/releases/download/{tag}/{name}"],
                "index": [rs.PYPI]}
    listed = ls.sources_list(day=date(2026, 11, 20), seq=1, imported=codeberg,
                             decisions=ls.DecisionState())
    await a.post(groups["sources"], "sources list 2026-11-20", listed,
                 content_type="application/json")
    c = await Client.connect(addr)
    try:
        got = await rs.read_council(c, gid, RELEASES_GROUP)
        assert got is not None and got.body.rstrip("\n") == listed.rstrip("\n")
        assert await rs.read_council(c, gid, "other.releases@" + "a" * 16) is None
    finally:
        await c.quit()
    # the project's last list points there; the council's list is what counts then
    moved = rs.from_dict({**sources().to_dict(), "moved_to": gid})
    body_moved = rs.make_post(moved, project)[1]
    assert rs.moved_to_in([body_moved, "x", got]) == {gid}
    used = rs.effective(rs.newest([body_moved]), got.body)
    assert used.files[0].startswith("https://codeberg.org/")
    assert rs.effective(sources(), got.body) == sources()           # not moved: its own
    assert rs.effective(moved, None) == moved                       # no council list yet
    urls = up.release_urls("stable", "x.zip", "0.8.0", used)
    assert urls and all(u.startswith("https://codeberg.org/") for u in urls)
    # a list posted by somebody who is not a member does not count
    fake = ls.sources_list(day=date(2026, 11, 21), seq=1,
                           imported={"files": ["https://evil.example/{name}"], "index": [rs.PYPI]},
                           decisions=ls.DecisionState())
    with pytest.raises(Exception):                  # a channel: the node refuses it already
        await stranger.post(groups["sources"], "sources list 2026-11-21", fake,
                            content_type="application/json")
    c = await Client.connect(addr)
    try:
        assert (await rs.read_council(c, gid, RELEASES_GROUP)).body == got.body
    finally:
        await c.quit()
    for s in made:
        await s.close()
    server.close()


def test_servers_go_by_the_councils_list(tmp_path, monkeypatch, project):
    """A server takes the council's list once its publisher moved there, and keeps it
    for when the network is gone."""
    from datetime import date

    from unseenet.core import lists as ls
    council = "unseenet.lists@" + "b" * 16
    moved = rs.from_dict({**sources().to_dict(), "moved_to": council})
    listed = ls.sources_list(day=date(2026, 11, 20), seq=1, imported={
        "files": ["https://codeberg.org/{repo}/{tag}/{name}"], "index": [rs.PYPI]},
        decisions=ls.DecisionState())
    got = [rs.make_post(moved, project)[1], rs.CouncilList(council, listed)]
    monkeypatch.setattr(su, "posts_in_network", lambda package, socks, node=None: got)
    monkeypatch.setattr(su, "newest_release", lambda *a, network=None, **k: network() and
                        su.Release("0.0.1", b""))
    seen = []
    monkeypatch.setattr(su, "run", lambda machine, state, find, **kw: find() and
                        seen.append(machine.sources) or "current")
    st = su.State.load(tmp_path / "state.json")
    su.update_service("x", tmp_path, st, direct=True)
    assert seen[-1].files == ("https://codeberg.org/{repo}/{tag}/{name}",)
    assert st.data["sources"]["moved_to"] == council and st.data["sources_council"] == listed
    monkeypatch.setattr(su, "posts_in_network", lambda package, socks, node=None: [])
    su.update_service("x", tmp_path, st, direct=True)          # the network is gone: kept
    assert seen[-1].files == ("https://codeberg.org/{repo}/{tag}/{name}",)
