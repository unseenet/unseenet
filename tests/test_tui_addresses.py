"""unseenet: addresses in the terminal client (UN-RFC 0031 section 3.4.1, #357), against a
local node: a post's address shown to give away, Join (j) opening a post in a group you
do not follow yet, the older unseenet:join form, and a person's address."""

import pytest

pytest.importorskip("textual")

from textual.widgets import Input  # noqa: E402

from unseenet.client.session import Session  # noqa: E402
from unseenet.client.tui import InfoDialog, InputDialog, ProfileDialog, UnseenetApp  # noqa: E402
from unseenet.core import addresses as addr  # noqa: E402
from unseenet.core import crypto  # noqa: E402
from unseenet.core.store import Store  # noqa: E402
from unseenet.core.vault import Vault  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

from tuihelp import laid_out, press, stack, wait_for  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


async def join(pilot, app, text: str) -> None:
    app.action_join()
    assert await wait_for(pilot, lambda: isinstance(app.screen, InputDialog)), stack(app)
    assert await wait_for(pilot, lambda: laid_out(app, "#value"))
    app.screen.query_one("#value", Input).value = text
    await press(pilot, app, "#ok")


async def test_tui_addresses(tmp_path, monkeypatch):
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    other = Session(Vault.open(tmp_path / "other.vault", "pw", **KDF), status=lambda *_: None)
    other.new_identity("other", "Other")
    other.add_node(f"127.0.0.1:{port}")
    theirs = await other.create_group("dk.andet", "open", min_pow=10)
    there = await other.post(theirs, "Derovre", "Et indlæg et andet sted\n")
    await other.close()

    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{port}")
    mine = await s.create_group("dk.adr", "open", min_pow=10)
    welcome = await s.post(mine, "Velkommen", "Læs denne først\n")
    me = s.identity().key_text
    await s.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.current_group == mine, 300)
        assert await wait_for(pilot, lambda: welcome in app.messages, 400)

        app.current_message = app.messages[welcome]                  # no n=: not an onion node
        app.action_post_address()
        assert await wait_for(pilot, lambda: isinstance(app.screen, InfoDialog)), stack(app)
        assert await wait_for(pilot, lambda: laid_out(app, "#value"))
        assert app.screen.query_one("#value", Input).value == addr.post_address(mine, welcome)
        assert app.screen.query_one("#web", Input).value == addr.web_address(
            addr.post_address(mine, welcome))                         # and its web form
        app.pop_screen()

        await join(pilot, app, addr.web_address(addr.group_address(theirs), "example.org"))
        assert await wait_for(pilot, lambda: app.current_group == theirs, 300), stack(app)

        await join(pilot, app, addr.post_address(theirs, there))      # not followed yet: joined
        assert await wait_for(pilot, lambda: app.current_message is not None
                              and app.current_message.message_id == there, 400), stack(app)
        assert theirs in app.session.data["subscribed"]

        await join(pilot, app, f"unseenet:join?g={mine}")              # the older form
        assert await wait_for(pilot, lambda: app.current_group == mine, 300), stack(app)

        await join(pilot, app, "dk.adr@nope")                         # not an address
        assert await wait_for(pilot, lambda: not isinstance(app.screen, InputDialog))
        assert app.current_group == mine

        fp = crypto.fingerprint(crypto.key_from_text(me))
        await join(pilot, app, addr.identity_address(fp))             # a person: the profile
        assert await wait_for(pilot, lambda: isinstance(app.screen, ProfileDialog), 300), stack(app)
        await pilot.press("q")
    server.close()
