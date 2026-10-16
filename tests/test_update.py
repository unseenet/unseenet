"""Updating a stick in place (unseenet.update, issue #68)."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from unseenet import update
from unseenet.core.crypto import Identity

V_OLD, V_NEW = "0.2.1", "0.3.0"


@pytest.fixture
def keys(monkeypatch):
    project, release = Identity.generate(), Identity.generate()
    monkeypatch.setitem(update.TRUSTED, "stable", (project.key_text,))
    monkeypatch.setitem(update.TRUSTED, "dev", (project.key_text, release.key_text))
    return project, release


def stick(tmp_path: Path, files: dict[str, str]) -> Path:
    media = tmp_path / "stick"
    for name, text in files.items():
        (media / name).parent.mkdir(parents=True, exist_ok=True)
        (media / name).write_text(text)
    return media


def update_zip(tmp_path: Path, files: dict[str, str], version: str = V_NEW) -> Path:
    files = {**files, update.VERSION_FILE: version + "\n"}
    files[update.FILES_LIST] = "\n".join(sorted([*files, update.FILES_LIST])) + "\n"
    z = tmp_path / f"unseenet-{version}-x86_64-update.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return z


def sums_for(*paths: Path) -> bytes:
    return "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                   for p in paths).encode()


# --- trust ------------------------------------------------------------------

def test_versions_order():
    order = ["0.2.1.dev3", "0.2.1", "0.2.2.dev1", "0.2.2", "0.10.0"]
    assert sorted(order, key=update.version_key) == order


def test_stable_trusts_only_the_project_key(keys, tmp_path):
    project, release = keys
    sums = sums_for(update_zip(tmp_path, {"a": "1"}))
    rel = update.check_release(sums, update.signature_text(sums, project), "stable")
    assert rel.version == V_NEW and rel.signed_by == project.key_text
    with pytest.raises(update.UpdateError, match="not trusted"):
        update.check_release(sums, update.signature_text(sums, release), "stable")
    assert update.check_release(sums, update.signature_text(sums, release), "dev").version == V_NEW


def test_changed_sums_are_refused(keys, tmp_path):
    project, _ = keys
    sums = sums_for(update_zip(tmp_path, {"a": "1"}))
    sig = update.signature_text(sums, project)
    with pytest.raises(update.UpdateError, match="wrong"):
        update.check_release(sums.replace(b"  ", b"  x", 1), sig, "stable")


def test_a_stranger_cannot_sign(keys, tmp_path):
    sums = sums_for(update_zip(tmp_path, {"a": "1"}))
    with pytest.raises(update.UpdateError, match="not trusted"):
        update.check_release(sums, update.signature_text(sums, Identity.generate()), "dev")


def test_pinned_keys_are_real_keys():
    from unseenet.core.crypto import key_from_text
    for key in (*update.TRUSTED["stable"], *update.TRUSTED["dev"]):
        assert len(key_from_text(key)) == 32


# --- replacing files ----------------------------------------------------------

OLD = {
    update.VERSION_FILE: V_OLD,
    update.FILES_LIST: "UNSEENET-VERSION\nboot/vmlinuz-lts\nold-only.txt\nboot/syslinux/menu.c32\n",
    "boot/vmlinuz-lts": "old kernel",
    "boot/syslinux/ldlinux.sys": "sectors",
    "boot/syslinux/menu.c32": "old c32",
    "boot/syslinux/SYSLINUX-VERSION": "syslinux-6.04-r1",
    "old-only.txt": "gone in the new version",
    "my-own-file.txt": "the user's: never listed, never removed",
    "data/unseenet.vault": "secret",
    "data/boot.json": "{}",
}


def test_update_keeps_data_and_replaces_the_rest(tmp_path):
    media = stick(tmp_path, OLD)
    z = update_zip(tmp_path, {"boot/vmlinuz-lts": "new kernel", "boot/syslinux/menu.c32": "new c32",
                              "boot/syslinux/SYSLINUX-VERSION": "syslinux-6.04-r1",
                              "new.txt": "new"})
    plan = update.apply(media, z, say=lambda _: None)
    assert (media / "boot/vmlinuz-lts").read_text() == "new kernel"
    assert (media / "boot/syslinux/menu.c32").read_text() == "new c32"   # same syslinux
    assert (media / "new.txt").exists() and not (media / "old-only.txt").exists()
    assert (media / "my-own-file.txt").exists()
    assert (media / "data/unseenet.vault").read_text() == "secret"
    assert (media / "boot/syslinux/ldlinux.sys").read_text() == "sectors"
    assert update.stick_version(media) == V_NEW
    assert update.unfinished(media) is None
    assert plan.replace[-1] == "boot/vmlinuz-lts"                       # kernel last
    assert not list(media.rglob("*.new"))


def test_other_syslinux_keeps_the_sticks_c32_files(tmp_path):
    media = stick(tmp_path, OLD)
    z = update_zip(tmp_path, {"boot/syslinux/menu.c32": "new c32",
                              "boot/syslinux/syslinux.cfg": "new cfg",
                              "boot/syslinux/SYSLINUX-VERSION": "syslinux-6.05-r1"})
    update.apply(media, z, say=lambda _: None)
    assert (media / "boot/syslinux/menu.c32").read_text() == "old c32"
    assert (media / "boot/syslinux/SYSLINUX-VERSION").read_text() == "syslinux-6.04-r1"
    assert (media / "boot/syslinux/syslinux.cfg").read_text() == "new cfg"


@pytest.mark.parametrize("bad", ["data/unseenet.vault", "../escape", "/etc/passwd",
                                 "boot/syslinux/ldlinux.sys", "DATA/x"])
def test_a_zip_may_not_touch_data_or_escape(tmp_path, bad):
    media = stick(tmp_path, OLD)
    z = update_zip(tmp_path, {bad: "evil"})
    with pytest.raises(update.UpdateError):
        update.apply(media, z, say=lambda _: None)
    assert (media / "data/unseenet.vault").read_text() == "secret"
    assert update.stick_version(media) == V_OLD


def test_not_enough_room_changes_nothing(tmp_path, monkeypatch):
    media = stick(tmp_path, OLD)
    z = update_zip(tmp_path, {"boot/vmlinuz-lts": "new kernel"})
    monkeypatch.setattr(update.shutil, "disk_usage", lambda _: type("U", (), {"free": 1})())
    with pytest.raises(update.UpdateError, match="MB free"):
        update.apply(media, z, say=lambda _: None)
    assert (media / "boot/vmlinuz-lts").read_text() == "old kernel"
    assert update.unfinished(media) is None


# --- the command, end to end (downloads faked) --------------------------------

def test_command_downloads_checks_and_updates(keys, tmp_path, monkeypatch, capsys):
    project, release = keys
    media = stick(tmp_path, OLD)
    z = update_zip(tmp_path, {"boot/vmlinuz-lts": "new kernel"}, version="0.3.1.dev2")
    sums = sums_for(z)
    served = {update.SUMS: sums, update.SIG: update.signature_text(sums, release).encode(),
              z.name: z.read_bytes()}

    def fake_fetch(url, socks_port, dest=None, progress=None):
        assert "/releases/download/dev/" in url or "/releases/latest/download/" in url
        data = served[url.rsplit("/", 1)[1]]
        if dest is None:
            return data
        dest.write_bytes(data)
        return b""

    monkeypatch.setattr(update, "fetch", fake_fetch)
    with pytest.raises(SystemExit) as exit_:
        update.main(["--media", str(media), "--channel", "dev", "--yes", "--no-tor"])
    assert exit_.value.code == 0
    assert (media / "boot/vmlinuz-lts").read_text() == "new kernel"
    assert "release key" in capsys.readouterr().out
    with pytest.raises(SystemExit):     # the same again: up to date
        update.main(["--media", str(media), "--channel", "dev", "--yes", "--no-tor"])
    assert "up to date" in capsys.readouterr().out
    # stable refuses what only the release key signed
    with pytest.raises(SystemExit) as exit_:
        update.main(["--media", str(media), "--yes", "--no-tor", "--force"])
    assert exit_.value.code == 2 and "not trusted" in capsys.readouterr().err


def test_offline_zip_needs_its_signed_sums(keys, tmp_path, capsys):
    project, _ = keys
    media = stick(tmp_path, OLD)
    folder = tmp_path / "dl"
    folder.mkdir()
    z = update_zip(folder, {"boot/vmlinuz-lts": "new kernel"})
    args = ["--media", str(media), "--zip", str(z), "--yes"]
    with pytest.raises(SystemExit) as exit_:
        update.main(args)
    assert exit_.value.code == 2 and "next to the zip" in capsys.readouterr().err
    sums = sums_for(z)
    (folder / update.SUMS).write_bytes(sums)
    (folder / update.SIG).write_text(update.signature_text(sums, project))
    with pytest.raises(SystemExit) as exit_:
        update.main(args)
    assert exit_.value.code == 0
    assert (media / "boot/vmlinuz-lts").read_text() == "new kernel"
