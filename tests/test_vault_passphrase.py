"""Changing a vault's passphrase: the vault, its sidecars, and copies elsewhere."""

import shutil

import pytest

from unseenet.core.vault import Vault, VaultError

KDF = {"ops": 1, "mem": 8192 * 1024}


def _vault(tmp_path):
    path = tmp_path / "me.vault"
    v = Vault.open(path, "old", **KDF)
    v.data["identities"]["me"] = {"secret": "k"}
    v.save()
    v.write_sidecar("cache", b"cached")
    return path, v


def test_change_passphrase_reencrypts_vault_and_sidecars(tmp_path):
    path, v = _vault(tmp_path)
    assert (tmp_path / "me.vault.lock").exists()          # beside it, and not a sidecar
    assert v.sidecar_names() == ["cache"]
    v.change_passphrase("old", "new")
    v.close()
    with pytest.raises(VaultError):
        Vault.open(path, "old")
    w = Vault.open(path, "new")
    assert w.data["identities"]["me"] == {"secret": "k"}
    assert w.read_sidecar("cache") == b"cached"
    assert w.check_passphrase("new") and not w.check_passphrase("old")


def test_wrong_current_passphrase_changes_nothing(tmp_path):
    path, v = _vault(tmp_path)
    before = path.read_bytes()
    with pytest.raises(VaultError):
        v.change_passphrase("guess", "new")
    assert path.read_bytes() == before
    v.close()
    Vault.open(path, "old").close()


def test_a_copy_keeps_the_old_passphrase(tmp_path):
    """The thing to tell users: only the file you change gets the new passphrase."""
    path, v = _vault(tmp_path)
    copy = tmp_path / "stick" / "me.vault"
    copy.parent.mkdir()
    shutil.copy2(path, copy)
    v.change_passphrase("old", "new")
    c = Vault.open(copy, "old")
    assert c.data["identities"]["me"] == {"secret": "k"}   # same keys, old passphrase


def test_backups_and_unknown_files_are_not_sidecars(tmp_path):
    path, v = _vault(tmp_path)
    (tmp_path / "me.vault.old-20261021-180000").write_bytes(path.read_bytes())
    (tmp_path / "me.vault.notes").write_text("mine")
    assert v.sidecar_names() == ["cache"]
    v.change_passphrase("old", "new")
    assert (tmp_path / "me.vault.notes").read_text() == "mine"


def test_a_failed_save_keeps_the_old_passphrase(tmp_path, monkeypatch):
    """A full disk while changing: the file keeps the old passphrase, and so does the
    program - a later save must not switch it to the new one behind the person's back."""
    path, v = _vault(tmp_path)

    def full(*_a, **_k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(v, "_atomic_write", full)
    with pytest.raises(OSError):
        v.change_passphrase("old", "new")
    monkeypatch.undo()
    v.data["identities"]["me"]["note"] = "later"
    v.save()                                               # an ordinary save afterwards
    v.close()
    assert Vault.open(path, "old").data["identities"]["me"]["note"] == "later"
    with pytest.raises(VaultError):
        Vault.open(path, "new")
