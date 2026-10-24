"""Withdrawing a chat line in the terminal client: in a chat, where no line is
selected, D withdraws your last line (as e edits it), after asking."""

import pytest

pytest.importorskip("textual")

from unseenet.client.session import Session  # noqa: E402
from unseenet.core.store import Store  # noqa: E402
from unseenet.core.vault import Vault  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

from tuihelp import app_ready, press, stack, wait_for  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


async def test_tui_withdraws_your_last_chat_line(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    from unseenet.client.tui import ConfirmDialog, UnseenetApp
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(addr)
    s.data["starter_groups"] = 99
    await s.ensure_inbox()
    gid = await s.create_group("dk.snak", "open", view="chat", min_pow=10)
    first = await s.send_chat(gid, "Hej")
    last = await s.send_chat(gid, "Ups, forkert gruppe")
    await s.close()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(tmp_path / "me.vault")
    async with app.run_test(size=(140, 40)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        assert await wait_for(pilot, lambda: gid in app.groups, 300)
        app.select_group(gid)
        assert await wait_for(pilot, lambda: app.current_group == gid
                              and len(app.session.cache.get(gid, {})) == 2, 300)
        assert app._withdrawable(gid).message_id == last
        assert app.check_action("withdraw", ())
        app.action_withdraw()
        assert await wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog), 100)
        assert "chat line" in str(app.screen.query_one(".title").render())
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: last in app.session.group_entry(gid).get("cancels", {}), 300)
        assert first not in app.session.group_entry(gid).get("cancels", {})
        await pilot.press("q")
    server.close()
