"""The terminal client's Change passphrase command."""

import pytest

pytest.importorskip("textual")

from textual.widgets import Input  # noqa: E402

from unseenet.client.session import Session  # noqa: E402
from unseenet.client.tui import UnseenetApp  # noqa: E402
from unseenet.core.vault import Vault, VaultError  # noqa: E402

from tuihelp import app_ready, laid_out, press, stack, wait_for  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


def _fill(app, old, new, again=None):
    app.screen.query_one("#old", Input).value = old
    app.screen.query_one("#pw", Input).value = new
    app.screen.query_one("#pw2", Input).value = new if again is None else again


async def test_tui_change_passphrase(tmp_path, monkeypatch):
    vault_path = tmp_path / "me.vault"
    s = Session(Vault.open(vault_path, "pw", **KDF))
    s.new_identity("andreas", "Andreas")
    s.add_node("127.0.0.1:9")
    s.vault.close()

    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(vault_path)
    async with app.run_test(size=(140, 45)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        app.action_change_passphrase()
        assert await wait_for(pilot, lambda: laid_out(app, "#old")), stack(app)
        _fill(app, "wrong", "secret words")
        await press(pilot, app, "#ok")
        # a wrong current passphrase: the dialog comes back with the error
        assert await wait_for(pilot, lambda: bool(app.screen.query(".error"))), stack(app)
        _fill(app, "pw", "secret words")
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: type(app.screen).__name__ != "ChangePassphraseDialog"
                              and app.session.vault.check_passphrase("secret words"), 400)
        await pilot.press("q")
    with pytest.raises(VaultError):
        Vault.open(vault_path, "pw", **KDF)
    v = Vault.open(vault_path, "secret words", **KDF)
    assert v.data["identities"]
