"""Creating a group shown as a feed or a site in the terminal client (UN-RFC 0034 3.2,
UN-RFC 0035 section 3): a site is a channel, so choosing Site makes it one."""

import pytest

pytest.importorskip("textual")

from unseenet.client.session import Session  # noqa: E402
from unseenet.core.store import Store  # noqa: E402
from unseenet.core.vault import Vault  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

from tuihelp import app_ready, press, stack, wait_for  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


async def _app(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    from unseenet.client.tui import UnseenetApp
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), sites="accept"))
    server = await node.serve("127.0.0.1", 0)
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    s.data["starter_groups"] = 99
    await s.ensure_inbox()
    await s.close()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    return UnseenetApp(tmp_path / "me.vault"), server


@pytest.mark.parametrize("view, gtype, want", [("pages", "open", "channel"),
                                               ("feed", "channel", "channel")])
async def test_tui_create_a_site_or_a_feed(tmp_path, monkeypatch, view, gtype, want):
    from unseenet.client.tui import CreateGroupDialog
    app, server = await _app(tmp_path, monkeypatch)
    async with app.run_test(size=(140, 50)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        app.action_create_group()
        assert await wait_for(pilot, lambda: isinstance(app.screen, CreateGroupDialog), 100)
        dlg = app.screen
        dlg.query_one("#name").value = f"dk.ny{view}"
        dlg.query_one("#type").value = gtype
        await pilot.pause()
        dlg.query_one("#view").value = view
        assert await wait_for(pilot, lambda: dlg.query_one("#type").value == want, 50)
        assert await wait_for(pilot, lambda: str(dlg.query_one("#view-help").render()), 50)
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: (app.current_group or "").startswith(f"dk.ny{view}"),
                              400), [n.message for n in app._notifications]
        data = app.session.manifest_data(app.current_group)
        assert data["view"] == view and data["type"] == want
        if view == "feed":
            assert data["comments"] == "open"
        await pilot.press("q")
    server.close()
