"""Feeds in the terminal client (UN-RFC 0034, #442), against a local node: following a
person, the Timeline with every note an entry and its comments under it, commenting with
r, switching a feed to threads, and starting your own feed only after the warning."""

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Input, Select, Static  # noqa: E402

from unseenet.client import session as sess  # noqa: E402
from unseenet.client.session import Session  # noqa: E402
from unseenet.client.threads import TIMELINE  # noqa: E402
from unseenet.client.tui import (ConfirmDialog, InputDialog, KeyListDialog,  # noqa: E402
                                 UnseenetApp)
from unseenet.core.store import Store  # noqa: E402
from unseenet.core.vault import Vault  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

from tuihelp import laid_out, press, stack, wait_for  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


def subjects(app) -> dict[str, str]:
    table = app.query_one("#threads", DataTable)
    return {str(k.value): str(table.get_cell(k, "subject")) for k in table.rows}


async def answer(pilot, app, kind, value=None, button="#ok"):
    assert await wait_for(pilot, lambda: isinstance(app.screen, kind), 300), stack(app)
    if value is not None:
        widget = "#value" if kind is InputDialog else "#who"
        assert await wait_for(pilot, lambda: laid_out(app, widget))
        app.screen.query_one(widget, Input if kind is InputDialog else Select).value = value
    await press(pilot, app, button)


async def test_tui_follow_timeline_comment_and_start_a_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    them = Session(Vault.open(tmp_path / "them.vault", "pw", **KDF), status=lambda *_: None)
    them.new_identity("them", "Them")
    them.add_node(f"127.0.0.1:{port}")
    feed = await them.start_personal_group("feed")
    first = await them.post(feed, "", "Første note\n", kind="chat")
    second = await them.post(feed, "", "Anden note\n", kind="chat")     # its own entry too
    their_key = them.identity().key_text
    await them.close()

    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{port}")
    home = await s.create_group("dk.hjem", "open", min_pow=10)
    await s.post(home, "Hej", "tekst\n")
    await s.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.current_group == home, 300)

        app.action_follow()
        await answer(pilot, app, InputDialog, their_key)
        assert await wait_for(pilot, lambda: feed in app.session.data["subscribed"], 300), stack(app)
        await app.session.fetch_group(feed)

        app.select_group(TIMELINE)
        assert await wait_for(pilot, lambda: {first, second} <= set(subjects(app)), 300), stack(app)
        rows = subjects(app)
        assert "Første note" in rows[first] and "feed)" in rows[first]      # which feed
        assert set(rows) == {first, second}                           # each note an entry
        title = str(app.query_one("#threads-title", Static).render())
        assert "Timeline" in title

        app.current_message = app.messages[first]
        app.action_reply()                                            # r: a comment here
        await answer(pilot, app, InputDialog, "Fin note")
        assert await wait_for(pilot, lambda: any(m.body.strip() == "Fin note"
                                                 for m, _ in app.comments.get(first, [])), 400)
        assert "(1 comment)" in subjects(app)[first]
        _, body = app.article(app.messages[first])
        assert "1 comment" in str(body) and "Fin note" in str(body)

        app.select_group(feed)                                        # the feed itself
        assert await wait_for(pilot, lambda: app.current_group == feed
                              and first in subjects(app), 300)
        app.action_toggle_view()
        assert app.session.view_of(feed) == "threads"
        app.action_toggle_view()
        app.action_toggle_view()
        assert app.session.view_of(feed) == "feed"

        app.action_start_feed()
        await answer(pilot, app, ConfirmDialog)                       # the warning first
        await answer(pilot, app, KeyListDialog, "open")
        mine = app.session.personal_group("feed")
        assert await wait_for(pilot, lambda: app.current_group == mine, 400), stack(app)
        assert app.session.group_entry(mine).get("owner")

        app.action_following()
        fp = next(iter(app.session.data["following"]["people"]))
        await answer(pilot, app, KeyListDialog, fp)
        assert await wait_for(pilot, lambda: feed not in app.session.data["subscribed"], 300)
        await pilot.press("q")
    server.close()
