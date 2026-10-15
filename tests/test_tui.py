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
        assert app.session.my_inbox in app.groups
        await pilot.press("o")
        await pilot.pause(0.5)
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
        assert await wait_for(pilot, lambda: len(app.messages) == 1, 100)
        await pilot.press("n")
        await pilot.pause(0.3)
        await pilot.press(*"Ja")
        await pilot.click("#body")
        await pilot.press(*"Jeg kommer")
        await pilot.press("ctrl+s")
        assert await wait_for(pilot, lambda: len(app.messages) == 2, 400)
        rows = [app._who(m) for m in app.messages.values()]
        assert rows[0].startswith("Sonia (datter) ✓") and rows[1] == "You"
        await pilot.press("q")
    server.close()
