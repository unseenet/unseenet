"""One program for the portable builds: ``unseenet`` starts the terminal client.

    unseenet                     the terminal client (TUI)
    unseenet --vault FILE        the TUI with another vault
    unseenet cli <command> ...   the command-line client (unseenet --help there)
    unseenet node ...            run a node (unusual on a USB stick, but possible)
    unseenet --self-test         check this build: finds Tor, starts it, reaches the network
    unseenet --version
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from . import __version__


def self_test(network: bool = True) -> int:
    """Print what this build will use, and try to start Tor. Returns an exit code."""
    from . import portable
    from .core.tor import TorError, TorProcess

    root = portable.portable_root()
    print(f"Unseenet {__version__}, Python {sys.version.split()[0]} on {sys.platform}")
    try:   # everything the client loads, so a build missing a part fails here
        import nacl.bindings  # noqa: F401
        from .cli import client_main  # noqa: F401
        from .client import tui  # noqa: F401
        from .core import crypto
        crypto.Identity.generate()
    except Exception as exc:  # noqa: BLE001
        print(f"Parts:     BROKEN ({type(exc).__name__}: {exc})")
        return 1
    print("Parts:     client, terminal UI and cryptography load")
    print(f"Program:   {portable.program_dir()}")
    print(f"Portable:  {root if root else 'no (files go in the current directory)'}")
    print(f"Vault:     {portable.default_vault_path().resolve()}")
    try:
        binary = TorProcess.find_binary()
    except TorError as exc:
        print(f"Tor:       NOT FOUND ({exc})")
        return 1
    print(f"Tor:       {binary}")
    version = TorProcess.binary_version(binary)
    print(f"           {version or 'does not run'}")
    if not version:
        return 1
    if not network:
        return 0
    print("Starting Tor and connecting to the Tor network (up to two minutes) ...")

    async def run() -> int:
        with tempfile.TemporaryDirectory(prefix="unseenet-selftest-") as tmp:
            tor = TorProcess(Path(tmp), binary)
            try:
                await tor.start(timeout=120)
            except TorError as exc:
                print(f"Tor did not connect: {exc}")
                return 2
            finally:
                await tor.stop()
        print("Tor connected. This build works.")
        return 0
    return asyncio.run(run())


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["cli"]:
        from .cli import client_main
        client_main(args[1:])
    elif args[:1] == ["node"]:
        from .cli import node_main
        node_main(args[1:])
    elif args[:1] == ["--self-test"]:
        sys.exit(self_test(network="--offline" not in args))
    elif args[:1] in (["--help"], ["-h"]):
        print(__doc__)
    elif args[:1] == ["--version"]:
        print(f"unseenet {__version__}")
    else:
        from .client.tui import main as tui_main
        tui_main(args)


if __name__ == "__main__":
    main()
