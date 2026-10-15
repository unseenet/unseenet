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
