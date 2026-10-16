"""The menu of the bootable image (unseenet.boot), run here without the image."""

from pathlib import Path

import pytest

from unseenet import boot


def test_find_media_and_settings(tmp_path, monkeypatch):
    (tmp_path / "UNSEENET-PORTABLE").touch()
    monkeypatch.setenv("UNSEENET_HOME", str(tmp_path))
    media = boot.find_media()
    assert media == tmp_path and boot.writable(media)
    boot.save_settings(media, {"keymap": "dk/dk"})
    assert boot.load_settings(media) == {"keymap": "dk/dk"}
    assert (tmp_path / "data" / "boot.json").exists()


def test_wifi_parsing(monkeypatch):
    listing = [
        "                               Available networks",
        "--------------------------------------------------------------------------------",
        "      Network name                      Security            Signal",
        "--------------------------------------------------------------------------------",
        "  \x1b[1;90m>   \x1b[0mHjemme                            psk                 ****",
        "      Café gratis                       open                **",
        "",
    ]
    monkeypatch.setattr(boot, "_iwctl", lambda *a, **k: [boot.ANSI.sub("", ln) for ln in listing])
    monkeypatch.setattr(boot.time, "sleep", lambda s: None)
    assert boot.wifi_networks("wlan0") == [("Hjemme", "psk", "****", True),
                                           ("Café gratis", "open", "**", False)]


def test_keymaps_common_first(tmp_path, monkeypatch):
    for name in ("us/us", "dk/dk", "dk/dk-latin1", "hu/hu"):
        f = tmp_path / f"{name}.bmap.gz"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"")
    monkeypatch.setattr(boot, "KEYMAPS", str(tmp_path))
    assert boot.keymaps()[:2] == ["us/us", "dk/dk"]
    assert set(boot.keymaps()) == {"us/us", "dk/dk", "dk/dk-latin1", "hu/hu"}


async def test_menu_starts(tmp_path, monkeypatch):
    (tmp_path / "UNSEENET-PORTABLE").touch()
    monkeypatch.setenv("UNSEENET_HOME", str(tmp_path))
    monkeypatch.setattr(boot, "addresses", lambda: [("eth0", "10.0.2.15")])
    monkeypatch.setattr(boot, "node_running", lambda: None)
    monkeypatch.setattr(boot, "keymaps", lambda: ["us/us", "dk/dk"])
    app = boot.BootMenu()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.3)
        status = str(app.query_one("#status").render())
        assert "eth0 10.0.2.15" in status and "no vault yet" in status
        menu = app.query_one("#menu")
        assert menu.option_count == len(boot.ITEMS)
        app.save_screenshot(str(tmp_path / "boot-menu.svg"))
        await pilot.press("down", "down", "down", "down", "enter")     # Keyboard
        await pilot.pause(0.3)
        assert isinstance(app.screen, boot.Pick)
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, boot.Pick)


def test_load_keymap_hands_over_the_bytes(tmp_path, monkeypatch):
    """A keymap is binary; re-encoded as text it scrambled the keyboard."""
    import gzip
    table = bytes(range(256)) * 4
    (tmp_path / "dk").mkdir()
    (tmp_path / "dk" / "dk.bmap.gz").write_bytes(gzip.compress(table))
    monkeypatch.setattr(boot, "KEYMAPS", str(tmp_path))
    got = {}

    def fake_run(cmd, input=None, **kw):
        got["cmd"], got["input"] = cmd, input
        return boot.subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(boot.subprocess, "run", fake_run)
    assert boot.load_keymap("dk/dk")
    assert got == {"cmd": ["loadkmap"], "input": table}
    assert not boot.load_keymap("xx/xx")


def test_logo_is_symmetric_and_drawable():
    from unseenet import logo
    assert len({len(row) for row in logo.ICON}) == 1
    assert all(row == row[::-1] for row in logo.ICON)
    assert set("".join(logo.ICON)) <= set(" " + "".join(logo.COLORS))
    # only characters the Linux console font (CP437) has
    drawn = logo.ansi_icon() + logo.WORDMARK
    plain = boot.ANSI.sub("", drawn).replace("\n", "")
    plain.encode("cp437")
    assert logo.rich_icon().plain.count("\n") == len(logo.ICON) // 2 - 1
