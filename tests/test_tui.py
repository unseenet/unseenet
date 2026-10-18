"""Headless TUI test against a local node (no Tor)."""

import re
import os

import pytest

pytest.importorskip("textual")

from unseenet.client.session import Session  # noqa: E402
from unseenet.client.tui import UnseenetApp  # noqa: E402
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


async def test_tui_create_group_and_post(tmp_path, monkeypatch):
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
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None)
        app.action_create_group()          # only in the command palette, no key
        await pilot.pause(0.2)
        await pilot.click("#name")
        await pilot.press(*"dk.test")
        await pilot.click("#ok")
        assert await wait_for(pilot, lambda: app.current_group and app.current_group.startswith("dk.test@"))

        await pilot.press("n")
        await pilot.pause(0.2)
        await pilot.press(*"Hej")
        await pilot.click("#body")
        await pilot.press(*"Fra TUI'en")
        await pilot.press("ctrl+s")
        gid = app.current_group
        assert await wait_for(pilot, lambda: any(m.subject == "Hej" for m in app.session.cache.get(gid, {}).values()), 400)
        msg = next(m for m in app.session.cache[gid].values() if m.subject == "Hej")
        assert "Fra TUI" in msg.body
        await pilot.press("q")
    server.close()


async def test_tui_shows_brackets_literally(tmp_path, monkeypatch):
    """Posts are user content: '[b]' or '[/x]' must never be parsed as markup."""
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("x", "Name [with] [/brackets]")
    s.add_node(f"127.0.0.1:{port}")
    gid = await s.create_group("dk.test", "open", title="[x] title", min_pow=10)
    await s.post(gid, "Subject [b]", "Body [/b] [link=x] [/]\n")
    s.data["read"] = {}
    s.save()
    await s.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: len(app.messages) == 1)
        app.query_one("#threads").focus()
        await pilot.press("down", "up")
        await pilot.pause(0.3)
        await pilot.press("g")
        await pilot.pause(0.5)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert app.return_code is None
        await pilot.press("q")
    server.close()


def test_vault_saves_are_private_and_fast(tmp_path):
    import os
    import time
    v = Vault.open(tmp_path / "v.vault", "pw", **KDF)
    v.data["x"] = 1
    v.save()
    if os.name != "nt":                    # Windows has no Unix file modes
        assert oct(os.stat(tmp_path / "v.vault").st_mode & 0o777) == "0o600"
    t = time.time()
    for _ in range(20):
        v.save()
    assert time.time() - t < 5.0          # no key derivation per save (loose: CI runners stall)
    assert Vault.open(tmp_path / "v.vault", "pw", **KDF).data["x"] == 1


async def test_tui_inbox_and_operator_contact(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    from unseenet.core import crypto
    from unseenet.core.groups import make_manifest
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    operator = crypto.Identity.generate()
    contact = make_manifest(operator, "operator", "inbox", local=True, pow_bits=10)
    node = Node(Store(), NodeConfig(name="testnode", min_pow=8, forward_delay=(0, 0),
                                    operator={"key": operator.key_text, "contact": contact.group}))
    node.accept(contact.to_bytes())
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{port}")
    s.save()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        # the personal inbox is created and listed
        assert await wait_for(pilot, lambda: app._inbox_ready, 300)
        # the group list is filled right after the inbox is made
        assert await wait_for(pilot, lambda: app.session.my_inbox in app.groups, 300)
        from unseenet.client.tui import NodeInfoDialog, NodesDialog
        await pilot.press("o")
        assert await wait_for(pilot, lambda: isinstance(app.screen, NodesDialog))
        await pilot.click("#info")                    # details of the selected node
        assert await wait_for(pilot, lambda: isinstance(app.screen, NodeInfoDialog))
        await pilot.click("#ok")                      # "Write to operator"
        await pilot.pause(0.4)
        await pilot.press(*"Hej")
        await pilot.click("#body")
        await pilot.press(*"Tak for noden")
        await pilot.press("ctrl+s")
        assert await wait_for(pilot, lambda: len(node.store.numbers(contact.group)) == 2, 400)
        raw = node.store.by_number(contact.group, 2)[1]
        assert b"Tak for noden" not in raw
        await pilot.press("q")
    server.close()


async def test_tui_signature_added_and_not_quoted(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{port}")
    s.set_signature("Me ({fp})")
    gid = await s.create_group("dk.test", "open", min_pow=10)
    await s.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.current_group == gid, 300)
        await pilot.press("n")
        await pilot.pause(0.3)
        await pilot.press(*"Emne")
        await pilot.click("#body")
        await pilot.press("ctrl+home")
        await pilot.press(*"Teksten")
        await pilot.press("ctrl+s")
        assert await wait_for(pilot, lambda: len(app.messages) == 1, 400)
        msg = next(iter(app.messages.values()))
        fp = app.session.identity().fingerprint[:4]
        assert msg.body.startswith("Teksten") and msg.body.endswith(f"-- \nMe ({fp})\n")
        app.query_one("#threads").focus()
        await pilot.press("r")
        await pilot.pause(0.4)
        text = app.screen.query_one("#body").text
        assert "> Teksten" in text and f"> Me ({fp})" not in text   # signature not quoted
        assert text.endswith(f"-- \nMe ({fp})")                      # own signature added
        await pilot.press("escape")
        await pilot.press("q")
    server.close()


async def test_tui_create_group_rejects_bad_name_and_keeps_dialog(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    from unseenet.client.tui import CreateGroupDialog
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{port}")
    s.save()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app._inbox_ready, 300)
        app.action_create_group()          # only in the command palette, no key
        await pilot.pause(0.3)
        await pilot.press(*"andlo,test")
        await pilot.click("#ok")
        await pilot.pause(0.3)
        assert isinstance(app.screen, CreateGroupDialog)          # still open
        assert app.screen.query_one("#name").value == "andlo,test"  # nothing lost
        assert "','" in str(app.screen.query_one("#name-help").render())
        name = app.screen.query_one("#name")
        name.value = "andlo.test"
        await pilot.pause(0.3)          # the help text changes, and the buttons move
        await pilot.click("#ok")
        assert await wait_for(pilot, lambda: any(g.startswith("andlo.test@") for g in app.groups), 300)
        await pilot.press("q")
    server.close()


async def test_tui_contact_conversation(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    a = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    a.new_identity("andreas", "Andreas"); a.add_node(addr)
    b = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    b.new_identity("sonia", "Sonia"); b.add_node(addr)
    await a.ensure_inbox(); await b.ensure_inbox()
    await b.send_private(a.my_inbox, "", "Kan du hente mig?\n", kind="chat")   # a chat (UN-RFC 0028)
    a.save(); await a.close(); await b.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(tmp_path / "a.vault")
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: len(app.messages) == 1, 300)
        app.query_one("#threads").focus()
        await pilot.press("a")                      # add the sender as a contact
        await pilot.pause(0.3)
        await pilot.click("#ok")                    # key pre-filled
        await pilot.pause(0.3)
        name = app.screen.query_one("#value")
        assert name.value == "Sonia"                # name suggested
        name.value = "Sonia (datter)"
        await pilot.click("#ok")
        assert await wait_for(pilot, lambda: bool(app.session.contacts()), 100)
        key = b.identity().key_text
        app.select_group("contact:" + key)
        assert await wait_for(pilot, lambda: app.current_group == "contact:" + key
                              and app.focused is not None and app.focused.id == "chat-input", 100)
        assert app.view_of(app.current_group) == "chat"          # conversations open as a chat
        assert app.focused.id == "chat-input"
        await pilot.press(*"Jeg kommer", "enter")
        assert await wait_for(pilot, lambda: len(app.messages) == 2, 400)
        rows = [app._who(m) for m in app.messages.values()]
        assert rows[0].startswith("Sonia (datter) √") and rows[1] == "You"
        lines = [str(line.text) for line in app.query_one("#chat-log").lines]
        assert any("Sonia (datter)" in ln and "Kan du hente mig?" in ln for ln in lines)
        assert any("You: Jeg kommer" in ln for ln in lines)
        await pilot.press("q")
    server.close()


async def _app_with_groups(tmp_path, monkeypatch, names):
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    s.data["starter_groups"] = True    # the project's groups are not on this test node
    await s.ensure_inbox()
    for n in names:
        await s.create_group(n, "open", min_pow=10)
    await s.close()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    return UnseenetApp(vault_path), server


async def test_tui_tree_cursor_survives_refresh(tmp_path, monkeypatch):
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak", "dk.teknik", "alt.test"])
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: len(app.groups) == 4, 300)
        await pilot.pause(0.5)
        tree = app.query_one("#groups")
        tree.focus()
        target = next(n for n in tree.root.children if n.children)   # the dk.* folder
        leaf = target.children[-1]
        tree.move_cursor(leaf)
        await pilot.pause(0.2)
        before = tree.cursor_node.data
        app.refresh_groups()
        await pilot.pause(1.5)
        assert tree.cursor_node is not None and tree.cursor_node.data == before
        await pilot.press("q")
    server.close()


async def test_tui_background_error_is_reported_not_fatal(tmp_path, monkeypatch):
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app._inbox_ready, 300)

        async def boom(gid):
            raise RuntimeError("simulated failure")
        app.session.fetch_group = boom
        app.select_group(next(iter(app.groups)))
        await pilot.pause(0.8)
        assert app.return_code is None and app.is_running            # still alive
        log = tmp_path / "unseenet-tui-errors.log"
        assert "simulated failure" in log.read_text()
        await pilot.press("q")
    server.close()


async def test_tui_chat_group_and_rules_on_first_visit(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    from unseenet.client.tui import GroupInfoDialog
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    owner = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    owner.new_identity("o", "Owner"); owner.add_node(addr)
    gid = await owner.create_group("chat.venner", "open", view="chat", low_latency=True,
                                   rules="Kun hyggesnak.", min_pow=9)
    await owner.post(gid, "hej", "Hej alle!\n")
    await owner.close()

    me = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    me.new_identity("me", "Me"); me.add_node(addr); me.subscribe(gid); me.save()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(tmp_path / "me.vault")
    async with app.run_test(size=(140, 40)) as pilot:
        # unlocking runs in the background; selecting before it is done is a race
        assert await wait_for(pilot, lambda: app.session is not None and gid in app.groups, 300)
        app.select_group(gid)
        # the rules are shown the first time
        assert await wait_for(pilot, lambda: isinstance(app.screen, GroupInfoDialog), 300)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert not app.session.rules_unseen(gid)
        assert app.view_of(gid) == "chat"                       # the owner's hint
        assert "fast delivery" in str(app.query_one("#threads-title").render())
        app.query_one("#chat-input").focus()
        await pilot.press(*"Hej med dig", "enter")
        assert await wait_for(pilot, lambda: len(app.messages) == 2, 400)
        lines = [str(line.text) for line in app.query_one("#chat-log").lines]
        assert any(re.search(r"Owner~[a-z2-7]{4}: Hej alle!", ln) for ln in lines)   # Name~fp (UN-RFC 0019)
        assert any("You: Hej med dig" in ln for ln in lines)
        # v switches to threads and back
        app.query_one("#groups").focus()
        await pilot.press("v")
        await pilot.pause(0.2)
        assert app.view_of(gid) == "threads" and app.query_one("#threads").display
        await pilot.press("q")
    server.close()


async def test_tui_chat_updates_by_push(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    friend = Session(Vault.open(tmp_path / "f.vault", "pw", **KDF), status=lambda *_: None)
    friend.new_identity("f", "Friend"); friend.add_node(addr)
    gid = await friend.create_group("chat.venner", "open", view="chat", low_latency=True, min_pow=9)

    me = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    me.new_identity("me", "Me"); me.add_node(addr); me.subscribe(gid); me.save()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(tmp_path / "me.vault")
    async with app.run_test(size=(140, 40)) as pilot:
        app.select_group(gid)
        assert await wait_for(pilot, lambda: app._inbox_ready and app.current_group == gid, 300)
        await pilot.pause(0.5)
        await friend.post(gid, "hej", "Er du der?\n")          # no refresh: push must bring it
        assert await wait_for(pilot, lambda: any(
            re.search(r"Friend~[a-z2-7]{4}: Er du der\?", str(ln.text)) for ln in app.query_one("#chat-log").lines), 100)
        await pilot.press("q")
    await friend.close()
    server.close()


async def test_tui_about_screen(tmp_path, monkeypatch):
    from unseenet.client.tui import AboutDialog, DOCS_URL, REPO_URL
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF))
    s.new_identity("andreas", "Andreas")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    opened = []
    app = UnseenetApp(vault_path)
    monkeypatch.setattr(app, "open_url", lambda url, **kw: opened.append(url))
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None)
        await pilot.press("f1")
        assert await wait_for(pilot, lambda: isinstance(app.screen, AboutDialog))
        await pilot.click("#repo")
        await pilot.click("#docs")
        await pilot.pause(0.1)
        assert opened == [REPO_URL, DOCS_URL]
        await pilot.press("escape")
        assert await wait_for(pilot, lambda: not isinstance(app.screen, AboutDialog))
    server.close()


async def test_tui_nodes_add_default_remove(tmp_path, monkeypatch):
    """Two nodes in the TUI: groups from both, the node manager, one key."""
    import unseenet.client.session as sess
    from unseenet.client.tui import BrowseDialog, NodesDialog
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    servers, addrs = [], []
    for _ in range(2):
        node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
        srv = await node.serve("127.0.0.1", 0)
        servers.append(srv)
        addrs.append(f"127.0.0.1:{srv.sockets[0].getsockname()[1]}")
    other = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    other.new_identity("o", "Other"); other.add_node(addrs[1])
    gid = await other.create_group("dk.andet", "open")
    await other.post(gid, "hej", "Fra den anden node\n")
    await other.close()

    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me"); s.add_node(addrs[0]); s.save()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app._inbox_ready, 300)
        await pilot.press("o")
        assert await wait_for(pilot, lambda: isinstance(app.screen, NodesDialog))
        await pilot.click("#add")
        from textual.widgets import Select
        from unseenet.client.tui import OTHER_NODE, AddNodeDialog
        assert await wait_for(pilot, lambda: isinstance(app.screen, AddNodeDialog))
        app.screen.query_one("#known", Select).value = OTHER_NODE     # not a known node
        await pilot.pause(0.2)
        app.screen.query_one("#node").focus()
        await pilot.press(*addrs[1], "enter")
        assert await wait_for(pilot, lambda: addrs[1] in app.session.nodes)
        assert await wait_for(pilot, lambda: isinstance(app.screen, NodesDialog))
        await pilot.press("escape")
        # the other node's group can be browsed and subscribed, and is read from there
        await pilot.press("g")
        assert await wait_for(pilot, lambda: isinstance(app.screen, BrowseDialog), 300)
        tree = app.screen.query_one("#browse-tree")
        leaf = next(n for n in _all_nodes(tree.root) if getattr(n.data, "group_id", None) == gid)
        tree.select_node(leaf)
        await pilot.pause(0.2)
        assert app.session.node_for(gid) == addrs[1]
        await pilot.press("escape")
        assert await wait_for(pilot, lambda: any(
            m.body == "Fra den anden node\n" for m in app.session.cache.get(gid, {}).values()), 300)
        # make the second node the default
        await pilot.press("o")
        assert await wait_for(pilot, lambda: isinstance(app.screen, NodesDialog))
        await pilot.press("down")
        await pilot.click("#default")
        assert await wait_for(pilot, lambda: app.session.node == addrs[1])
        await pilot.press("escape")
        await pilot.press("q")
    for srv in servers:
        srv.close()


def _all_nodes(node):
    for child in node.children:
        yield child
        yield from _all_nodes(child)


async def test_tui_bridges_dialog(tmp_path, monkeypatch):
    from textual.widgets import Select, TextArea
    from unseenet.client.tui import BridgesDialog
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF))
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app._inbox_ready, 300)
        app.action_bridges()
        assert await wait_for(pilot, lambda: isinstance(app.screen, BridgesDialog))
        await pilot.pause(0.2)
        assert not app.screen.query_one("#lines").display          # only for own bridges
        app.screen.query_one("#mode", Select).value = "custom"
        await pilot.pause(0.2)
        assert app.screen.query_one("#lines").display
        app.screen.query_one("#lines", TextArea).text = "obfs4 192.0.2.1:443 ABCD cert=x iat-mode=0\n"
        await pilot.click("#ok")
        assert await wait_for(pilot, lambda: app.session.bridge_setting()["mode"] == "custom")
        assert app.session.bridge_setting()["custom"] == ["obfs4 192.0.2.1:443 ABCD cert=x iat-mode=0"]
        await pilot.press("q")
    server.close()


async def test_tui_first_start_offers_known_nodes(tmp_path, monkeypatch):
    from textual.widgets import Input, Select
    import unseenet.client.session as sess
    from unseenet.client.tui import SetupDialog
    from unseenet.known_nodes import KNOWN_NODES

    async def offline(self, address=None, quiet=False):     # no Tor in tests
        raise ConnectionError("offline in tests")
    monkeypatch.setattr(sess.Session, "_connect", offline)
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(tmp_path / "new.vault")
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: isinstance(app.screen, SetupDialog), 300)
        await pilot.pause(0.2)
        assert app.screen.query_one("#known", Select).value == KNOWN_NODES[0].address
        assert not app.screen.query_one("#node").display          # only for another node
        app.screen.query_one("#display", Input).value = "Andreas"
        await pilot.click("#ok")
        assert await wait_for(pilot, lambda: app.session.nodes == [n.address for n in KNOWN_NODES])
        await pilot.press("q")


async def test_tui_browse_and_nodes_fit_small_terminal(tmp_path, monkeypatch):
    """Lists fill the dialog and the buttons stay visible in a small window;
    the highlighted group and node are described below the list."""
    from unseenet.client.tui import BrowseDialog, NodesDialog
    names = [f"dk.gruppe{i}" for i in range(30)]
    app, server = await _app_with_groups(tmp_path, monkeypatch, names)
    async with app.run_test(size=(80, 20)) as pilot:
        assert await wait_for(pilot, lambda: len(app.groups) == 31, 300)
        await pilot.press("g")
        assert await wait_for(pilot, lambda: isinstance(app.screen, BrowseDialog), 100)
        dialog = app.screen
        await pilot.pause(0.3)
        ok = dialog.query_one("#cancel")
        assert str(ok.label) == "OK"
        assert ok.region.bottom <= 20 and ok.region.height > 0
        tree = dialog.query_one("#browse-tree")
        tree.move_cursor(tree.root.children[0].children[3])
        assert await wait_for(pilot, lambda: isinstance(
            dialog.peeked.get(tree.cursor_node.data.group_id), tuple), 100)
        text = str(dialog.query_one("#group-details").render())
        assert "dk.gruppe" in text and "open" in text and "Owner:  you" in text
        app.save_screenshot(str(tmp_path / "browse.svg"))
        await pilot.click("#cancel")             # OK closed it twice: ScreenStackError
        await pilot.pause(0.3)
        assert not isinstance(app.screen, BrowseDialog) and app.is_running
        app.action_node_info()
        assert await wait_for(pilot, lambda: isinstance(app.screen, NodesDialog), 200)
        await pilot.pause(0.3)
        ok = app.screen.query_one("#cancel")
        assert ok.region.bottom <= 20 and ok.region.height > 0
        assert "Address:" in str(app.screen.query_one("#node-details").render())
        app.save_screenshot(str(tmp_path / "nodes.svg"))
        await pilot.click("#cancel")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, NodesDialog) and app.is_running
        await pilot.pause(0.2)
        await pilot.press("q")
    server.close()


async def test_tui_browse_does_not_subscribe_to_someone_elses_inbox(tmp_path, monkeypatch):
    """A node operator's contact inbox (operator@...) is listed, but only its owner
    can read it: Enter explains that instead of subscribing."""
    from unseenet.client.tui import BrowseDialog
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    op = Session(Vault.open(tmp_path / "op.vault", "pw", **KDF), status=lambda *_: None)
    op.new_identity("op", "Operator"); op.add_node(addr)
    gid = await op.create_group("operator", "inbox", local=True, min_pow=10)
    await op.close()
    async with app.run_test(size=(120, 40)) as pilot:
        assert await wait_for(pilot, lambda: app._inbox_ready, 300)
        await pilot.press("g")
        assert await wait_for(pilot, lambda: isinstance(app.screen, BrowseDialog), 100)
        dialog = app.screen
        tree = dialog.query_one("#browse-tree")
        leaf = next(n for n in tree.root.children if n.data is not None
                    and getattr(n.data, "group_id", "") == gid)
        tree.move_cursor(leaf)
        assert await wait_for(pilot, lambda: isinstance(dialog.peeked.get(gid), tuple), 100)
        assert "only its owner can read it" in str(dialog.query_one("#group-details").render())
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert gid not in app.session.data["subscribed"]
        assert any("is an inbox" in n.message for n in app._notifications)
        await pilot.click("#cancel")
        await pilot.pause(0.3)
        assert app.is_running and not isinstance(app.screen, BrowseDialog)
        await pilot.press("q")
    server.close()


def test_group_icons():
    from unseenet.client.tui import ICON_LEGEND, group_icons
    assert group_icons("open", {"view": "threads"}) == "  ≡"
    assert group_icons("open", {"view": "chat"}) == "  »"
    assert group_icons("closed", {"view": "chat"}) == "∩ »"
    assert group_icons("channel", {}) == "► ≡"
    assert group_icons("moderated", {}) == "√ ≡"
    assert group_icons("open", {"local": True}) == "⌂ ≡"
    assert group_icons("inbox", {}) == "@  "
    assert group_icons(None, {}) == "·  "
    assert group_icons(None, {"type": "closed"}) == "∩ ≡"          # from the manifest
    assert group_icons("channel", {"view": "data"}) == "► ¤"       # UN-RFC 0008 3.1.1
    assert group_icons("open", {"view": "something new"}) == "  ≡"  # unknown: threads
    # WGL4 only: the classic Windows console shows every one of them
    for ch in "≡»¤√►∩@⌂·" + ICON_LEGEND:
        assert ord(ch) < 0x80 or ch in "≡»¤√►∩⌂·", ch


async def test_tui_browse_hides_data_groups(tmp_path, monkeypatch):
    """Data groups the client knows of are not offered when browsing; one it does not
    know yet is marked as soon as its manifest is read (UN-RFC 0008 3.1.1). The
    owner's settings dialog does not break on views."""
    import unseenet.known_nodes as kn
    from unseenet.client.tui import BrowseDialog, EditGroupDialog
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    other = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    other.new_identity("o", "Other"); other.add_node(addr)
    known = await other.create_group("dk.nodelist", "channel", view="data", min_pow=10)
    unknown = await other.create_group("dk.list", "channel", view="data", min_pow=10)
    talk = await other.create_group("dk.talk", "open", min_pow=10)
    assert other.is_data_group(unknown) and not other.is_data_group(talk)
    await other.close()
    monkeypatch.setattr(kn, "DATA_GROUPS", kn.DATA_GROUPS | {known})   # like the project's
    async with app.run_test(size=(120, 40)) as pilot:
        assert await wait_for(pilot, lambda: app._inbox_ready, 300)
        await pilot.press("g")
        assert await wait_for(pilot, lambda: isinstance(app.screen, BrowseDialog), 100)
        dialog = app.screen
        listed = {g.group_id for g in dialog.groups}
        assert talk in listed and unknown in listed and known not in listed
        tree = dialog.query_one("#browse-tree")
        leaf = next(n for parent in [tree.root, *tree.root.children] for n in parent.children
                    if getattr(n.data, "group_id", "") == unknown)
        tree.move_cursor(leaf)
        assert await wait_for(pilot, lambda: isinstance(dialog.peeked.get(unknown), tuple), 100)
        await pilot.pause(0.2)
        assert "Data for programs" in str(dialog.query_one("#group-details").render())
        assert "¤" in str(dialog._label(leaf.data))
        await pilot.click("#cancel")
        await pilot.pause(0.2)
        edit = EditGroupDialog({"name": "dk.list", "view": "data"})
        app.push_screen(edit)
        await pilot.pause(0.2)
        assert edit.query_one("#view").value == "data"
        app.pop_screen()
        edit = EditGroupDialog({"name": "x", "view": "from-the-future"})
        app.push_screen(edit)
        await pilot.pause(0.2)
        assert edit.query_one("#view").value == "threads"
        app.pop_screen()
        await pilot.press("q")
    server.close()


def test_project_data_groups_are_known_before_their_manifests(tmp_path):
    import unseenet.known_nodes as kn
    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    for gid in ("unseenet.nodes@ph5fc5hop5232qsz", "unseenet.names@ph5fc5hop5232qsz",
                "unseenet.hierarchies@ph5fc5hop5232qsz", "unseenet.checkgroups@ph5fc5hop5232qsz"):
        assert gid in kn.DATA_GROUPS and s.is_data_group(gid)
    assert not s.is_data_group(kn.ANNOUNCE_GROUP)


async def test_tui_group_list_shows_icons(tmp_path, monkeypatch):
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    async with app.run_test(size=(120, 30)) as pilot:
        assert await wait_for(pilot, lambda: len(app.groups) == 2, 300)
        await pilot.pause(0.5)
        labels = [str(n.label) for n in app.query_one("#groups").root.children]
        assert any(label.startswith("@   Letters") for label in labels)
        assert any("  ≡ dk.snak" in label for label in labels)
        app.save_screenshot(str(tmp_path / "icons.svg"))
        await pilot.press("q")
    server.close()


async def test_tui_sent_private_messages_and_full_screen(tmp_path, monkeypatch):
    """Private letters you sent show in Letters (also to keys that are
    not contacts); Enter reads a message on the whole screen, n/p move, Esc goes back."""
    from unseenet.client.tui import ReadScreen
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    other = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    other.new_identity("o", "Other"); other.add_node(addr)
    await other.ensure_inbox()
    me = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    await me.send_private(other.my_inbox, "Hej du", "Første\n", owner_key=other.identity().public_key)
    await me.send_private(other.my_inbox, "Igen", "Anden\n", owner_key=other.identity().public_key)
    assert [m.subject for m in me.private_messages()] == ["Hej du", "Igen"]
    assert all(m.to_key == other.identity().key_text for m in me.sent_messages())
    await me.close(); await other.close()

    async with app.run_test(size=(120, 36)) as pilot:
        assert await wait_for(pilot, lambda: app._inbox_ready, 300)
        app.select_group(app.session.my_inbox)
        assert await wait_for(pilot, lambda: len(app.messages) == 2, 100)
        await pilot.pause(0.3)
        table = app.query_one("#threads")
        whos = [str(table.get_row_at(i)[2]) for i in range(table.row_count)]
        assert all(w.startswith("You → ") for w in whos), whos
        table.focus()
        table.move_cursor(row=0)
        await pilot.pause(0.2)
        first = app.current_message
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: isinstance(app.screen, ReadScreen), 50)
        assert first.subject in str(app.screen.query_one("#read-head").render())
        await pilot.press("n")
        await pilot.pause(0.3)
        assert app.screen.msg is not first and app.current_message is app.screen.msg
        await pilot.press("p")
        await pilot.pause(0.3)
        assert app.screen.msg is first
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, ReadScreen) and app.is_running
        await pilot.press("q")
    server.close()


async def test_tui_browse_space_and_click_on_box(tmp_path, monkeypatch):
    """Space subscribes; a click on the line only shows the group, a click on
    [ ] subscribes."""
    from unseenet.client.tui import BrowseDialog
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    other = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    other.new_identity("o", "Other"); other.add_node(addr)
    gid = await other.create_group("alt.test", "open", min_pow=10)
    await other.close()
    async with app.run_test(size=(120, 36)) as pilot:
        assert await wait_for(pilot, lambda: app._inbox_ready, 300)
        await pilot.press("g")
        assert await wait_for(pilot, lambda: isinstance(app.screen, BrowseDialog), 100)
        dialog = app.screen
        tree = dialog.query_one("#browse-tree")
        leaf = next(n for n in tree.root.children if getattr(n.data, "group_id", "") == gid)
        tree.move_cursor(leaf)
        await pilot.pause(0.2)
        subscribed = lambda: gid in app.session.data["subscribed"]   # noqa: E731
        await pilot.press("space")
        await pilot.pause(0.2)
        assert subscribed()
        await pilot.press("space")
        await pilot.pause(0.2)
        assert not subscribed()

        region = tree._get_label_region(leaf.line)
        y = leaf.line - tree.scroll_offset.y + tree.gutter.top
        x0 = region.x - tree.scroll_offset.x + tree.gutter.left
        await pilot.click(tree, offset=(x0 + 12, y))           # on the name
        await pilot.pause(0.2)
        assert not subscribed() and tree.cursor_node is leaf
        await pilot.click(tree, offset=(x0 + 1, y))            # on the box
        await pilot.pause(0.2)
        assert subscribed()
        await pilot.press("escape")
        await pilot.pause(0.2)
        await pilot.press("q")
    server.close()


async def test_tui_shortcuts_follow_where_you_are(tmp_path, monkeypatch):
    """Invite only in closed groups you own, no new post in your inbox, and in a
    chat the letters are shortcuts again after Esc (Enter writes again)."""
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    async with app.run_test(size=(120, 36)) as pilot:
        assert await wait_for(pilot, lambda: app._inbox_ready, 300)
        open_gid = next(g for g in app.groups if g.startswith("dk.snak@"))
        closed = await app.session.create_group("familie", "closed", min_pow=10)
        chat = await app.session.create_group("snak", "open", min_pow=10, view="chat")
        app.refresh_groups()
        assert await wait_for(pilot, lambda: closed in app.groups and chat in app.groups, 300)

        def shown(action):
            return app.check_action(action, ())
        app.select_group(app.session.my_inbox)
        await pilot.pause(0.3)
        assert not shown("new_post") and not shown("invite") and shown("message")
        app.select_group(open_gid)
        await pilot.pause(0.3)
        assert shown("new_post") and not shown("invite") and not shown("reply")
        app.select_group(closed)
        await pilot.pause(0.3)
        assert shown("invite")

        app.select_group(chat)
        await pilot.pause(0.5)
        assert app.focused.id == "chat-input"
        assert shown("leave_input") and not shown("write")
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert app.focused.id == "chat-log" and shown("write") and shown("new_post")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.focused.id == "chat-input"
        await pilot.press("escape")
        await pilot.pause(0.2)
        await pilot.press("q")
    server.close()


async def test_tui_names_dialog(tmp_path, monkeypatch):
    """@ opens your names (UN-RFC 0019); a claim with no registrar is an error, not a crash."""
    from unseenet.client.tui import NamesDialog
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF))
    s.new_identity("andreas", "Andreas")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    notes = []
    real = app.notify
    monkeypatch.setattr(app, "notify", lambda msg, **kw: (notes.append(msg), real(msg, **kw)))
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None)
        await pilot.press("@")
        assert await wait_for(pilot, lambda: isinstance(app.screen, NamesDialog), 300)
        assert "no names yet" in str(app.screen.query_one("#names-details").render())
        app.screen.query_one("#value").value = "Lorensen"
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: any("registrar is not set up" in n for n in notes), 300)
        assert not isinstance(app.screen, NamesDialog)
    server.close()


async def test_tui_withdraw_own_post(tmp_path, monkeypatch):
    """D withdraws your own post after a warning that it is best effort (UN-RFC 0004, 7)."""
    from unseenet.client.tui import ConfirmDialog
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: len(app.groups) == 2, 300)
        gid = next(g for g in app.groups if g.startswith("dk.snak@"))
        await app.session.post(gid, "Ups", "Forkert\n")
        app.select_group(gid)
        assert await wait_for(pilot, lambda: len(app.session.cache.get(gid, {})) == 1, 300)
        await pilot.pause(0.3)
        app.query_one("#threads").focus()
        await pilot.press("down")
        assert await wait_for(pilot, lambda: app.current_message is not None, 100)
        assert app.check_action("withdraw", ())
        await pilot.press("D")
        assert await wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog), 100)
        assert "not deleted" in " ".join(str(w.render()) for w in app.screen.query("Static"))
        await pilot.click("#ok")
        assert await wait_for(pilot, lambda: not app.session.cache.get(gid), 300)
        await pilot.press("q")
    server.close()


async def test_tui_names_transfer_and_release(tmp_path, monkeypatch):
    """Under @ you can also transfer a name to another key, or release it (UN-RFC 0019, 6.5)."""
    from unseenet.client import naming
    from unseenet.client.tui import ConfirmDialog, InputDialog, NamesDialog
    from unseenet.core import crypto
    sent = []

    async def fake_claim(s, name, action="claim", to=None):
        sent.append((action, name, to))
        return "<x@y>"

    monkeypatch.setattr(naming, "claim", fake_claim)
    app, server = await _app_with_groups(tmp_path, monkeypatch, [])
    new_key = crypto.Identity.generate().key_text
    async with app.run_test(size=(120, 34)) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None, 300)
        for action in ("transfer", "release"):
            app.action_names()
            assert await wait_for(pilot, lambda: isinstance(app.screen, NamesDialog)
                                  and app.screen.query("#value"), 300)
            app.screen.query_one("#value").value = "lorensen"
            await pilot.pause(0.3)
            app.screen.query_one(f"#{action}").press()
            if action == "transfer":
                assert await wait_for(pilot, lambda: isinstance(app.screen, InputDialog), 300)
                await pilot.pause(0.2)
                app.screen.query_one("#value").value = new_key
                app.screen.query_one("#ok").press()
            assert await wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog), 300)
            await pilot.pause(0.2)
            app.screen.query_one("#ok").press()
            assert await wait_for(pilot, lambda: len(sent) == (1 if action == "transfer" else 2), 300)
        assert sent == [("transfer", "lorensen", new_key), ("release", "lorensen", None)]
        await pilot.press("q")
    server.close()


async def test_tui_ignore_and_show_again(tmp_path, monkeypatch):
    """#72: Ignore this person hides their posts; People you ignore shows them again."""
    from unseenet.client.tui import ConfirmDialog, KeyListDialog
    from unseenet.core import crypto
    from unseenet.core.article import new_article
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    other = crypto.Identity.generate()
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: len(app.groups) == 2, 300)
        gid = next(g for g in app.groups if g.startswith("dk.snak@"))
        art = new_article(gid, "Spam", "x\n", from_name="Trold").finalize(other, 10)
        await app.session._post_article(art)
        await app.session.post(gid, "Mit", "y\n")
        app.select_group(gid)
        assert await wait_for(pilot, lambda: len(app.messages) == 2, 300)
        await pilot.pause(0.5)                   # let the list settle: a re-render moves the cursor
        table = app.query_one("#threads")
        table.focus()
        for row in range(table.row_count):
            table.move_cursor(row=row)
            await pilot.pause(0.1)
            if app.current_message and app.current_message.subject == "Spam":
                break
        assert app.current_message.subject == "Spam"
        app.action_ignore()
        assert await wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog), 200)
        await pilot.pause(0.2)
        app.screen.query_one("#ok").press()
        assert await wait_for(pilot, lambda: [m.subject for m in app.messages.values()] == ["Mit"], 300)
        app.action_ignored()
        assert await wait_for(pilot, lambda: isinstance(app.screen, KeyListDialog), 200)
        await pilot.pause(0.2)
        app.screen.query_one("#who").value = other.key_text
        app.screen.query_one("#ok").press()
        assert await wait_for(pilot, lambda: len(app.messages) == 2, 300)
        await pilot.press("q")
    server.close()


async def test_tui_owner_bans_and_lifts(tmp_path, monkeypatch):
    """UN-RFC 0004 section 5.1 in the client: Ban from group, Banned from group."""
    from unseenet.client.tui import InputDialog, KeyListDialog
    from unseenet.core import crypto
    from unseenet.core.article import new_article
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    other = crypto.Identity.generate()
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: len(app.groups) == 2, 300)
        gid = next(g for g in app.groups if g.startswith("dk.snak@"))
        await app.session._post_article(new_article(gid, "Trussel", "x\n", from_name="T").finalize(other, 10))
        app.select_group(gid)
        assert await wait_for(pilot, lambda: len(app.messages) == 1, 300)
        app.current_message = next(iter(app.messages.values()))
        app.action_ban()
        assert await wait_for(pilot, lambda: isinstance(app.screen, InputDialog), 200)
        await pilot.pause(0.2)
        app.screen.query_one("#value").value = "trusler"
        app.screen.query_one("#ok").press()
        assert await wait_for(pilot, lambda: not app.messages, 300)
        assert app.session.banned(gid) == [(other.key_text, "trusler")]
        app.action_banned()
        assert await wait_for(pilot, lambda: isinstance(app.screen, KeyListDialog), 200)
        await pilot.pause(0.2)
        app.screen.query_one("#who").value = other.key_text
        app.screen.query_one("#ok").press()
        assert await wait_for(pilot, lambda: not app.session.banned(gid), 300)
        await pilot.press("q")
    server.close()


async def test_tui_make_and_remove_moderator(tmp_path, monkeypatch):
    """#70: Make moderator (key filled in from the selected post) and remove again."""
    from unseenet.client.tui import InputDialog, KeyListDialog
    from unseenet.core import crypto
    from unseenet.core.article import new_article
    app, server = await _app_with_groups(tmp_path, monkeypatch, ["dk.snak"])
    other = crypto.Identity.generate()
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: len(app.groups) == 2, 300)
        gid = next(g for g in app.groups if g.startswith("dk.snak@"))
        await app.session._post_article(new_article(gid, "Hej", "x\n", from_name="M").finalize(other, 10))
        app.select_group(gid)
        assert await wait_for(pilot, lambda: len(app.messages) == 1, 300)
        app.current_message = next(iter(app.messages.values()))
        app.action_add_role("moderators")
        assert await wait_for(pilot, lambda: isinstance(app.screen, InputDialog), 200)
        await pilot.pause(0.2)
        assert app.screen.query_one("#value").value == other.key_text
        app.screen.query_one("#ok").press()
        assert await wait_for(pilot, lambda: app.session.manifest_data(gid).get("moderators") == [other.key_text], 300)
        app.action_roles()
        assert await wait_for(pilot, lambda: isinstance(app.screen, KeyListDialog), 200)
        await pilot.pause(0.2)
        app.screen.query_one("#who").value = other.key_text
        app.screen.query_one("#ok").press()
        assert await wait_for(pilot, lambda: not app.session.manifest_data(gid).get("moderators"), 300)
        await pilot.press("q")
    server.close()


async def test_tui_moderation_queue(tmp_path, monkeypatch):
    """UN-RFC 0009 section 3 in the client: a submission waits in the queue and
    Approve posts it."""
    import unseenet.client.session as sess
    from unseenet.client.tui import ModerationDialog
    app, server = await _app_with_groups(tmp_path, monkeypatch, [])
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None, 300)
        s = app.session
        gid = await s.create_group("dk.mod", "moderated", min_pow=10)
        user = Session(Vault.open(tmp_path / "u.vault", "pw", **KDF), status=lambda *_: None)
        user.new_identity("u", "U"); user.add_node(addr); user.subscribe(gid)
        await user.fetch_group(gid)
        msgid = await user.post(gid, "Hej", "Må jeg?\n")
        app.action_moderation()
        assert await wait_for(pilot, lambda: isinstance(app.screen, ModerationDialog), 300)
        await pilot.pause(0.3)
        app.screen.query_one("#which").value = app.screen.items[0][0]
        app.screen.query_one("#approve").press()
        await user.close()
        assert await wait_for(pilot, lambda: s.data.get("moderation_done"), 300)
        msgs = await s.fetch_group(gid)
        assert [m.message_id for m in msgs] == [msgid]
        assert sess.SUBMISSION_TYPE == "message/unseenet"
        await pilot.press("q")
    server.close()


async def test_tui_report_post(tmp_path, monkeypatch):
    """#74: Report post lists who can act on it and sends the report."""
    from unseenet.client.tui import ReportDialog
    app, server = await _app_with_groups(tmp_path, monkeypatch, [])
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    owner = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    owner.new_identity("o", "Ejer"); owner.add_node(addr)
    await owner.ensure_inbox()
    gid = await owner.create_group("dk.snak", "open", min_pow=10)
    await owner.post(gid, "Grimt", "x\n")
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None, 300)
        app.session.subscribe(gid)
        await app._render_groups()
        for _ in range(5):              # the start-up refresh may pick another group first
            app.select_group(gid)
            if await wait_for(pilot, lambda: app.current_group == gid and len(app.messages) == 1, 100):
                break
        assert app.current_group == gid and len(app.messages) == 1
        app.current_message = next(iter(app.messages.values()))
        app.action_report()
        assert await wait_for(pilot, lambda: isinstance(app.screen, ReportDialog), 300)
        assert len(app.screen.targets) == 1                  # the owner (no operator here)
        await pilot.pause(0.2)
        app.screen.query_one("#note").value = "Trusler"
        app.screen.query_one("#ok").press()
        assert await wait_for(pilot, lambda: not isinstance(app.screen, ReportDialog), 200)
        for _ in range(100):                                 # sent in the background
            await owner.fetch_group(owner.my_inbox)
            if any(owner.reported_post(m) for m in owner.private_messages()):
                break
            await pilot.pause(0.1)
        assert any(owner.reported_post(m) for m in owner.private_messages())
        await pilot.press("q")
    await owner.close()
    server.close()


async def test_tui_give_a_name_and_answer_a_request(tmp_path, monkeypatch):
    """UN-RFC 0019 section 5.4 in the client: give a name under yours, and answer a request."""
    from unseenet import names as nm
    from unseenet.client import naming
    from unseenet.client.tui import InputDialog, ModerationDialog
    from unseenet.core import crypto
    app, server = await _app_with_groups(tmp_path, monkeypatch, [])
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    reg = crypto.Identity.generate()
    sonia = Session(Vault.open(tmp_path / "s.vault", "pw", **KDF), status=lambda *_: None)
    sonia.new_identity("s", "Sonia"); sonia.add_node(addr)
    await sonia.ensure_inbox()
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None, 300)
        s = app.session
        cert = nm.make_certificate(reg, "lorensen", s.identity().key_text, 1)
        for p in (s, sonia):
            st = p.data.setdefault("naming", {}).setdefault("names", {})
            st.update({"registrars": [reg.key_text], "certs": [cert.to_json()], "revoked": []})

        app.action_give_subname()
        for value in ("andreas@lorensen", s.identity().key_text, "2"):
            assert await wait_for(pilot, lambda: isinstance(app.screen, InputDialog), 200)
            await pilot.pause(0.2)
            app.screen.query_one("#value").value = value
            app.screen.query_one("#ok").press()
            await pilot.pause(0.2)
        assert await wait_for(pilot, lambda: [c.name for c in naming.names_given(s)] == ["andreas@lorensen"], 300)
        assert s.identity_label(s.identity().key_text) == "andreas@lorensen"

        await naming.request_subname(sonia, "sonia@lorensen")
        app.action_name_requests()
        assert await wait_for(pilot, lambda: isinstance(app.screen, ModerationDialog), 300)
        await pilot.pause(0.3)
        app.screen.query_one("#which").value = app.screen.items[0][0]
        app.screen.query_one("#approve").press()
        assert await wait_for(pilot, lambda: "sonia@lorensen" in [c.name for c in naming.names_given(s)], 300)
        await pilot.press("q")
    await sonia.fetch_group(sonia.my_inbox)
    naming.take_certificates(sonia)
    assert [c.name for c in naming.my_names(sonia)] == ["sonia@lorensen"]
    await sonia.close()
    server.close()


async def test_tui_for_you(tmp_path, monkeypatch):
    """#109: 'For you' at the top of the groups lists a reply to your post, marked."""
    from unseenet.client.tui import FOR_YOU, REPLY_MARK
    app, server = await _app_with_groups(tmp_path, monkeypatch, [])
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    other = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    other.new_identity("o", "Other"); other.add_node(addr)
    gid = await other.create_group("dk.snak", "open", min_pow=10)
    async with app.run_test(size=(140, 40)) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None, 300)
        s = app.session
        s.subscribe(gid)
        mine = await s.post(gid, "Spørgsmål", "?\n")
        await other.fetch_group(gid)
        await other.post(gid, "Re: Spørgsmål", "Svar\n", references=[mine])
        await s.fetch_group(gid)
        app.refresh_groups()
        assert await wait_for(pilot, lambda: gid in app.groups, 300)
        await pilot.pause(0.3)
        app.select_group(FOR_YOU)
        assert await wait_for(pilot, lambda: [m.subject for m in app.messages.values()] == ["Re: Spørgsmål"], 300)
        table = app.query_one("#threads")
        assert str(table.get_row_at(0)[1]).startswith(REPLY_MARK)
        assert "For you" in str(app.query_one("#threads-title").render())
        await pilot.press("q")
    await other.close()
    server.close()
