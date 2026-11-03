"""#822, UN-RFC 0062 section 6: the user chooses whom a stick takes updates from - the
project, or another publisher added by its first key list - and everything kept is
kept per publisher."""

from types import SimpleNamespace

import pytest

from unseenet import publishers as pb
from unseenet import release_keys as rk
from unseenet import service_update as su
from unseenet import update
from unseenet.core.crypto import Identity
from unseenet.known_nodes import RELEASES_GROUP

OTHER = "dk.builds@abcdefghijklmnop"
SUMS = ("a" * 64 + "  unseenet-9.9.9-linux-x86_64.zip\n").encode()


@pytest.fixture
def keys():
    return [Identity.generate() for _ in range(3)]


def channel(keys, sums=SUMS, by=None):
    """The posts of another publisher's releases channel: its first key list, posted by
    one of its keys, and a release signed by two of them."""
    first = rk.make_body(1, [k.key_text for k in keys], 2, {"dev": 1})
    sig = update.add_signature(update.signature_text(sums, keys[0]), sums, keys[1])
    return first, [((by or keys[0]).key_text, "release-keys 1", first),
                   (keys[0].key_text, "release", update.release_post(sums, sig, "stable", rk.parse(first))[1])]


def test_a_stick_follows_the_project_until_told_otherwise(tmp_path):
    assert pb.followed(None) == pb.PROJECT and pb.followed(tmp_path) == pb.PROJECT
    assert pb.PROJECT.first_list() == rk.first() and pb.PROJECT.is_project


def test_a_channel_shows_its_first_key_list_and_releases(keys, tmp_path):
    first, items = channel(keys)
    p = pb.preview(OTHER, items)
    assert p.first == first and p.keys.seq == 1 and not p.fork
    assert p.releases == {"stable": "9.9.9"}
    assert len(p.fingerprint) == 19 and p.fingerprint.count("-") == 3
    # one signature is not enough for its stable channel
    one = update.signature_text(SUMS, keys[0])
    assert pb.preview(OTHER, [items[0], (keys[0].key_text, "r",
                                         update.release_post(SUMS, one, "dev", p.keys)[1].replace(", dev", ", stable"))]
                      ).releases == {}
    # a first list posted by a stranger is no publisher's
    with pytest.raises(pb.PublisherProblem, match="no first key list"):
        pb.preview(OTHER, channel(keys, by=Identity.generate())[1])
    # two different first lists: trust neither
    other = rk.make_body(1, [keys[1].key_text], 1)
    with pytest.raises(pb.PublisherProblem, match="two different"):
        pb.preview(OTHER, items + [(keys[1].key_text, "release-keys 1", other)])


def test_add_follow_and_remove(keys, tmp_path):
    _, items = channel(keys)
    p = pb.preview(OTHER, items)
    got = pb.add(tmp_path, p, "Danske builds")
    assert got.follow == RELEASES_GROUP and [x.group for x in got.known] == [RELEASES_GROUP, OTHER]
    with pytest.raises(pb.PublisherProblem, match="already"):
        pb.add(tmp_path, p)
    assert pb.follow(tmp_path, OTHER).followed.name == "Danske builds"
    assert pb.followed(tmp_path).first_list() == p.keys
    pb.remove(tmp_path, OTHER)
    assert pb.followed(tmp_path) == pb.PROJECT
    pb.remove(tmp_path, RELEASES_GROUP)                    # the project too
    assert pb.followed(tmp_path) is None
    with pytest.raises(pb.PublisherProblem, match="first"):
        pb.follow(tmp_path, OTHER)
    got = pb.add(tmp_path, p)                              # the only one: followed
    assert got.follow == OTHER


def test_what_is_kept_is_kept_per_publisher(keys, tmp_path):
    kl = rk.parse(rk.make_body(1, [keys[0].key_text], 1))
    update.keep_keys(tmp_path, kl, OTHER)
    assert update.kept_keys(tmp_path, OTHER) == kl.body
    assert update.kept_keys(tmp_path) is None              # not the project's
    assert update.kept_sources(tmp_path, OTHER).files == ()  # no GitHub of the project's
    assert update.release_urls("stable", "x.zip", "1.0", None, project=False) == []


def test_another_publishers_releases_count_by_its_keys(keys, monkeypatch):
    first, items = channel(keys)
    start = rk.parse(first)
    sig = update.add_signature(update.signature_text(SUMS, keys[0]), SUMS, keys[1])
    assert update.check_signature(SUMS, sig, "stable", start) == keys[0].key_text
    with pytest.raises(update.UpdateError):               # not the project's keys
        update.check_signature(SUMS, sig, "stable")
    two = rk.make_body(2, [keys[2].key_text], 1, prev=start)
    got, fork = rk.newest([(keys[0].key_text, two), (keys[1].key_text, two)], None, start)
    assert got.seq == 2 and not fork


def test_a_server_follows_another_publisher(keys):
    first, _ = channel(keys)
    state = su.State(path=None, data={"off": False, "release_keys": {"body": "x"},
                                      "sources": {"v": 1}})
    su.set_publisher(state, OTHER, first)
    assert state.data["publisher"] == {"group": OTHER, "first": first}
    assert "release_keys" not in state.data and "sources" not in state.data
    assert any("Publisher" in line for line in su.explain(state))
    with pytest.raises(su.Problem, match="first key list"):
        su.set_publisher(state, OTHER, None)
    su.set_publisher(state, None, None)
    assert "publisher" not in state.data
    # with nothing in the network, another publisher's release is not looked for on GitHub
    with pytest.raises(su.Problem, match="from this publisher"):
        su.newest_release(lambda u: pytest.fail("asked GitHub"), network=lambda: [],
                          start=rk.parse(first))


async def test_the_client_follows_the_sticks_publisher(keys, tmp_path, monkeypatch):
    from unseenet.client.session import Session, SessionError
    from unseenet.core.vault import Vault
    s = Session(Vault.open(tmp_path / "v.vault", "pw", ops=1, mem=8192 * 1024),
                status=lambda *_: None)
    stick = tmp_path / "stick"
    stick.mkdir()
    monkeypatch.setattr(update, "find_stick", lambda: stick)
    first, items = channel(keys)
    read = []

    async def fetch_group(group):
        read.append(group)
        return [SimpleNamespace(readable=True, author_key=a, subject=sub, body=b)
                for a, sub, b in (items if group == OTHER else [])]
    monkeypatch.setattr(s, "fetch_group", fetch_group)
    from unseenet.core.addresses import group_address
    shown = await s.publisher_preview(group_address(OTHER))
    assert shown.group == OTHER
    with pytest.raises(SessionError, match="fingerprint is"):
        await s.add_publisher(OTHER, "0000-0000-0000-0000")
    got = await s.add_publisher(OTHER, shown.fingerprint.upper(), "Danske", follow=True)
    assert got["follow"] == OTHER and got["publishers"][1]["followed"]
    await s.refresh_releases()
    assert read[-1] == OTHER and s.data["releases"]["stable"]["version"] == "9.9.9"
    assert s.data["release_keys"]["group"] == OTHER
    # back to the project: what was counted for the other one is not used
    s.change_publisher("follow", RELEASES_GROUP)
    await s.refresh_releases()
    assert read[-1] == RELEASES_GROUP and not s.data.get("releases")
    s.change_publisher("remove", RELEASES_GROUP)
    s.change_publisher("remove", OTHER)
    assert await s.refresh_releases() is None


def test_no_stick_where_looking_is_not_allowed(monkeypatch):
    """On a computer whose /boot/efi the user cannot read, there is no stick: the client
    follows the project, it does not fail (GitHub's runners are such computers)."""
    import unseenet.boot as boot

    def refused():
        raise PermissionError(13, "Permission denied", "/boot/efi/unseenet.apkovl.tar.gz")
    monkeypatch.setattr(boot, "find_media", refused)
    import unseenet.portable as portable
    monkeypatch.setattr(portable, "portable_root", lambda: None)
    assert update.find_stick() is None
    assert pb.followed(update.find_stick()) == pb.PROJECT


def test_the_routes_are_there():
    from unseenet.client.localapi import server as srv
    routes = {(m, p) for m, p, _ in srv.ROUTES}
    assert {("GET", "/api/publishers"), ("POST", "/api/publishers")} <= routes
