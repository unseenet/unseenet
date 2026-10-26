"""`unseenet passphrase` (#579): the CLI changes the vault's passphrase like the clients do."""
import json
from argparse import Namespace

import pytest

from unseenet import cli
from unseenet.core.vault import Vault, VaultError

KDF = {"ops": 1, "mem": 8192 * 1024}


def _app(tmp_path, pw="old-pw"):
    app = cli.App(Vault.open(tmp_path / "v.vault", pw, **KDF))
    app.passphrase = pw
    return app


async def test_from_the_environment(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path)
    app.data["nodes"].append("x.onion"); app.vault.save()
    monkeypatch.setenv("UNSEENET_NEW_PASSPHRASE", "new-pw")
    await cli.c_passphrase(app, Namespace(json=True))
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and "old passphrase" in out["note"]
    assert Vault.open(tmp_path / "v.vault", "new-pw", **KDF).data["nodes"] == ["x.onion"]
    with pytest.raises(VaultError):
        Vault.open(tmp_path / "v.vault", "old-pw", **KDF)


async def test_from_the_terminal_asked_twice(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path)
    monkeypatch.delenv("UNSEENET_NEW_PASSPHRASE", raising=False)
    answers = iter(["new-pw", "other"])
    monkeypatch.setattr(cli.basics.getpass, "getpass", lambda prompt="": next(answers))
    with pytest.raises(SystemExit, match="not the same"):
        await cli.c_passphrase(app, Namespace(json=False))
    answers = iter(["new-pw", "new-pw"])
    await cli.c_passphrase(app, Namespace(json=False))
    assert capsys.readouterr().out.startswith("Passphrase changed.")
    Vault.open(tmp_path / "v.vault", "new-pw", **KDF)


@pytest.mark.parametrize("new, msg", [("abc", "too short"), ("old-pw", "same as the current")])
async def test_refused_and_nothing_changes(tmp_path, monkeypatch, new, msg):
    app = _app(tmp_path)
    monkeypatch.setenv("UNSEENET_NEW_PASSPHRASE", new)
    with pytest.raises(SystemExit, match=msg):
        await cli.c_passphrase(app, Namespace(json=True))
    Vault.open(tmp_path / "v.vault", "old-pw", **KDF)


async def test_wrong_current(tmp_path, monkeypatch):
    app = _app(tmp_path)
    app.passphrase = "not-it"
    monkeypatch.setenv("UNSEENET_NEW_PASSPHRASE", "new-pw")
    with pytest.raises(SystemExit, match="not right"):
        await cli.c_passphrase(app, Namespace(json=True))


def test_in_the_parser(capsys):
    with pytest.raises(SystemExit):
        cli.client_main(["passphrase", "--help"])
    assert "UNSEENET_NEW_PASSPHRASE" in capsys.readouterr().out
