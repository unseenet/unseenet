"""One program for the portable builds: ``unseenet`` starts the terminal client.

    unseenet                     the terminal client (TUI)
    unseenet --vault FILE        the TUI with another vault
    unseenet cli <command> ...   the command-line client (unseenet --help there)
    unseenet node ...            run a node (unusual on a USB stick, but possible)
    unseenet --self-test         check this build: finds Tor, starts it, reaches the network
             [--offline]         ... without the network
             [--node ADDRESS]    ... and talks to a node over Tor
    unseenet --version
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from . import __version__


def self_test(network: bool = True, node: str | None = None) -> int:
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
                print("Tor connected.")
                if node:
                    from .nntp import Client
                    print(f"Reaching node {node} over Tor ...")
                    client = await asyncio.wait_for(Client.connect(node, tor.socks_port), 120)
                    caps = await client.fetch_capabilities()
                    groups = await client.multiline("LIST NEWSGROUPS *", 215)
                    await client.quit()
                    print(f"Node answers: {caps[0] if caps else '?'}, {len(groups)} groups.")
            except TorError as exc:
                print(f"Tor did not connect: {exc}")
                return 2
            except (OSError, ConnectionError, asyncio.TimeoutError) as exc:
                print(f"Could not reach the node: {exc}")
                return 3
            finally:
                await tor.stop()
        print("This build works.")
        return 0
    return asyncio.run(run())


def _clean_after_update() -> None:
    """Windows: delete the programs an update had to move aside while they ran."""
    if sys.platform != "win32":
        return
    from .portable import portable_root
    root = portable_root()
    if root is not None:
        from .update import clean_old
        clean_old(root)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    _clean_after_update()
    if args[:1] == ["cli"]:
        from .cli import client_main
        client_main(args[1:])
    elif args[:1] == ["update"]:
        from .update import main as update_main
        update_main(args[1:])
    elif args[:1] == ["node"]:
        from .cli import node_main
        node_main(args[1:])
    elif args[:1] == ["--self-test"]:
        node = args[args.index("--node") + 1] if "--node" in args[:-1] else None
        sys.exit(self_test(network="--offline" not in args, node=node))
    elif args[:1] in (["--help"], ["-h"]):
        print(__doc__)
    elif args[:1] == ["--version"]:
        print(f"unseenet {__version__}")
    else:
        from .client.tui import main as tui_main
        tui_main(args)


if __name__ == "__main__":
    main()
