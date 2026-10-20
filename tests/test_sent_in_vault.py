"""Copies of sent private posts live in the vault itself; older sidecars move in."""
import json

from unseenet.client.session import SENT_SIDECAR, Session
from unseenet.core.vault import Vault

KDF = {"ops": 1, "mem": 8192 * 1024}


def test_old_sidecar_moves_into_the_vault(tmp_path):
    path = tmp_path / "old.vault"
    v = Vault.open(path, "pw", **KDF)
    v.save()
    entry = {"msgid": "<a@unseenet>", "to": "ed25519:x", "after": 1}
    v.write_sidecar(SENT_SIDECAR, json.dumps({"v": 1, "sent": [entry]}).encode())
    v.close()

    s = Session(Vault.open(path, "pw", **KDF), status=lambda *_: None)
    assert s.sent == [entry]
    assert not v.sidecar_path(SENT_SIDECAR).exists()
    s.vault.close()

    again = Vault.open(path, "pw", **KDF)          # the vault file alone has it now
    assert again.data["sent"] == [entry]
    again.close()


def test_new_vault_starts_empty(tmp_path):
    s = Session(Vault.open(tmp_path / "new.vault", "pw", **KDF), status=lambda *_: None)
    assert s.sent == [] and s.data["sent"] == []
    s.vault.close()
