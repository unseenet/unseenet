"""Writing a site's pages in the terminal client (UN-RFC 0035 section 9.2, #212): a new page
with a preview, a new version with e, the previous version again, and removing a page -
the same as unseenet-gui. Readers get no writing tools."""

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, TextArea  # noqa: E402

from unseenet.client.session import Session  # noqa: E402
from unseenet.client.tui import ConfirmDialog, PageDialog, PreviewDialog, UnseenetApp  # noqa: E402
from unseenet.core.store import Store  # noqa: E402
from unseenet.core.vault import Vault  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

from tuihelp import app_ready, laid_out, press, stack, wait_for  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


def _page(app, gid, path):
    return next((p for p in app.session.site(gid)["pages"] if p["path"] == path), None)


async def _confirm(pilot, app):
    assert await wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog)), stack(app)
    await press(pilot, app, "#ok")


async def test_tui_writes_pages(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), sites="accept"))
    server = await node.serve("127.0.0.1", 0)
    where = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    me = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    me.new_identity("me", "Me"); me.add_node(where)
    me.data["starter_groups"] = 99
    await me.ensure_inbox()
    gid = await me.create_group("dk.wiki", "channel", view="pages", min_pow=10)
    await me.fetch_group(gid)
    await me.put_page(gid, "index", "# Velkommen\n\nSe [om os](about).\n", "Velkommen")
    await me.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(tmp_path / "me.vault")
    async with app.run_test(size=(140, 40)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        app.select_group(gid)
        assert await wait_for(pilot, lambda: len(app.messages) == 1, 400), stack(app)

        assert app.check_action("new_post", ()) is True        # n is shown for a writer
        assert app.check_action("reply", ()) is False           # a page is not answered
        app.action_new_post()                                   # n in a site: a new page
        assert await wait_for(pilot, lambda: isinstance(app.screen, PageDialog)), stack(app)
        assert await wait_for(pilot, lambda: laid_out(app, "#body"))
        app.screen.query_one("#path", Input).value = "about"
        app.screen.query_one("#title", Input).value = "Om os"
        app.screen.query_one("#body", TextArea).text = "# Om os\n\nVi er en lille landsby.\n"
        await press(pilot, app, "#preview")                     # as readers will see it
        assert await wait_for(pilot, lambda: isinstance(app.screen, PreviewDialog)), stack(app)
        assert "Vi er en lille landsby" in str(app.screen.rendered)
        await press(pilot, app, "#cancel")
        assert await wait_for(pilot, lambda: isinstance(app.screen, PageDialog)), stack(app)
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: _page(app, gid, "about") is not None, 400), stack(app)
        first = _page(app, gid, "about")["current"].message_id

        app.current_message = _page(app, gid, "about")["current"]   # e: a new version
        app.action_edit()
        assert await wait_for(pilot, lambda: isinstance(app.screen, PageDialog)), stack(app)
        assert await wait_for(pilot, lambda: laid_out(app, "#body"))
        assert app.screen.query_one("#path", Input).disabled       # the path stays
        app.screen.query_one("#body", TextArea).text = "# Om os\n\nVi er en stor landsby.\n"
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: (p := _page(app, gid, "about")) is not None
                              and p["current"].message_id != first, 400), stack(app)
        assert "stor" in _page(app, gid, "about")["current"].body

        app.current_message = _page(app, gid, "about")["current"]   # the previous version again
        app.action_page_previous()
        await _confirm(pilot, app)
        assert await wait_for(pilot, lambda: "lille" in _page(app, gid, "about")["current"].body,
                              400), stack(app)

        app.current_message = _page(app, gid, "about")["current"]   # removed
        app.action_page_remove()
        await _confirm(pilot, app)
        assert await wait_for(pilot, lambda: _page(app, gid, "about") is None, 400), stack(app)
        assert _page(app, gid, "index") is not None

        app.current_message = None                              # a new page over an old path
        app.action_new_post()
        assert await wait_for(pilot, lambda: isinstance(app.screen, PageDialog)), stack(app)
        assert await wait_for(pilot, lambda: laid_out(app, "#body"))
        app.screen.query_one("#path", Input).value = "index"
        app.screen.query_one("#body", TextArea).text = "# Ny forside\n"
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog)), stack(app)
        await press(pilot, app, "#cancel")                      # not written over
        assert "Velkommen" in _page(app, gid, "index")["current"].body
        await pilot.press("q")
    server.close()


async def test_tui_readers_do_not_write_pages(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), sites="accept"))
    server = await node.serve("127.0.0.1", 0)
    where = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    owner = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    owner.new_identity("o", "Owner"); owner.add_node(where)
    gid = await owner.create_group("dk.wiki", "channel", view="pages", min_pow=10)
    await owner.fetch_group(gid)
    await owner.put_page(gid, "index", "# Velkommen\n", "Velkommen")
    await owner.close()
    me = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    me.new_identity("me", "Me"); me.add_node(where)
    me.data["starter_groups"] = 99
    await me.ensure_inbox()
    me.subscribe(gid)
    await me.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(tmp_path / "me.vault")
    async with app.run_test(size=(140, 40)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        app.select_group(gid)
        assert await wait_for(pilot, lambda: len(app.messages) == 1, 400), stack(app)
        assert not app.check_action("new_post", ())           # n hidden for a reader
        app.action_new_post()
        app.current_message = next(iter(app.messages.values()))
        app.action_edit()
        await pilot.pause(0.3)
        assert not isinstance(app.screen, PageDialog), stack(app)
        await pilot.press("q")
    server.close()
