"""Updating a stick in place (unseenet.update, issue #68)."""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

from unseenet import update
from unseenet.core.crypto import Identity

V_OLD, V_NEW = "0.2.1", "9.0.0"     # newer than any real version, so the tests outlive releases


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


def test_versions_order_pre_releases():
    """A stick on an alpha or its development build updates to the release (PEP 440)."""
    order = ["0.3.0.dev5", "0.3.0a1.dev2", "0.3.0a1", "0.3.0a2.dev10", "0.3.0a2",
             "0.3.0b1", "0.3.0rc1.dev1", "0.3.0rc1", "0.3.0", "0.3.1.dev1", "v0.3.1"]
    assert sorted(reversed(order), key=update.version_key) == order
    assert update.version_key("0.3.0") > update.version_key("0.3.0a2.dev10")


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
    "unseenet.apkovl.tar.gz": "the bootable system",
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
    z = update_zip(tmp_path, {"boot/vmlinuz-lts": "new kernel"}, version="9.0.1.dev2")
    sums = sums_for(z)
    served = {update.SUMS: sums, update.SIG: update.signature_text(sums, release).encode(),
              z.name: z.read_bytes()}

    def fake_fetch(url, socks_port, dest=None, progress=None):
        assert "/releases/download/" in url or "/releases/latest/download/" in url
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


# --- portable folders (the usb zip and the per-platform zips) -----------------

def portable_zip(tmp_path: Path, version: str = V_NEW, what: str = "usb") -> Path:
    z = tmp_path / f"unseenet-{version}-{what}.zip"
    files = {"UNSEENET-PORTABLE": "", "UNSEENET-VERSION": version + "\n",
             "linux-x86_64/unseenet": "new linux", "windows-x86_64/unseenet.exe": "new exe",
             "macos-aarch64/_internal/Python.framework/Versions/3.13/Python": "py",
             "macos-aarch64/_internal/Python.framework/Versions/3.13/Resources/Info.plist": "pl"}
    links = {"macos-aarch64/_internal/Python": "Python.framework/Versions/3.13/Python",
             "macos-aarch64/_internal/Python.framework/Versions/Current": "3.13"}
    with zipfile.ZipFile(z, "w") as zf:
        for name, text in files.items():
            info = zipfile.ZipInfo(f"{update.TOP}/{name}")
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith("unseenet") else 0o100644) << 16
            zf.writestr(info, text)
        for name, target in links.items():
            info = zipfile.ZipInfo(f"{update.TOP}/{name}")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            zf.writestr(info, target)
    return z


PORTABLE = {"UNSEENET-PORTABLE": "", "linux-x86_64/unseenet": "old", "windows-x86_64/unseenet.exe": "old",
            "macos-aarch64/_internal/x": "old", "data/unseenet.vault": "secret"}


def test_kind_of_installation(tmp_path):
    assert update.stick_kind(stick(tmp_path, OLD | {"unseenet.apkovl.tar.gz": ""})) == "x86_64-update"
    assert update.stick_kind(stick(tmp_path / "a", PORTABLE)) == "usb"
    one = stick(tmp_path / "b", {"UNSEENET-PORTABLE": "", "windows-x86_64/unseenet.exe": "x"})
    assert update.stick_kind(one) == "windows-x86_64"


def test_portable_zip_strips_its_folder_keeps_modes_and_links(tmp_path):
    media = stick(tmp_path, PORTABLE)
    update.apply(media, portable_zip(tmp_path), say=lambda _: None)
    assert (media / "linux-x86_64/unseenet").read_text() == "new linux"
    assert (media / "data/unseenet.vault").read_text() == "secret"
    assert not (media / update.TOP).exists()
    if os.name != "nt":
        assert (media / "linux-x86_64/unseenet").stat().st_mode & 0o111
    py = media / "macos-aarch64/_internal/Python"
    assert py.read_text() == "py"                 # a link, or a copy where links fail
    current = media / "macos-aarch64/_internal/Python.framework/Versions/Current"
    assert (current / "Resources/Info.plist").read_text() == "pl"


def test_links_become_copies_where_the_file_system_has_none(tmp_path, monkeypatch):
    def no_links(*_a, **_k):
        raise OSError("FAT has no links")
    monkeypatch.setattr(update.os, "symlink", no_links)
    media = stick(tmp_path, PORTABLE)
    update.apply(media, portable_zip(tmp_path), say=lambda _: None)
    py = media / "macos-aarch64/_internal/Python"
    assert not py.is_symlink() and py.read_text() == "py"
    current = media / "macos-aarch64/_internal/Python.framework/Versions/Current"
    assert current.is_dir() and not current.is_symlink()
    assert (current / "Resources/Info.plist").read_text() == "pl"


def test_a_running_program_is_moved_aside(tmp_path, monkeypatch):
    media = stick(tmp_path, PORTABLE)
    exe = media / "windows-x86_64/unseenet.exe"
    real = os.replace
    busy = {str(exe)}

    def replace(src, dst):                 # Windows: a running .exe cannot be replaced
        if str(dst) in busy and not str(src).endswith(update.OLD_SUFFIX):
            if Path(src).name.endswith(".new"):
                busy.discard(str(dst))
                raise PermissionError("in use")
        return real(src, dst)
    monkeypatch.setattr(update.os, "replace", replace)
    update.apply(media, portable_zip(tmp_path), say=lambda _: None)
    assert exe.read_text() == "new exe"
    aside = exe.with_name(exe.name + update.OLD_SUFFIX)
    assert aside.read_text() == "old"
    update.clean_old(media)
    assert not aside.exists() and (media / "data/unseenet.vault").exists()


def test_offline_zip_must_be_for_this_kind(keys, tmp_path, capsys):
    project, _ = keys
    media = stick(tmp_path, PORTABLE)
    folder = tmp_path / "dl"
    folder.mkdir()
    z = update_zip(folder, {"boot/vmlinuz-lts": "k"})       # the image's, not the usb zip
    with pytest.raises(SystemExit) as exit_:
        update.main(["--media", str(media), "--zip", str(z), "--yes"])
    assert exit_.value.code == 2 and "not the zip for this stick" in capsys.readouterr().err
    z = portable_zip(folder)
    sums = sums_for(z)
    (folder / update.SUMS).write_bytes(sums)
    (folder / update.SIG).write_text(update.signature_text(sums, project))
    with pytest.raises(SystemExit) as exit_:
        update.main(["--media", str(media), "--zip", str(z), "--yes"])
    assert exit_.value.code == 0
    assert (media / "windows-x86_64/unseenet.exe").read_text() == "new exe"


def test_a_graphical_stick_is_not_updated_with_these_releases(tmp_path, capsys):
    """unseenet-gui's builds carry the graphical client: unseenet's zips would remove it."""
    media = stick(tmp_path, OLD)
    (media / "README-graphical.txt").write_text("graphical")
    with pytest.raises(SystemExit) as exit_:
        update.main(["--media", str(media), "--yes", "--no-tor"])
    assert exit_.value.code == 2 and "graphical client" in capsys.readouterr().err
