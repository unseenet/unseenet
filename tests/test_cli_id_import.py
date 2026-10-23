"""`unseenet id-import`: an identity from a seed on stdin (for unseenet-demo, #385)."""
import io
import json
from argparse import Namespace

import pytest

from unseenet import cli
from unseenet.core import crypto
from unseenet.core.vault import Vault

KDF = {"ops": 1, "mem": 8192 * 1024}


def _app(tmp_path):
    return cli.App(Vault.open(tmp_path / "v.vault", "pw", **KDF))


async def _import(app, monkeypatch, name, line, display=None):
    monkeypatch.setattr("sys.stdin", io.StringIO(line + "\n"))
    await cli.c_id_import(app, Namespace(name=name, display=display, json=True))


async def test_an_identity_from_a_seed(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path)
    seed = bytes(range(32))
    key = crypto.Identity.from_seed(seed).key_text
    await _import(app, monkeypatch, "bee", seed.hex(), display="Bee Keeper")
    out = json.loads(capsys.readouterr().out)
    assert out["key"] == key and out["new"] and app.data["identities"]["bee"]["display"] == "Bee Keeper"
    await _import(app, monkeypatch, "bee", seed.hex())                  # again: nothing changes
    assert json.loads(capsys.readouterr().out)["new"] is False
    assert app.data["identities"]["bee"]["display"] == "Bee Keeper"
    with pytest.raises(SystemExit, match="another key"):
        await _import(app, monkeypatch, "bee", bytes(32).hex())
    for bad in ("", "zz" * 32, "00" * 31):
        with pytest.raises(SystemExit, match="64 hex"):
            await _import(app, monkeypatch, "x", bad)
    await cli.c_whoami(app, Namespace(json=True))
    who = json.loads(capsys.readouterr().out)["identities"]
    assert [(w["name"], w["key"], w["default"]) for w in who] == [("bee", key, True)]
    assert Vault.open(tmp_path / "v.vault", "pw", **KDF).data["identities"]["bee"]["seed"] == seed.hex()
