"""UN-RFC 0050 section 5 (unseenet-gui#145): a device opens the vault with a secret its
secure hardware releases after its PIN - the passphrase still opens it, the file alone
opens nothing, and a new passphrase removes the devices."""

import base64
import os

import pytest

from unseenet.client.localapi import LocalAPI
from unseenet.client.session import SessionError
from unseenet.core.vault import Vault, VaultError, device_unlocks_of

KDF = {"ops": 1, "mem": 8192 * 1024}


def _vault(tmp_path):
    v = Vault.open(tmp_path / "me.vault", "pw", **KDF)
    v.data["hello"] = "world"
    v.save()
    return v


def test_a_device_opens_it_and_the_passphrase_still_does(tmp_path):
    v = _vault(tmp_path)
    secret = os.urandom(32)
    with pytest.raises(VaultError):
        v.add_device_unlock("wrong", "cred-1", secret)       # the passphrase is needed
    v.add_device_unlock("pw", "cred-1", secret, "This phone")
    assert [(d["id"], d["label"]) for d in device_unlocks_of(v.path)] == [("cred-1", "This phone")]
    assert secret.hex() not in v.unlock_path().read_text()   # the secret is never kept
    v.close()
    w = Vault.open_with_device(v.path, "cred-1", secret)
    assert w.data["hello"] == "world"
    w.close()
    with pytest.raises(VaultError):
        Vault.open_with_device(v.path, "cred-1", os.urandom(32))   # another secret
    with pytest.raises(VaultError):
        Vault.open_with_device(v.path, "cred-2", secret)           # another device
    with pytest.raises(VaultError):
        Vault.open_with_device(v.path, "cred-1", b"short")
    Vault.open(v.path, "pw", **KDF).close()                         # the passphrase, as before


def test_a_new_passphrase_removes_the_devices(tmp_path):
    v = _vault(tmp_path)
    secret = os.urandom(32)
    v.add_device_unlock("pw", "cred-1", secret)
    v.change_passphrase("pw", "new")
    assert device_unlocks_of(v.path) == [] and not v.unlock_path().exists()
    v.close()
    with pytest.raises(VaultError):
        Vault.open_with_device(v.path, "cred-1", secret)


def test_remove_one_or_all(tmp_path):
    v = _vault(tmp_path)
    for i in range(3):
        v.add_device_unlock("pw", f"c{i}", os.urandom(32))
    assert v.remove_device_unlock("c1") == 1
    assert [d["id"] for d in v.device_unlocks()] == ["c0", "c2"]
    assert v.remove_device_unlock() == 2 and v.device_unlocks() == []
    v.close()


async def test_through_the_local_api(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    path = tmp_path / "me.vault"
    api = LocalAPI(path, refresh_seconds=3600)
    assert api.device_unlocks() == {"possible": True, "devices": []}
    await api.unlock("pw")
    secret = base64.b64encode(os.urandom(32)).decode()
    with pytest.raises(SessionError, match="passphrase is not right"):
        await api.add_device_unlock({"passphrase": "nope", "id": "cred", "secret": secret})
    got = await api.add_device_unlock({"passphrase": "pw", "id": "cred", "secret": secret,
                                       "label": "Firefox"})
    assert [d["label"] for d in got["devices"]] == ["Firefox"]
    await api.close()

    again = LocalAPI(path, refresh_seconds=3600)
    assert [d["id"] for d in again.device_unlocks()["devices"]] == ["cred"]     # locked: still there
    with pytest.raises(SessionError):
        await again.unlock("", device="cred", secret=base64.b64encode(os.urandom(32)).decode())
    state = await again.unlock("", device="cred", secret=secret)
    assert state["unlocked"]
    assert again.remove_device_unlock({"all": True})["devices"] == []
    await again.close()
