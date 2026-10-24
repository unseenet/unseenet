"""#495: your own feed at the top of the group list, and the feed and follow buttons
on profiles, in the terminal client."""

import pytest

pytest.importorskip("textual")

from unseenet.client.session import Session  # noqa: E402
from unseenet.client.tui import START_FEED, START_SITE, ProfileDialog, UnseenetApp  # noqa: E402
from unseenet.core.store import Store  # noqa: E402
from unseenet.core.vault import Vault  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

from tuihelp import app_ready, press, stack, wait_for  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


async def _setup(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), sites="accept"))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(addr)
    s.data["starter_groups"] = 99
    await s.ensure_inbox()
    await s.close()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    return UnseenetApp(tmp_path / "me.vault"), server, addr


def _top(app):
    return [n.data for n in app.query_one("#groups").root.children]


def test_session_knows_whether_your_feed_is_started_and_whom_you_follow(tmp_path):
    s = Session(Vault.open(tmp_path / "s.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    assert not s.has_personal_group("feed")
    gid = s.personal_group("feed")
    s.subscribe(gid)
    assert not s.has_personal_group("feed")          # followed, but not yours here
    s.group_entry(gid)["owner"] = True
    assert s.has_personal_group("feed")
    other = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    other.new_identity("o", "O")
    key = other.identity().key_text
    assert not s.is_following(key) and not s.is_following("not a key")


async def test_tui_start_my_feed_at_the_top_then_my_feed(tmp_path, monkeypatch):
    app, server, _ = await _setup(tmp_path, monkeypatch)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        assert await wait_for(pilot, lambda: START_FEED in _top(app), 200)
        tree = app.query_one("#groups")
        node = next(n for n in tree.root.children if n.data == START_FEED)
        tree.select_node(node)
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog", 100)
        await press(pilot, app, "#ok")
        gid = app.session.personal_group("feed")
        assert await wait_for(pilot, lambda: app.session.has_personal_group("feed"), 400)
        assert await wait_for(pilot, lambda: gid in _top(app) and START_FEED not in _top(app), 300)
        # listed once: at the top, not again in its hierarchy further down
        def leaves(n):
            for c in n.children:
                yield c
                yield from leaves(c)
        assert [n.data for n in leaves(tree.root)].count(gid) == 1
        label = str(next(n for n in tree.root.children if n.data == gid).label)
        assert "My feed" in label
        await pilot.press("q")
    server.close()


async def test_tui_profile_buttons_start_my_feed_and_follow(tmp_path, monkeypatch):
    app, server, addr = await _setup(tmp_path, monkeypatch)
    alice = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    alice.new_identity("alice", "Alice")
    alice.add_node(addr)
    feed = await alice.start_personal_group("feed")
    await alice.post(feed, "Hej", "Fra Alice\n")
    site = await alice.start_personal_group("site")
    await alice.put_page(site, "index", "# Alices side\n")
    key = alice.identity().key_text
    await alice.close()
    async with app.run_test(size=(140, 40)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        # your own profile: Start my feed
        app.action_show_profile(app.session.identity().key_text)
        assert await wait_for(pilot, lambda: isinstance(app.screen, ProfileDialog), 200)
        assert str(app.screen.query_one("#my-feed").label) == "Start my feed"
        assert not app.screen.query("#follow")
        await press(pilot, app, "#my-feed")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog", 100)
        await press(pilot, app, "#cancel")
        assert not app.session.has_personal_group("feed")
        # someone else's: their site, read without following (#506)
        app.action_show_profile(key)
        assert await wait_for(pilot, lambda: isinstance(app.screen, ProfileDialog), 200)
        assert app.screen.query("#their-feed") and app.screen.query("#their-site")
        await press(pilot, app, "#their-site")
        assert await wait_for(pilot, lambda: app.current_group == site, 300)
        assert site not in app.session.data["subscribed"] and not app.session.is_following(key)
        # then Follow, then Following, and their feed
        app.action_show_profile(key)
        assert await wait_for(pilot, lambda: isinstance(app.screen, ProfileDialog), 200)
        assert str(app.screen.query_one("#follow").label) == "Follow"
        await press(pilot, app, "#follow")
        assert await wait_for(pilot, lambda: app.session.is_following(key), 400)
        assert await wait_for(pilot, lambda: feed in app.session.data["subscribed"], 200)
        app.action_show_profile(key)
        assert await wait_for(pilot, lambda: isinstance(app.screen, ProfileDialog), 200)
        assert str(app.screen.query_one("#follow").label) == "Following"
        await press(pilot, app, "#their-feed")
        assert await wait_for(pilot, lambda: app.current_group == feed, 200)
        app.action_show_profile(key)
        assert await wait_for(pilot, lambda: isinstance(app.screen, ProfileDialog), 200)
        await press(pilot, app, "#follow")                  # Following: stop
        assert await wait_for(pilot, lambda: not app.session.is_following(key), 200)
        await pilot.press("q")
    server.close()


async def test_tui_start_my_site_at_the_top_and_on_the_profile(tmp_path, monkeypatch):
    """My site works as My feed does: at the top, and a button on your own profile."""
    app, server, _ = await _setup(tmp_path, monkeypatch)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        assert await wait_for(pilot, lambda: START_SITE in _top(app), 200)
        app.action_show_profile(app.session.identity().key_text)
        assert await wait_for(pilot, lambda: isinstance(app.screen, ProfileDialog), 200)
        assert str(app.screen.query_one("#my-site").label) == "Start my site"
        await press(pilot, app, "#my-site")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog", 100)
        await press(pilot, app, "#ok")
        gid = app.session.personal_group("site")
        assert await wait_for(pilot, lambda: app.session.has_personal_group("site"), 400)
        assert await wait_for(pilot, lambda: gid in _top(app) and START_SITE not in _top(app), 300)
        tree = app.query_one("#groups")
        assert "My site" in str(next(n for n in tree.root.children if n.data == gid).label)
        await pilot.press("q")
    server.close()


async def test_tui_no_feed_or_site_buttons_for_someone_without_them(tmp_path, monkeypatch):
    app, server, addr = await _setup(tmp_path, monkeypatch)
    bob = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    bob.new_identity("bob", "Bob")
    key = bob.identity().key_text
    async with app.run_test(size=(140, 40)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        app.action_show_profile(key)
        assert await wait_for(pilot, lambda: isinstance(app.screen, ProfileDialog), 200)
        assert not app.screen.query("#their-feed") and not app.screen.query("#their-site")
        assert app.screen.query("#follow")
        await pilot.press("escape")
        await pilot.press("q")
    server.close()
