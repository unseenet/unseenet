"""Minimal Tor integration: launch tor, talk to its control port, open onion connections.

We deliberately do not depend on ``stem``: it no longer builds on current Python
versions, and the parts of the control protocol we need (AUTHENTICATE, ADD_ONION,
GETINFO) are a few lines of text. See the Tor control-spec for details.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from python_socks import ProxyError
from python_socks.async_.asyncio import Proxy


class TorError(RuntimeError):
    pass


LINUX_LOADERS = {"x86_64": "/lib64/ld-linux-x86-64.so.2", "aarch64": "/lib/ld-linux-aarch64.so.1"}


def launch_command(binary: str) -> tuple[list[str], dict[str, str]]:
    """How to run a program that may come from a portable build.

    - The Tor Expert Bundle ships its own libevent/OpenSSL next to ``tor``; they
      must be found before the system's (Linux, macOS).
    - A frozen (PyInstaller) client sets LD_LIBRARY_PATH to its own libraries;
      a child program must get the original back, not our OpenSSL.
    - On Linux, FAT-formatted USB sticks are often mounted without execute bits;
      the dynamic loader can still start the program.
    """
    env = dict(os.environ)
    folder = Path(binary).resolve().parent
    var = {"darwin": "DYLD_LIBRARY_PATH"}.get(sys.platform, "LD_LIBRARY_PATH")
    if getattr(sys, "frozen", False):
        original = env.pop(f"{var}_ORIG", None)
        if original is None:
            env.pop(var, None)
        else:
            env[var] = original
    if sys.platform != "win32" and any(folder.glob("libevent*")):
        env[var] = os.pathsep.join([str(folder)] + ([env[var]] if env.get(var) else []))
    argv = [str(binary)]
    if sys.platform.startswith("linux") and not os.access(binary, os.X_OK):
        loader = LINUX_LOADERS.get(platform.machine())
        if loader and os.path.exists(loader):
            argv = [loader, str(binary)]
    return argv, env


def builtin_bridges(binary: str, transport: str) -> list[str]:
    """The bridges that come with the Tor Expert Bundle (``pt_config.json``)."""
    config = Path(binary).resolve().parent / "pluggable_transports" / "pt_config.json"
    try:
        return list(json.loads(config.read_text())["bridges"][transport])
    except (OSError, ValueError, KeyError):
        return []


BRIDGE_MODES = ("off", "obfs4", "snowflake", "custom")


def bridges_for(setting: dict | None, binary: str) -> list[str] | None:
    """Bridge lines for a client's setting ``{"mode": ..., "custom": [...]}``, or None.

    ``obfs4`` and ``snowflake`` use the bridges that come with the portable
    builds; ``custom`` uses lines the user got from bridges.torproject.org.
    """
    mode = (setting or {}).get("mode", "off")
    if mode == "off":
        return None
    if mode == "custom":
        lines = [ln.strip() for ln in (setting or {}).get("custom", []) if ln.strip()]
        if not lines:
            raise TorError("no bridge lines given")
        return lines
    lines = builtin_bridges(binary, mode)
    if not lines:
        raise TorError(f"built-in {mode} bridges come with the portable builds; "
                       "use custom bridges with this Tor")
    return lines


def bridge_transports(lines: list[str]) -> set[str]:
    """The pluggable transports a list of bridge lines needs (empty for plain bridges)."""
    out = set()
    for line in lines:
        first = line.split()[0] if line.split() else ""
        if first and not first[0].isdigit() and not first.startswith("["):
            out.add(first)
    return out


class TorControl:
    """Async client for the Tor control protocol (subset)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        # One command at a time: replies carry no id, so two commands in flight
        # on the one connection would read each other's replies (issue #127).
        self._lock = asyncio.Lock()

    @classmethod
    async def connect(cls, host: str, port: int) -> "TorControl":
        return cls(*await asyncio.open_connection(host, port))

    async def command(self, line: str) -> list[str]:
        """Send one command and read its whole reply.

        Callers that put a timeout on this should wrap it in ``asyncio.shield``:
        cancelling it halfway leaves the rest of the reply unread on the
        connection, where the next command would read it as its own.
        """
        async with self._lock:
            return await self._command(line)

    async def _command(self, line: str) -> list[str]:
        self.writer.write(line.encode() + b"\r\n")
        await self.writer.drain()
        lines: list[str] = []
        while True:
            raw = (await self.reader.readline()).decode().rstrip("\r\n")
            if len(raw) < 4:
                raise TorError(f"short reply: {raw!r}")
            code, sep, text = raw[:3], raw[3], raw[4:]
            if sep == "+":  # data reply: read until "."
                while (data := (await self.reader.readline()).decode().rstrip("\r\n")) != ".":
                    text += "\n" + data
            lines.append(text)
            if not code.startswith("2"):
                raise TorError(f"{code} {text}")
            if sep == " ":
                return lines

    async def authenticate_cookie(self, cookie_path: Path) -> None:
        await self.command(f"AUTHENTICATE {cookie_path.read_bytes().hex()}")

    async def add_onion(self, key: str | None, virtual_port: int, target: str) -> tuple[str, str | None]:
        """Create an onion service. ``key`` is 'ED25519-V3:<b64>' or None for a new one.

        Returns (service_id, private_key_or_None). The key is handed to Tor over the
        control port only, so Tor never writes it to disk (UN-RFC 0007, section 3).
        """
        keyspec = key or "NEW:ED25519-V3"
        flags = "" if key is None else " Flags=DiscardPK"
        reply = await self.command(f"ADD_ONION {keyspec}{flags} Port={virtual_port},{target}")
        service_id = private = None
        for item in reply:
            if item.startswith("ServiceID="):
                service_id = item.split("=", 1)[1]
            elif item.startswith("PrivateKey="):
                private = item.split("=", 1)[1]
        if not service_id:
            raise TorError("ADD_ONION returned no ServiceID")
        return service_id + ".onion", private

    async def close(self) -> None:
        self.writer.close()


@dataclass
class TorProcess:
    """A private tor process with its data on a directory we control (e.g. the USB stick)."""

    data_dir: Path
    binary: str = "tor"
    bridges: list[str] | None = None     # bridge lines; none: connect to Tor directly
    process: asyncio.subprocess.Process | None = None
    socks_port: int = 0
    control: TorControl | None = None

    @staticmethod
    def find_binary(explicit: str | None = None) -> str:
        from ..portable import bundled_tor
        # a portable build uses the Tor it came with, so the version is the one we tested
        candidates = [explicit, os.environ.get("UNSEENET_TOR"), bundled_tor(), shutil.which("tor")]
        for c in candidates:
            if c and Path(c).exists():
                return str(c)
        raise TorError("tor binary not found; install tor or set UNSEENET_TOR")

    @staticmethod
    def binary_version(binary: str) -> str | None:
        """``Tor version ...`` if the binary runs here, else None."""
        argv, env = launch_command(binary)
        try:
            out = subprocess.run(argv + ["--version"], env=env, capture_output=True, text=True,
                                 timeout=30, cwd=Path(binary).resolve().parent)
        except (OSError, subprocess.SubprocessError):
            return None
        first = (out.stdout or "").strip().splitlines()
        return first[0] if out.returncode == 0 and first else None

    def _torrc(self) -> str:
        lines = ["# Written by Unseenet for this run; Tor gets the rest as options."]
        if self.bridges:
            folder = Path(self.binary).resolve().parent
            pt_dir = folder / "pluggable_transports"
            lyrebird = pt_dir / ("lyrebird.exe" if sys.platform == "win32" else "lyrebird")
            needed = bridge_transports(self.bridges)
            if needed and not lyrebird.exists():
                raise TorError("these bridges need pluggable transports (lyrebird), which come "
                               "with the portable builds; install obfs4proxy/lyrebird otherwise")
            if needed:
                # relative to Tor's working directory: paths on USB sticks often have spaces
                rel = os.path.relpath(lyrebird, folder)
                argv, _ = launch_command(str(lyrebird))
                exec_ = (f"{argv[0]} {rel}" if len(argv) > 1 else rel)
                lines.append("ClientTransportPlugin meek_lite,obfs2,obfs3,obfs4,scramblesuit,"
                             f"webtunnel,snowflake exec {exec_}")
            lines.append("UseBridges 1")
            lines += [f"Bridge {b.strip()}" for b in self.bridges if b.strip()]
        return "\n".join(lines) + "\n"

    async def start(self, timeout: float = 120) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        port_file = self.data_dir / "control_port"
        port_file.unlink(missing_ok=True)
        # Our own, empty torrc: never inherit the system's /etc/tor/torrc (e.g. Fedora's
        # ControlSocket in /run/tor, which a normal user cannot use).
        torrc = self.data_dir / "torrc"
        torrc.write_text(self._torrc())
        self.log_file = self.data_dir / "tor.log"
        argv, env = launch_command(self.binary)
        folder = Path(self.binary).resolve().parent
        geoip = [opt for name, flag in (("geoip", "--GeoIPFile"), ("geoip6", "--GeoIPv6File"))
                 if (folder / name).is_file() for opt in (flag, str(folder / name))]
        self.process = await asyncio.create_subprocess_exec(
            *argv,
            "-f", str(torrc),
            "--defaults-torrc", str(torrc),
            "--DataDirectory", str(self.data_dir),
            "--SocksPort", "auto",
            "--ControlPort", "auto",
            "--ControlPortWriteToFile", str(port_file),
            "--CookieAuthentication", "1",
            "--CookieAuthFile", str(self.data_dir / "control_auth_cookie"),
            "--Log", f"notice file {self.log_file}",
            "--AvoidDiskWrites", "1",
            *geoip,
            env=env, cwd=str(folder),
            # Never PIPE without reading it: a full pipe would eventually block Tor.
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        cookie = self.data_dir / "control_auth_cookie"
        # Tor writes the port file and the cookie separately; on Windows the
        # port file can come first. Wait for both, and for a complete port file.
        while not (port_file.exists() and cookie.exists()
                   and port_file.read_text().strip().startswith("PORT=")):
            if self.process.returncode is not None or loop.time() > deadline:
                raise TorError("tor failed to start" + self._log_tail())
            await asyncio.sleep(0.2)
        host, port = port_file.read_text().strip().split("=", 1)[1].rsplit(":", 1)
        if self.process.returncode is not None:
            raise TorError("tor exited during start" + self._log_tail())
        self.control = await TorControl.connect(host, int(port))
        await self.control.authenticate_cookie(self.data_dir / "control_auth_cookie")
        socks = (await self.control.command("GETINFO net/listeners/socks"))[0]
        self.socks_port = int(socks.split("=", 1)[1].strip('"').rsplit(":", 1)[1])
        while True:
            status = (await self.control.command("GETINFO status/bootstrap-phase"))[0]
            if "PROGRESS=100" in status:
                return
            if loop.time() > deadline:
                raise TorError("tor bootstrap timed out" + self._log_tail())
            await asyncio.sleep(1)

    def alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    def _log_tail(self, lines: int = 5) -> str:
        try:
            tail = self.log_file.read_text(errors="replace").splitlines()[-lines:]
        except (OSError, AttributeError):
            return ""
        return ":\n" + "\n".join(tail) if tail else ""

    async def stop(self) -> None:
        if self.control:
            await self.control.close()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            await self.process.wait()


# Tor's extended SOCKS5 replies for onion services (tor's doc/socks-extensions)
ONION_ERRORS = {
    0x01: "general failure in Tor (it may still be building circuits)",
    0x04: "host unreachable (the node may be down)",
    0x06: "timed out (the node may be down, or Tor is still starting)",
    0xF0: "the node's onion service was not found (down, or a wrong address)",
    0xF1: "the onion service descriptor is invalid",
    0xF2: "the onion service's introduction failed",
    0xF3: "the onion service's rendezvous failed",
    0xF4: "the onion service needs client authorization",
    0xF5: "wrong client authorization",
    0xF6: "this is not a valid onion address - check it for typos",
    0xF7: "the onion service introduction timed out",
}
PERMANENT_ONION_ERRORS = {0xF4, 0xF5, 0xF6}
ONION_RETRY_PAUSES = (3.0, 10.0)


# ---------------------------------------------------------------------------
# A Tor that is already running (Tails, Whonix, a system tor)
# ---------------------------------------------------------------------------
TOR_SOCKS_ENV = "UNSEENET_TOR_SOCKS"     # "9050", "127.0.0.1:9050", or "own"
TAILS_SOCKS = ("127.0.0.1", 9050)        # Tails' Tor; its firewall blocks any other


@dataclass(frozen=True)
class Socks:
    """The SOCKS port of a Tor that someone else runs.

    With ``isolate`` each destination gets its own SOCKS username, so Tor (which
    isolates streams by SOCKS username by default) gives each node its own circuit.
    ``source`` says where the setting came from, for the client to show.
    """
    host: str
    port: int
    source: str = ""
    isolate: bool = True

    def __str__(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"


def running_on_tails() -> bool:
    if Path("/etc/amnesia/version").exists():
        return True
    try:
        return 'NAME="Tails"' in Path("/etc/os-release").read_text()
    except OSError:
        return False


def parse_socks(value: str) -> tuple[str, int]:
    """``"9050"``, ``"127.0.0.1:9050"`` or ``"[::1]:9050"`` as (host, port).

    The host must be an IP address or ``localhost``: a name would be looked up
    outside Tor before Tor is even reached.
    """
    value = value.strip()
    host, sep, port = value.rpartition(":")
    if not sep:
        host, port = "127.0.0.1", value
    host = host.strip("[]") or "127.0.0.1"
    if host != "localhost":
        try:
            ipaddress.ip_address(host)
        except ValueError:
            raise TorError(f"Tor SOCKS address {value!r}: use an IP address, "
                           "e.g. 127.0.0.1:9050") from None
    if not port.isdigit() or not 0 < int(port) < 65536:
        raise TorError(f"Tor SOCKS address {value!r}: the port must be a number, e.g. 9050")
    return host, int(port)


def existing_tor(setting: dict | None) -> Socks | None:
    """The running Tor to use, or None to start our own.

    In order: ``UNSEENET_TOR_SOCKS``, the vault's ``tor.socks`` setting, then
    Tails (detected), where our own Tor could not reach the network anyway.
    ``"own"`` in either place always starts our own Tor; ``"auto"`` or nothing
    means "Tails' Tor on Tails, else our own".
    """
    for value, source in ((os.environ.get(TOR_SOCKS_ENV, ""), TOR_SOCKS_ENV),
                          ((setting or {}).get("socks", ""), "setting")):
        value = (value or "").strip()
        if value.lower() == "own":
            return None
        if value and value.lower() != "auto":
            return Socks(*parse_socks(value), source=source)
    if running_on_tails():
        return Socks(*TAILS_SOCKS, source="Tails")
    return None


async def check_socks(socks: Socks, timeout: float = 10) -> None:
    """Make sure a SOCKS5 server answers there (a greeting, nothing is sent onwards)."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(socks.host, socks.port), timeout)
    except (OSError, asyncio.TimeoutError) as exc:
        raise TorError(f"no Tor answers on {socks} ({socks.source}): "
                       f"{exc or 'timed out'}") from exc
    try:
        writer.write(b"\x05\x02\x00\x02")       # SOCKS5; no auth or username/password
        await writer.drain()
        reply = await asyncio.wait_for(reader.readexactly(2), timeout)
    except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as exc:
        raise TorError(f"{socks} ({socks.source}) does not answer like Tor's SOCKS port") from exc
    finally:
        writer.close()
    if reply[0] != 5 or reply[1] == 0xFF:
        raise TorError(f"{socks} ({socks.source}) is not a SOCKS5 port")


def _proxy_url(socks: int | Socks, dest_host: str) -> str:
    if isinstance(socks, int):
        return f"socks5://127.0.0.1:{socks}"
    auth = f"{quote('unseenet-' + dest_host, safe='')}:unseenet@" if socks.isolate else ""
    return f"socks5://{auth}{socks}"


async def open_connection(address: str, socks_port: int | Socks | None):
    """Open a stream to ``host:port``; .onion hosts go through Tor's SOCKS port.

    ``socks_port`` is our own Tor's port, or a :class:`Socks` of a Tor that is
    already running.

    Hostnames are resolved by Tor (remote DNS), never locally (UN-RFC 0005, section 1).
    """
    host, _, port = address.rpartition(":")
    if not host:
        host, port = address, "119"
    if host.endswith(".onion"):
        if not socks_port:
            raise TorError(f"Tor is required to reach {host}")
        proxy = Proxy.from_url(_proxy_url(socks_port, host), rdns=True)
        for attempt, pause in enumerate(ONION_RETRY_PAUSES + (None,)):
            try:
                sock = await proxy.connect(dest_host=host, dest_port=int(port))
                return await asyncio.open_connection(sock=sock)
            except ProxyError as exc:
                # A SOCKS refusal from Tor. Right after start Tor often has not
                # fetched the service's descriptor yet; a moment later it has.
                code = getattr(exc, "error_code", None)
                if pause is None or code in PERMANENT_ONION_ERRORS:
                    raise ConnectionError(f"Tor could not reach {host}: "
                                          f"{ONION_ERRORS.get(code, exc)}") from exc
                await asyncio.sleep(pause)
    return await asyncio.open_connection(host, int(port))


def temp_tor_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="unseenet-tor-"))
