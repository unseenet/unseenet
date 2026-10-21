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
from unseenet.core.article import Article, ArticleError  # noqa: E402
from unseenet.core.groups import Manifest  # noqa: E402
from unseenet.core.tor import TorProcess  # noqa: E402
from unseenet.core.vault import Vault, VaultError  # noqa: E402
from unseenet.known_nodes import PROJECT_KEY, builtin_list  # noqa: E402
from unseenet.nntp import Client, NNTPError  # noqa: E402

VAULT = Path.home() / ".unseenet" / "owner.vault"
POW_BITS = 22                               # postage on the project's manifests
FP = "ph5fc5hop5232qsz"                     # the project key's fingerprint


async def _post_with_session(s: Session, arts: list[Article], addresses: list[str],
                             others=()) -> int:
    from unseenet.client.session import SessionError
    from unseenet.core import crypto
    signers = {s.identity().key_text: (s, s.identity())}
    for ident in others:                     # their own session each: their own ripening
        state = VAULT.parent / "keys" / f"{crypto.fingerprint(ident.public_key)}.state.json"
        signers[ident.key_text] = (Session.from_key(ident, state, status=lambda *_: None), ident)
    ok = 0
    for address in addresses:
        took = 0
        for art in arts:
            who, key = signers.get(crypto.key_to_text(art.author_key), (None, None))
            if who is None:
                print(f"  {art.message_id}: signed by a key not given here; skipped", flush=True)
                continue
            try:
                await who.post_article(art, node=address, sign_with=key)
                took += 1
                print(f"  {address[:16]}...: 240 {art.message_id}", flush=True)
            except SessionError as exc:
                took += "duplicate" in str(exc)
                print(f"  {address[:16]}...: {exc}", flush=True)
            except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
                print(f"  {address[:16]}...: not reached ({exc})", flush=True)
                break
        ok += took == len(arts)
    for who, _ in signers.values():
        await who.close()
    return ok


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


async def read_manifests(c: Client, group_ids: list[str]) -> dict[str, dict]:
    """The newest valid manifest (UN-RFC 0004 section 4) of each group one node has."""
    found: dict[str, dict] = {}
    for gid in group_ids:
        try:
            _, low, high = await c.group(gid)
        except (NNTPError, OSError, ConnectionError, ValueError, asyncio.IncompleteReadError):
            continue
        if high < low:
            continue
        # Ask which articles are manifests (one HDR) and fetch only those, instead
        # of every post in the group, one round trip over Tor each (#170).
        try:
            lines = await c.multiline(f"HDR Control {low}-{high}", 225)
            numbers = [ln.split(" ", 1)[0] for ln in lines
                       if ln.partition(" ")[2].strip().lower().startswith("manifest")]
        except (NNTPError, OSError, ConnectionError, ValueError, asyncio.IncompleteReadError):
            numbers = [str(n) for n in range(low, high + 1)]   # a node without HDR
        for n in numbers:
            raw = await c.article(n)
            if not raw:
                continue
            try:
                art = Article.from_bytes(raw)
                if art.control != ["manifest"]:
                    continue
                m = Manifest.from_article(art)
            except (ArticleError, ValueError):
                continue
            if m.group_id == gid and m.serial > int(found.get(gid, {}).get("serial", 0)):
                found[gid] = dict(m.raw)
    return found


async def fetch_manifests(group_ids: list[str], addresses: list[str] | None = None) -> dict[str, dict]:
    """The newest valid manifest of each group on any of the project's nodes, over Tor.

    Signatures and owners are checked here, so a node cannot hand us someone
    else's manifest; taking the highest serial means a new one always follows it.
    """
    addresses = addresses or [n.address for n in builtin_list()[1]]
    best: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="unseenet-owner-") as tmp:
        tor = TorProcess(Path(tmp), TorProcess.find_binary())
        print("Starting Tor to read the groups' manifests ...", flush=True)
        await tor.start(timeout=180)
        try:
            for address in addresses:
                try:
                    c = await asyncio.wait_for(Client.connect(address, tor.socks_port), 120)
                    got = await asyncio.wait_for(read_manifests(c, group_ids), 600)
                    await c.quit()
                except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
                    print(f"  {address[:16]}...: not reached ({exc})", flush=True)
                    continue
                print(f"  {address[:16]}...: {len(got)} manifests", flush=True)
                for gid, data in got.items():
                    if int(data["serial"]) > int(best.get(gid, {}).get("serial", 0)):
                        best[gid] = data
        finally:
            await tor.stop()
    return best


async def post_everywhere(raws: list, addresses: list[str] | None = None,
                          session: Session | None = None, others=()) -> int:
    """Post every article to every node that answers, over Tor.

    With ``session`` (the owner session), ``raws`` are Articles, posted through
    ``Session.post_article`` and signed with the project key: postage and key
    ripening (UN-RFC 0025) are then the same code as everywhere (#287). Without
    it, raw signed articles are posted as they are (nodes from before 0025 only).
    ``others``: further keys (e.g. the registrar's claim inbox key) whose articles
    are among ``raws``; each posts through a session of its own, with its own
    ripening kept in ~/.unseenet/keys.

    Returns how many nodes took all of them; the nodes replicate to each other
    anyway, so one node being down does not matter.
    """
    addresses = addresses or [n.address for n in builtin_list()[1]]
    if session is not None:
        return await _post_with_session(session, raws, addresses, others)
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
