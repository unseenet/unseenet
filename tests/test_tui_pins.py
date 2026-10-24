"""Pinned posts in the terminal client (UN-RFC 0033 section 7, #442), against a local node:
the owner pins with a note, the Pinned section above the threads and the mark in its
place, folding it, the pinned line above a chat, and unpinning."""

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Input, Static  # noqa: E402

from unseenet.client.session import Session  # noqa: E402
from unseenet.client.tui import ConfirmDialog, PinDialog, UnseenetApp  # noqa: E402
from unseenet.core.store import Store  # noqa: E402
from unseenet.core.vault import Vault  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

from tuihelp import laid_out, press, stack, wait_for  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


def subjects(app) -> dict[str, str]:
    table = app.query_one("#threads", DataTable)
    return {str(k.value): str(table.get_cell(k, "subject")) for k in table.rows}


async def test_tui_pin_show_fold_and_unpin(tmp_path, monkeypatch):
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{port}")
    gid = await s.create_group("dk.pins", "open", min_pow=10)
    welcome = await s.post(gid, "Velkommen", "Læs denne først\n")
    await s.post(gid, "Regler", "Vær søde\n")
    await s.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.current_group == gid, 300)
        assert await wait_for(pilot, lambda: welcome in app.messages, 400)
        assert "pins:head" not in subjects(app)                  # nothing pinned yet
        app.current_message = app.messages[welcome]

        app.action_pin()
        assert await wait_for(pilot, lambda: isinstance(app.screen, PinDialog)), stack(app)
        assert await wait_for(pilot, lambda: laid_out(app, "#value"))
        app.screen.query_one("#value", Input).value = "Til nye"
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: "pins:head" in subjects(app), 400), stack(app)
        rows = subjects(app)
        assert rows["pins:head"].endswith("Pinned (1)")
        assert rows["pin:" + welcome] == "[P] Velkommen  - Til nye"     # the section, with the note
        assert rows[welcome].startswith("[P] Velkommen")               # and in its place

        app.action_toggle_pins()                                        # folded away, remembered
        await pilot.pause()
        assert "pin:" + welcome not in subjects(app) and gid in app.session.data["pins_hidden"]
        app.action_toggle_pins()
        await pilot.pause()

        app.session.set_view(gid, "chat")                               # the pinned line above a chat
        app._render_threads()
        await pilot.pause()
        line = app.query_one("#chat-pins", Static)
        assert line.has_class("shown") and "[P] Me" in str(line.render()) \
            and "Velkommen" in str(line.render())
        app.session.set_view(gid, "threads")
        app._render_threads()
        await pilot.pause()

        app.current_message = app.messages[welcome]
        app.action_pin()                                                # pinned: this unpins
        assert await wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog)), stack(app)
        assert "stays where it is" in str(app.screen.text)
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: "pins:head" not in subjects(app), 400), stack(app)
        assert not subjects(app)[welcome].startswith("[P]")
        await pilot.press("q")
    server.close()


async def test_tui_no_pinning_for_others(tmp_path, monkeypatch):
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    owner = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    owner.new_identity("owner", "Owner")
    owner.add_node(f"127.0.0.1:{port}")
    gid = await owner.create_group("dk.ejet", "open", min_pow=10)
    await owner.post(gid, "Velkommen", "tekst\n")
    await owner.close()
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{port}")
    s.subscribe(gid)
    await s.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None
                              and gid in app.groups, 300), stack(app)
        app.select_group(gid)
        assert await wait_for(pilot, lambda: len(app.messages) == 1, 400)
        app.current_message = next(iter(app.messages.values()))
        app.action_pin()
        await pilot.pause(0.3)
        assert not isinstance(app.screen, PinDialog)                    # refused, with a note why
        await pilot.press("q")
    server.close()
