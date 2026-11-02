"""#264: releases announced in unseenet.releases, and updating from mirrors."""
import pytest

from unseenet import __version__, update
from unseenet.core.crypto import Identity

KEY = Identity.from_seed(bytes(range(32)))
SUMS = ("a" * 64 + "  unseenet-9.9.9-linux-x86_64.zip\n"
        + "b" * 64 + "  unseenet-9.9.9-x86_64-update.zip\n").encode()


@pytest.fixture
def trusted(monkeypatch):
    monkeypatch.setitem(update.TRUSTED, "dev", (KEY.key_text,))
    monkeypatch.setitem(update.TRUSTED, "stable", (KEY.key_text,))


def test_post_carries_the_signed_sums_unchanged(trusted):
    sig = update.signature_text(SUMS, KEY)
    subject, body = update.release_post(SUMS, sig, "dev")
    assert subject == "Unseenet 9.9.9"
    channel, sums, sig2 = update.parse_release_post(body)
    assert (channel, sums) == ("dev", SUMS)
    rel = update.check_release(sums, sig2, "dev", "x86_64-update")
    assert rel.version == "9.9.9" and rel.signed_by == KEY.key_text


def test_posts_for_the_portable_and_the_bootable_sums_alone(trusted):
    """unseenet-portable and unseenet-bootable each sign and post their own sums (#550)."""
    portable = ("a" * 64 + "  unseenet-9.9.9-linux-x86_64.zip\n").encode()
    images = ("b" * 64 + "  unseenet-9.9.9-x86_64.img.xz\n"
              + "c" * 64 + "  unseenet-9.9.9-x86_64-update.zip\n").encode()
    for sums in (portable, images):
        subject, _ = update.release_post(sums, update.signature_text(sums, KEY), "dev")
        assert subject == "Unseenet 9.9.9"
    nothing = ("d" * 64 + "  something-else.txt\n").encode()
    with pytest.raises(update.UpdateError):
        update.release_post(nothing, update.signature_text(nothing, KEY), "dev")


def test_a_changed_post_does_not_check_out(trusted):
    _, body = update.release_post(SUMS, update.signature_text(SUMS, KEY), "stable")
    channel, sums, sig = update.parse_release_post(body.replace("a" * 64, "c" * 64))
    with pytest.raises(update.UpdateError):
        update.check_release(sums, sig, channel)
    assert update.parse_release_post("Unseenet web client 20261021.1000\n\nabc\n") is None


def test_only_onions_over_plain_http():
    with pytest.raises(update.UpdateError):
        update.fetch("http://example.org/x.zip", 9050)
    with pytest.raises(update.UpdateError):
        update.fetch("http://abc.onion/x.zip", None)        # never without Tor


def test_offer_follows_the_channel(tmp_path):
    from unseenet.client.session import Session
    from unseenet.core.vault import Vault
    s = Session(Vault.open(tmp_path / "v.vault", "pw", ops=1, mem=8192 * 1024), status=lambda *_: None)
    channel = "dev" if ".dev" in __version__ else "stable"
    s.data["releases"] = {channel: {"version": "99.0.0"}}
    assert s.update_offer() == {"version": "99.0.0", "channel": channel}
    s.data["releases"] = {channel: {"version": "0.0.1"}}
    assert s.update_offer() is None
    # the graphical client asks for its own builds, by its own version (#264)
    s.data["releases"] = {"stable": {"version": "99.0.0", "gui": "0.7.0"}}
    assert s.update_offer("unseenet-gui", "0.6.0") == {"version": "0.7.0", "channel": "stable"}
    assert s.update_offer("unseenet-gui", "0.7.0") is None
    assert s.update_offer("unseenet-gui", "0.7.0.dev3") is None             # dev: none posted


async def test_releases_are_read_per_product(tmp_path, monkeypatch, trusted):
    """The portable sums carry both clients, the bootable ones only the terminal client:
    each product keeps its newest version (#264)."""
    from types import SimpleNamespace

    from unseenet.client.session import Session
    from unseenet.core.vault import Vault
    s = Session(Vault.open(tmp_path / "v.vault", "pw", ops=1, mem=8192 * 1024), status=lambda *_: None)
    portable = ("a" * 64 + "  unseenet-9.9.9-linux-x86_64.zip\n"
                + "b" * 64 + "  unseenet-gui-9.1.0-linux-x86_64.zip\n").encode()
    images = ("c" * 64 + "  unseenet-9.9.8-x86_64-update.zip\n").encode()
    posts = [SimpleNamespace(readable=True, body=update.release_post(x, update.signature_text(x, KEY),
                                                                     "stable")[1])
             for x in (portable, images)]

    async def fetch_group(group):
        return posts
    monkeypatch.setattr(s, "fetch_group", fetch_group)
    await s.refresh_releases()
    assert s.data["releases"]["stable"] == {"version": "9.9.9", "gui": "9.1.0"}


def test_a_mirror_is_found_by_every_version_it_has(monkeypatch):
    """unseenet-entrance#44: a mirror keeps the portable builds and the bootable images
    each at its own newest version, and names all of them in "mirror_all"; one that names
    only "mirror" (an older entrance) is found by that."""
    import json

    from unseenet import update
    said = {"new.onion": {"mirror": {"stable": "1.0.post1"}, "mirror_all": {"stable": ["1.0.post1", "1.0"]}},
            "old.onion": {"mirror": {"stable": "1.0"}},
            "none.onion": {}}
    monkeypatch.setattr(update, "fetch", lambda url, port: json.dumps(said[url.split("/")[2]]).encode())
    onions = list(said)
    assert sorted(update.mirrors_with(onions, "stable", "1.0", 9050)) == ["http://new.onion/", "http://old.onion/"]
    assert update.mirrors_with(onions, "stable", "1.0.post1", 9050) == ["http://new.onion/"]
    assert update.mirrors_with(onions, "dev", "1.0", 9050) == []
