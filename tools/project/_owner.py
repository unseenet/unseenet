"""Shared by the scripts in tools/project/: the project's owner vault, and posting.

The project key owns the project's groups (unseenet, unseenet.announce,
unseenet.nodes, unseenet.hierarchies, unseenet.names, ...). It is kept in an
encrypted vault (UN-RFC 0007) on the maintainer's own computer, by default
~/.unseenet/owner.vault, and never on GitHub or a node. These scripts ask for
its passphrase in the terminal; it is never put on a command line, in the
environment or in a file.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from unseenet.client.session import Session  # noqa: E402
from unseenet.core.tor import TorProcess  # noqa: E402
from unseenet.core.vault import Vault, VaultError  # noqa: E402
from unseenet.known_nodes import PROJECT_KEY, builtin_list  # noqa: E402
from unseenet.nntp import Client  # noqa: E402

VAULT = Path.home() / ".unseenet" / "owner.vault"
POW_BITS = 22                               # postage on the project's manifests
FP = "ph5fc5hop5232qsz"                     # the project key's fingerprint


def open_owner_session(path: Path = VAULT, project_key: str | None = None) -> Session:
    """Ask for the passphrase and open the owner vault; check it holds the project key."""
    project_key = project_key or PROJECT_KEY
    try:
        vault = Vault.open(path, getpass.getpass(f"Passphrase for {path}: "))
    except VaultError as exc:
        sys.exit(f"Cannot open the vault: {exc}")
    s = Session(vault, status=lambda *_: None)
    if s.identity().key_text != project_key:
        sys.exit(f"This vault's identity is {s.identity().key_text}, not the project key.")
    return s


async def post_everywhere(raws: list[bytes], addresses: list[str] | None = None) -> int:
    """Post every article to every node that answers, over Tor.

    Returns how many nodes took all of them; the nodes replicate to each other
    anyway, so one node being down does not matter.
    """
    addresses = addresses or [n.address for n in builtin_list()[1]]
    ok = 0
    with tempfile.TemporaryDirectory(prefix="unseenet-owner-") as tmp:
        tor = TorProcess(Path(tmp), TorProcess.find_binary())
        print("Starting Tor ...", flush=True)
        await tor.start(timeout=180)
        try:
            for address in addresses:
                try:
                    c = await asyncio.wait_for(Client.connect(address, tor.socks_port), 120)
                    took = 0
                    for raw in raws:
                        code, text = await c.post(raw)
                        took += code == 240 or "duplicate" in text
                        print(f"  {address[:16]}...: {code} {text}", flush=True)
                    await c.quit()
                    ok += took == len(raws)
                except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
                    print(f"  {address[:16]}...: not reached ({exc})", flush=True)
        finally:
            await tor.stop()
    return ok
