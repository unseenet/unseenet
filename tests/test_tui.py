"""Headless TUI test against a local node (no Tor)."""

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
        await pilot.press("c")
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
    assert time.time() - t < 1.0          # no key derivation per save
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
        await pilot.press("c")
        await pilot.pause(0.3)
        await pilot.press(*"andlo,test")
        await pilot.click("#ok")
        await pilot.pause(0.3)
        assert isinstance(app.screen, CreateGroupDialog)          # still open
        assert app.screen.query_one("#name").value == "andlo,test"  # nothing lost
        assert "','" in str(app.screen.query_one("#name-help").render())
        name = app.screen.query_one("#name")
        name.value = "andlo.test"
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
    await b.send_private(a.my_inbox, "Hej far", "Kan du hente mig?\n")
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
        assert rows[0].startswith("Sonia (datter) ✓") and rows[1] == "You"
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
        assert any("Owner: Hej alle!" in ln for ln in lines)
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
            "Friend: Er du der?" in str(ln.text) for ln in app.query_one("#chat-log").lines), 100)
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
        await pilot.pause(0.3)
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
