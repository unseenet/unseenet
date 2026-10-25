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
