"""Reactions in the terminal client (UN-RFC 0048 section 7, #510), against a local node:
l opens the group's set, a number reacts, the count shows in the list and under the
post, the same number again takes it back, and no l where the group takes none."""

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable  # noqa: E402

from unseenet.client.session import Session  # noqa: E402
from unseenet.client.tui import ReactDialog, UnseenetApp, reactions_text  # noqa: E402
from unseenet.core import reactions as rx  # noqa: E402
from unseenet.core.store import Store  # noqa: E402
from unseenet.core.vault import Vault  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

from tuihelp import app_ready, stack, wait_for  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


def subjects(app) -> dict[str, str]:
    table = app.query_one("#threads", DataTable)
    return {str(k.value): str(table.get_cell(k, "subject")) for k in table.rows}


def test_reactions_text():
    c = rx.count([("<1@x>", "A", 1, "<t@x>", "👍"), ("<2@x>", "B", 1, "<t@x>", "👍"),
                  ("<3@x>", "C", 1, "<t@x>", "❤")])["<t@x>"]
    assert reactions_text(c, "❤️") == "👍 2  [❤️ 1]"
    assert reactions_text(None, None) == ""


async def test_tui_react_and_take_back(tmp_path, monkeypatch):
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{port}")
    gid = await s.create_group("dk.noter", "open", min_pow=10, view="feed")
    mine = await s.post(gid, "Mit", "Mit eget opslag\n")
    o = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    o.new_identity("o", "O")
    o.add_node(f"127.0.0.1:{port}")
    await o.fetch_group(gid)
    entry = await o.post(gid, "Hej", "Første opslag\n")
    await o.close()
    other = await s.create_group("dk.debat", "open", min_pow=10)
    await s.post(other, "Emne", "tekst\n")
    await s.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        app.select_group(gid)
        assert await wait_for(pilot, lambda: app.current_group == gid and entry in app.messages,
                              400)
        assert await wait_for(pilot, lambda: mine in app.messages, 400)
        app.current_message = app.messages[mine]                       # your own: no l (#524)
        assert not app.check_action("react", ())
        app.current_message = app.messages[entry]
        assert app.check_action("react", ()) is True

        app.action_react()
        assert await wait_for(pilot, lambda: isinstance(app.screen, ReactDialog)), \
            (stack(app), [n.message for n in app._notifications])
        assert "public and signed" in str(app.screen.query("Label").last().render())
        await pilot.press("1")                                          # 👍
        assert await wait_for(pilot, lambda: "👍 1" in subjects(app).get(entry, ""), 400), \
            subjects(app)
        assert "[👍 1]" in subjects(app)[entry]                          # yours, marked
        _, body = app.article(app.messages[entry])
        assert "👍 1" in str(body) and "l reacts" in str(body)

        app.current_message = app.messages[entry]
        app.action_react()
        assert await wait_for(pilot, lambda: isinstance(app.screen, ReactDialog)), stack(app)
        await pilot.press("1")                                          # again: taken back
        assert await wait_for(pilot, lambda: "👍" not in subjects(app).get(entry, "x"), 400), \
            subjects(app)

        app.select_group(other)                                         # a discussion: none
        assert await wait_for(pilot, lambda: app.current_group == other and app.messages, 400)
        app.current_message = next(iter(app.messages.values()))
        assert app.check_action("react", ()) is False
    server.close()
