"""The terminal client's profile dialogs (UN-RFC 0022) against a local node."""

import pytest

pytest.importorskip("textual")

from textual.widgets import Button, Input, TextArea  # noqa: E402

from unseenet.client.session import Session  # noqa: E402
from unseenet.client.tui import ProfileDialog, UnseenetApp, identicon_text  # noqa: E402
from unseenet.core.store import Store  # noqa: E402
from unseenet.core.vault import Vault  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


async def wait_for(pilot, cond, tries=200):
    for _ in range(tries):
        if cond():
            return True
        await pilot.pause(0.05)
    return False


def laid_out(app, selector: str) -> bool:
    """The widget is on the current screen *and* has a place on it. A dialog pushed from a
    worker is in the DOM before its first layout; a click then lands on nothing."""
    found = app.screen.query(selector)
    return bool(found) and found.first().region.area > 0


def stack(app) -> str:
    return " > ".join(type(s).__name__ for s in app.screen_stack)


async def press(pilot, app, selector: str) -> None:
    """Press a dialog's button through its own handler. A mouse click at the button's
    place missed on slow CI runners (13 of 15 red runs), with no error at all."""
    assert await wait_for(pilot, lambda: laid_out(app, selector)), stack(app)
    app.screen.query_one(selector, Button).press()
    await pilot.pause()


async def test_tui_publish_and_show_profile(tmp_path, monkeypatch):
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF))
    s.new_identity("andreas", "Andreas")
    s.add_node(f"127.0.0.1:{port}")

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 45)) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None)
        app.action_edit_profile()
        # the warning before the first profile: wait for it rather than for a fixed time,
        # the dialog is pushed from a worker and slow runners need longer than 0.2 s
        assert await wait_for(pilot, lambda: type(app.screen).__name__ == "ConfirmDialog")
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: laid_out(app, "#about")), stack(app)
        app.screen.query_one("#about", TextArea).text = "Laver Unseenet"
        app.screen.query_one("#lang", Input).value = "da, en"
        app.screen.query_one("#links", TextArea).text = "github andlo  # code"
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: app.session.has_published_profile(), 400)
        mine = app.session.my_profile()
        assert mine["about"] == "Laver Unseenet" and mine["lang"] == ["da", "en"]
        assert mine["links"] == [{"kind": "github", "value": "andlo", "label": "code"}]

        key = app.session.identity().key_text
        p = await app.session.profile_of(key)
        app.push_screen(ProfileDialog(key, "Andreas", p, mine=True))
        assert await wait_for(pilot, lambda: bool(app.screen.query("#profile-text")))
        text = str(app.screen.query_one("#profile-text").render())
        assert "Laver Unseenet" in text and "github: andlo  (code)" in text
        await pilot.press("escape")
        await pilot.press("q")
    server.close()


def test_identicon_text_has_five_rows():
    from unseenet.core import crypto
    text = identicon_text(crypto.Identity.generate().key_text)
    assert text.plain.count("\n") == 5
