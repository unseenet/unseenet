"""Minimal Tor integration: launch tor, talk to its control port, open onion connections.

We deliberately do not depend on ``stem``: it no longer builds on current Python
versions, and the parts of the control protocol we need (AUTHENTICATE, ADD_ONION,
GETINFO) are a few lines of text. See the Tor control-spec for details.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from python_socks.async_.asyncio import Proxy


class TorError(RuntimeError):
    pass


class TorControl:
    """Async client for the Tor control protocol (subset)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer

    @classmethod
    async def connect(cls, host: str, port: int) -> "TorControl":
        return cls(*await asyncio.open_connection(host, port))

    async def command(self, line: str) -> list[str]:
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

    async def start(self, timeout: float = 120) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        port_file = self.data_dir / "control_port"
        port_file.unlink(missing_ok=True)
        # Our own, empty torrc: never inherit the system's /etc/tor/torrc (e.g. Fedora's
        # ControlSocket in /run/tor, which a normal user cannot use).
        torrc = self.data_dir / "torrc"
        torrc.write_text("# Unseenet runs Tor with command-line options only.\n")
        self.log_file = self.data_dir / "tor.log"
        self.process = await asyncio.create_subprocess_exec(
            self.binary,
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
            # Never PIPE without reading it: a full pipe would eventually block Tor.
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not port_file.exists():
            if self.process.returncode is not None or loop.time() > deadline:
                raise TorError("tor failed to start" + self._log_tail())
            await asyncio.sleep(0.2)
        host, port = port_file.read_text().strip().split("=", 1)[1].rsplit(":", 1)
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


async def open_connection(address: str, socks_port: int | None):
    """Open a stream to ``host:port``; .onion hosts go through Tor's SOCKS port.

    Hostnames are resolved by Tor (remote DNS), never locally (UN-RFC 0005, section 1).
    """
    host, _, port = address.rpartition(":")
    if not host:
        host, port = address, "119"
    if host.endswith(".onion"):
        if not socks_port:
            raise TorError(f"Tor is required to reach {host}")
        proxy = Proxy.from_url(f"socks5://127.0.0.1:{socks_port}", rdns=True)
        sock = await proxy.connect(dest_host=host, dest_port=int(port))
        return await asyncio.open_connection(sock=sock)
    return await asyncio.open_connection(host, int(port))


def temp_tor_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="unseenet-tor-"))
