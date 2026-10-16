"""The menu of the bootable Unseenet image (tools/image): what you see after booting.

    python -m unseenet.boot              the menu on the console
    python -m unseenet.boot --self-test  check the running system (CI, and the
                                         "Self-test" entry of the boot loader)

The image is one FAT partition labelled UNSEENET with the portable builds and a
data/ folder. Booted, the same data/ is used (``UNSEENET_HOME``), so the vault is
the one you have when you start the stick on a running computer.

Deliberately plain: it starts the programs that already exist (unseenet-tui,
unseenet-node, unseenet-monitor), so a nicer menu is easy to build on top.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .console import console_css
from .logo import WORDMARK, rich_icon

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

MEDIA_MARKERS = ("unseenet.apkovl.tar.gz", "UNSEENET-PORTABLE")
NODE_SOCKET = "/run/unseenet/monitor.sock"
NODE_LOG = "/var/log/unseenet-node.log"
KEYMAPS = "/usr/share/bkeymaps"
COMMON_KEYMAPS = ["us/us", "dk/dk", "de/de", "gb/gb", "fr/fr", "se/se", "no/no", "fi/fi",
                  "nl/nl", "es/es", "it/it", "ch/ch", "pl/pl", "pt/pt", "be/be", "cz/cz"]

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# ----------------------------------------------------------------------
# The system: plain functions, so the self-test and the menu share them
# ----------------------------------------------------------------------
def run(*cmd: str, timeout: float = 20, **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, **kw)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(list(cmd), 127, "", str(exc))


def find_media() -> Path | None:
    """Where the UNSEENET partition is mounted (Alpine's init mounts it read-only)."""
    env = os.environ.get("UNSEENET_HOME")
    if env:
        return Path(env)
    try:
        mounts = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        return None
    for line in mounts:
        parts = line.split()
        if len(parts) > 2 and parts[2] in ("vfat", "msdos", "exfat"):
            mnt = Path(parts[1].replace("\\040", " "))
            if any((mnt / m).exists() for m in MEDIA_MARKERS):
                return mnt
    return None


def writable(media: Path) -> bool:
    """Make sure data/ can be written: remount the medium read-write if needed."""
    data = media / "data"
    probe = data / ".unseenet-write-test"
    for attempt in (1, 2):
        try:
            data.mkdir(exist_ok=True)
            probe.write_text("ok")
            probe.unlink()
            return True
        except OSError:
            if attempt == 1:
                run("mount", "-o", "remount,rw", str(media))
    return False


def settings_path(media: Path) -> Path:
    return media / "data" / "boot.json"


def load_settings(media: Path | None) -> dict:
    if media is None:
        return {}
    try:
        return json.loads(settings_path(media).read_text())
    except (OSError, ValueError):
        return {}


def save_settings(media: Path | None, settings: dict) -> None:
    if media is not None and writable(media):
        settings_path(media).write_text(json.dumps(settings, indent=1))


def keymaps() -> list[str]:
    """Available console keyboard layouts as "dk/dk", the common ones first."""
    base = Path(KEYMAPS)
    found = sorted(f"{p.parent.name}/{p.name.removesuffix('.bmap.gz')}"
                   for p in base.glob("*/*.bmap.gz")) if base.is_dir() else []
    return [k for k in COMMON_KEYMAPS if k in found] + [k for k in found if k not in COMMON_KEYMAPS]


def load_keymap(name: str) -> bool:
    path = Path(KEYMAPS) / f"{name}.bmap.gz"
    try:
        data = gzip.decompress(path.read_bytes())
    except OSError:
        return False
    # The keymap is binary: hand it over as bytes. (As text it was re-encoded as
    # UTF-8, which scrambled the table and left the keyboard dead.)
    try:
        return subprocess.run(["loadkmap"], input=data, capture_output=True,
                              timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def addresses() -> list[tuple[str, str]]:
    """(interface, IPv4 address) of the connected network interfaces."""
    out = []
    for line in run("ip", "-4", "-o", "addr", "show").stdout.splitlines():
        parts = line.split()
        if len(parts) > 3 and parts[1] != "lo":
            out.append((parts[1], parts[3].split("/")[0]))
    return out


# --- Wi-Fi, through iwd's iwctl ---------------------------------------------
def _iwctl(*args: str, timeout: float = 20) -> list[str]:
    res = run("iwctl", *args, timeout=timeout)
    return [ANSI.sub("", ln).rstrip() for ln in res.stdout.splitlines()]


def wifi_devices() -> list[str]:
    lines = _iwctl("device", "list")
    devs = []
    for ln in lines:
        parts = ln.split()
        if parts and parts[0] not in ("Devices", "Name") and not parts[0].startswith("-") \
                and "station" in ln:
            devs.append(parts[0])
    return devs


def wifi_networks(dev: str) -> list[tuple[str, str, str, bool]]:
    """(name, security, signal, connected) after a scan."""
    _iwctl("station", dev, "scan")
    time.sleep(3)
    nets, dashes = [], 0
    for ln in _iwctl("station", dev, "get-networks"):
        if ln.strip().startswith("---"):
            dashes += 1
            continue
        if dashes < 2 or not ln.strip():
            continue
        connected = ln.lstrip().startswith(">")
        cols = re.split(r"\s{2,}", ln.replace(">", " ", 1).strip())
        if len(cols) >= 3:
            nets.append((cols[0], cols[1], cols[2], connected))
    return nets


def wifi_connect(dev: str, name: str, passphrase: str | None) -> tuple[bool, str]:
    args = ["--passphrase", passphrase] if passphrase else []
    res = run("iwctl", *args, "station", dev, "connect", name, timeout=40)
    msg = ANSI.sub("", (res.stdout + res.stderr)).strip()
    return res.returncode == 0, msg or ("connected" if res.returncode == 0 else "failed")


# --- the node ---------------------------------------------------------------
NODE_TOML = """# Unseenet node on the bootable image. See https://unseenet.org/node/configuration/
[node]
name = "unseenet-boot"
min_pow = 18
retention_days = 90
new_groups = "accept"

# Peers: other nodes to exchange groups with.
# [[peer]]
# name = "friend"
# address = "....onion"
# key = "ed25519:..."
"""


def node_dir(media: Path) -> Path:
    return media / "data" / "node"


def node_running() -> int | None:
    res = run("pgrep", "-f", "unseenet-node --data")
    pids = [int(p) for p in res.stdout.split() if p.isdigit()]
    return pids[0] if pids else None


def start_node(media: Path, passphrase: str) -> tuple[bool, str]:
    if node_running():
        return True, "the node is already running"
    if not writable(media):
        return False, "the medium cannot be written"
    data = node_dir(media)
    data.mkdir(parents=True, exist_ok=True)
    config = data / "node.toml"
    if not config.exists():
        config.write_text(NODE_TOML)
    Path(NODE_SOCKET).parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, UNSEENET_NODE_PASSPHRASE=passphrase)
    log = open(NODE_LOG, "ab")
    subprocess.Popen(["/opt/unseenet/bin/unseenet-node", "--data", str(data), "--config",
                      str(config), "--monitor", NODE_SOCKET], env=env, stdout=log,
                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        time.sleep(1)
        text = Path(NODE_LOG).read_text(errors="replace")[-3000:]
        if "Stats for unseenet-monitor" in text:
            return True, "started"
        if not node_running():
            return False, text.strip().splitlines()[-1] if text.strip() else "it stopped"
    return True, "starting (Tor can take a minute)"


def stop_node() -> None:
    pid = node_running()
    if pid:
        run("kill", str(pid))


# ----------------------------------------------------------------------
# Self-test (CI boots the image with "unseenet.selftest" and reads this)
# ----------------------------------------------------------------------
def self_test() -> int:
    ok = True

    def check(name: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"{'ok  ' if good else 'FAIL'} {name}{': ' + detail if detail else ''}", flush=True)

    print(f"Unseenet bootable image {__version__}, Python {sys.version.split()[0]}", flush=True)
    media = find_media()
    check("the UNSEENET partition is mounted", media is not None, str(media or ""))
    if media is not None:
        check("data/ can be written", writable(media), str(media / "data"))
        check("portable builds on the medium", (media / "UNSEENET-PORTABLE").exists())
        check("the version is on the medium (for updates)",
              (media / "UNSEENET-VERSION").read_text().strip() == __version__
              if (media / "UNSEENET-VERSION").exists() else False)
    import ssl
    check("certificates for HTTPS (updates)",
          ssl.create_default_context().cert_store_stats()["x509_ca"] > 0)
    try:
        from .client import tui  # noqa: F401
        from . import monitor  # noqa: F401
        import nacl.bindings  # noqa: F401
        check("client, monitor and cryptography load", True)
    except Exception as exc:  # noqa: BLE001
        check("client, monitor and cryptography load", False, repr(exc))
    tor = run("tor", "--version").stdout.splitlines()
    check("Tor runs", bool(tor) and tor[0].startswith("Tor version"), tor[0] if tor else "")
    res = run("rc-service", "dbus", "status")
    check("dbus is running", res.returncode == 0)
    wireless = list(Path("/sys/class/net").glob("*/wireless"))
    res = run("rc-service", "iwd", "status")
    if wireless:                              # without Wi-Fi hardware (QEMU) iwd may stop
        check("iwd is running", res.returncode == 0)
    else:
        print(f"info iwd: no Wi-Fi hardware ({'running' if res.returncode == 0 else 'stopped'})",
              flush=True)
    check("keyboard layouts", "dk/dk" in keymaps())
    for _ in range(30):                       # DHCP may take a moment
        net = addresses()
        if net:
            break
        time.sleep(1)
    print(f"info network: {', '.join(f'{i} {a}' for i, a in net) or 'none'}", flush=True)
    if not ok or not net:                     # what went wrong, for the log
        for cmd in (["rc-status", "-a"], ["ip", "addr"], ["tail", "-n", "40", "/var/log/messages"]):
            print(f"--- {' '.join(cmd)}", flush=True)
            print(run(*cmd).stdout, flush=True)
    os.environ.setdefault("UNSEENET_HOME", str(media or "."))
    from .launcher import self_test as portable_self_test
    code = portable_self_test(network=bool(net))
    check("Tor starts" + (" and connects" if net else ""), code == 0, f"exit {code}")
    if code:                                  # Tor's own words
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            res = run("tor", "--DataDirectory", tmp, "--SocksPort", "auto", "--ControlPort",
                      "auto", "--Log", "notice stdout", timeout=15)
            print("--- tor\n" + (res.stdout + res.stderr)[-2500:], flush=True)
    print("UNSEENET-SELFTEST-" + ("OK" if ok else "FAILED"), flush=True)
    return 0 if ok else 1


# ----------------------------------------------------------------------
# The menu
# ----------------------------------------------------------------------

MENU_CSS = """
Screen { background: $surface; align: center top; }
#logo { color: $success; width: auto; margin: 1 0 0 0; }
#wordmark { color: $success; width: auto; margin: 1 0 0 0; }
#version { color: $text-muted; width: auto; }
#status { width: 72; height: auto; margin: 1 0; padding: 0 1; border: solid $primary-darken-2; }
#menu { width: 72; height: auto; max-height: 14; }
#hint { color: $text-muted; width: 72; }
ModalScreen { align: center middle; }
.dialog { width: 70; height: auto; max-height: 90%; border: thick $primary; background: $panel; padding: 1 2; }
.dialog Label { width: 100%; }
.dialog .title { text-style: bold; margin-bottom: 1; }
.dialog .buttons { height: auto; align-horizontal: right; margin-top: 1; }
.dialog Button { margin-left: 1; }
.dialog OptionList { height: auto; max-height: 14; }
"""

class Ask(ModalScreen):
    """A line of input (a passphrase, a time)."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, hint: str, password: bool = False, value: str = ""):
        super().__init__()
        self.title_, self.hint, self.password, self.value = title, hint, password, value

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_, classes="title")
            yield Label(self.hint)
            yield Input(value=self.value, password=self.password, id="answer")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("OK", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.dismiss(self.query_one(Input).value)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

class Pick(ModalScreen):
    """Choose one of a list (a keyboard layout, a Wi-Fi network)."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, hint: str, options: list[tuple[str, str]]):
        super().__init__()
        self.title_, self.hint, self.options = title, hint, options

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_, classes="title")
            yield Label(self.hint)
            yield OptionList(*[Option(text, id=key) for key, text in self.options])
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    @on(OptionList.OptionSelected)
    def _picked(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

ITEMS = [
    ("client", "Client        read and write - your vault is in data/ on this stick"),
    ("node", "Node          run a node from this stick"),
    ("monitor", "Monitor       how the node is doing"),
    ("wifi", "Wi-Fi         connect to a wireless network"),
    ("keyboard", "Keyboard      choose the keyboard layout"),
    ("clock", "Clock         Tor needs the right time"),
    ("update", "Update        a newer Unseenet onto this stick, keeping data/"),
    ("shell", "Shell         a command line (type 'exit' to come back)"),
    ("reboot", "Restart"),
    ("poweroff", "Shut down"),
]

# Screen lines the menu needs with the eye (12) and the wordmark (4) shown.
LOGO_NEEDS = 37
WORDMARK_NEEDS = 25


class BootMenu(App):
    CSS = MENU_CSS + console_css()
    TITLE = "Unseenet"
    BINDINGS = [Binding("ctrl+c", "noop", show=False)]

    def __init__(self) -> None:
        super().__init__()
        self.media = find_media()
        self.settings = load_settings(self.media)

    def compose(self) -> ComposeResult:
        yield Static(rich_icon(), id="logo")
        yield Static(WORDMARK, id="wordmark")
        yield Static(f"version {__version__}  -  discussion groups the old Usenet way, over Tor",
                     id="version")
        yield Static("", id="status")
        yield OptionList(*[Option(text, id=key) for key, text in ITEMS], id="menu")
        yield Static("Arrow keys and Enter.  Alt+F2: another console.  Alt+F3: system messages.",
                     id="hint")

    def on_mount(self) -> None:
        if self.settings.get("keymap"):
            load_keymap(self.settings["keymap"])
        if self.media is not None:
            writable(self.media)
        self.query_one("#menu", OptionList).focus()
        self.refresh_status()
        self.set_interval(5, self.refresh_status)
        self.fit(self.size.height)

    def on_resize(self, event) -> None:
        self.fit(event.size.height)

    def fit(self, height: int) -> None:
        """Leave out the eye, then the wordmark, on small screens (80x25 in safe mode)."""
        self.query_one("#logo").display = height >= LOGO_NEEDS
        self.query_one("#wordmark").display = height >= WORDMARK_NEEDS

    def action_noop(self) -> None:
        pass

    def refresh_status(self) -> None:
        net = addresses()
        vault = (self.media / "data" / "unseenet.vault") if self.media else None
        node = node_running()
        lines = [
            "Network:  " + (", ".join(f"{i} {a}" for i, a in net) if net
                            else "not connected - plug in a cable, or choose Wi-Fi"),
            "Data:     " + (f"{self.media}/data  ("
                            + ("your vault is there" if vault and vault.exists() else "no vault yet")
                            + ")" if self.media else "the UNSEENET partition was not found"),
            "Clock:    " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "Node:     " + (f"running (pid {node})" if node else "not running"),
            "Keyboard: " + self.settings.get("keymap", "us/us (default)"),
        ]
        self.query_one("#status", Static).update("\n".join(lines))

    def _env(self) -> dict:
        env = dict(os.environ)
        if self.media is not None:
            env["UNSEENET_HOME"] = str(self.media)
        return env

    def _run(self, *cmd: str) -> None:
        with self.suspend():
            os.system("clear")
            subprocess.run(list(cmd), env=self._env())
        self.refresh_status()

    @on(OptionList.OptionSelected, "#menu")
    def _chosen(self, event: OptionList.OptionSelected) -> None:
        getattr(self, f"do_{event.option.id}")()

    def do_client(self) -> None:
        if self.media is None or not writable(self.media):
            self.notify("data/ cannot be written; the client keeps nothing this time",
                        severity="warning")
        self._run("/opt/unseenet/bin/unseenet-tui")

    @work(exclusive=True, group="dialog")
    async def do_node(self) -> None:
        if node_running():
            stop = await self.push_screen_wait(Pick(
                "The node is running", "", [("monitor", "Show the monitor"),
                                            ("stop", "Stop the node")]))
            if stop == "stop":
                stop_node()
                self.notify("The node is stopping")
            elif stop == "monitor":
                self.do_monitor()
            self.refresh_status()
            return
        if self.media is None:
            self.notify("The UNSEENET partition was not found", severity="error")
            return
        first = not (node_dir(self.media) / "node_key.vault").exists()
        pw = await self.push_screen_wait(Ask(
            "Start the node", ("Choose a passphrase for the node's keys (it is asked at every start)."
                               if first else "The node's passphrase.")
            + f" Its data is in {node_dir(self.media)}, its settings in node.toml there.",
            password=True))
        if not pw:
            return
        self.notify("Starting the node and Tor ...")
        ok, msg = await self._in_thread(start_node, self.media, pw)
        self.notify(f"Node: {msg}", severity="information" if ok else "error", timeout=8)
        self.refresh_status()

    async def _in_thread(self, fn, *args):
        import asyncio
        return await asyncio.to_thread(fn, *args)

    def do_monitor(self) -> None:
        if not node_running():
            self.notify("Start the node first", severity="warning")
            return
        self._run("/opt/unseenet/bin/unseenet-monitor", "--node", NODE_SOCKET)

    @work(exclusive=True, group="dialog")
    async def do_wifi(self) -> None:
        devs = await self._in_thread(wifi_devices)
        if not devs:
            self.notify("No Wi-Fi device found (or its firmware is missing)", severity="warning")
            return
        dev = devs[0]
        self.notify(f"Looking for networks on {dev} ...")
        nets = await self._in_thread(wifi_networks, dev)
        if not nets:
            self.notify("No networks found", severity="warning")
            return
        choice = await self.push_screen_wait(Pick(
            "Wi-Fi", f"Networks seen by {dev}:",
            [(name, f"{'> ' if conn else '  '}{name:<32} {sec:<8} {sig}")
             for name, sec, sig, conn in nets]))
        if not choice:
            return
        security = next(sec for name, sec, _, _ in nets if name == choice)
        pw = None
        if security != "open":
            pw = await self.push_screen_wait(Ask(f"Connect to {choice}",
                                                 "The network's password.", password=True))
            if pw is None:
                return
        self.notify(f"Connecting to {choice} ...")
        ok, msg = await self._in_thread(wifi_connect, dev, choice, pw)
        self.notify(f"{choice}: {msg}", severity="information" if ok else "error", timeout=8)
        self.refresh_status()

    @work(exclusive=True, group="dialog")
    async def do_keyboard(self) -> None:
        maps = keymaps()
        if not maps:
            self.notify("No keyboard layouts on this system", severity="error")
            return
        choice = await self.push_screen_wait(Pick("Keyboard", "The layout of your keyboard:",
                                                  [(m, m.split("/")[1]) for m in maps]))
        if choice and load_keymap(choice):
            self.settings["keymap"] = choice
            save_settings(self.media, self.settings)
            self.notify(f"Keyboard: {choice}")
            self.refresh_status()

    @work(exclusive=True, group="dialog")
    async def do_clock(self) -> None:
        now = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
        value = await self.push_screen_wait(Ask(
            "Clock", "Tor refuses to work when the clock is hours wrong. Many computers keep "
            "local time; type the right time in UTC (Danish winter time minus 1 hour, summer "
            "time minus 2):", value=now))
        if value and value != now:
            res = run("date", "-u", "-s", value)
            self.notify("Clock set" if res.returncode == 0 else f"Not set: {res.stderr.strip()}",
                        severity="information" if res.returncode == 0 else "error")
        self.refresh_status()

    @work(exclusive=True, group="dialog")
    async def do_update(self) -> None:
        if self.media is None or not writable(self.media):
            self.notify("The stick cannot be written, so it cannot be updated", severity="error")
            return
        offline = sorted(self.media.glob("unseenet-*-update.zip"))
        options = [("stable", "Newest release (recommended)"),
                   ("dev", "Newest development build - may have bugs a release would not")]
        options += [(f"zip:{z.name}", f"From {z.name} on the stick") for z in offline]
        choice = await self.push_screen_wait(Pick(
            "Update", "Get a newer Unseenet onto this stick, over Tor. Your data/ (vault, "
            "node, settings) is kept. The computer restarts afterwards.", options))
        if not choice:
            return
        cmd = [sys.executable, "-m", "unseenet.update", "--media", str(self.media), "--reboot"]
        if choice.startswith("zip:"):
            cmd += ["--zip", str(self.media / choice[4:])]
        else:
            if not addresses():
                self.notify("Not connected: plug in a cable or choose Wi-Fi first",
                            severity="warning")
                return
            cmd += ["--channel", choice]
        self._run(*cmd, "--pause")

    def do_shell(self) -> None:
        self._run("/bin/sh", "-l")

    def do_reboot(self) -> None:
        stop_node()
        run("sync")
        run("reboot")

    def do_poweroff(self) -> None:
        stop_node()
        run("sync")
        run("poweroff")



def menu() -> None:
    BootMenu().run()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="unseenet-boot", description=__doc__.splitlines()[0])
    p.add_argument("--self-test", action="store_true", help="check the running system and exit")
    args = p.parse_args(argv)
    if args.self_test:
        sys.exit(self_test())
    menu()


if __name__ == "__main__":
    main()
