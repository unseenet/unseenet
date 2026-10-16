#!/usr/bin/env python3
"""Screenshots of unseenet-tui for the documentation (docs/img/client-*.svg).

Starts a node on this machine (no Tor), fills it with a few groups, posts
and a private message from made-up people, and then drives the client the
way the tests do, saving a screenshot of each screen. Nothing touches your
own vault or the network.

    python tools/docs_screenshots.py            # writes docs/img/client-*.svg
    python tools/docs_screenshots.py OUT_DIR

Run it again when the client's look changes, and commit the SVG files.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

os.environ["UNSEENET_PASSPHRASE"] = "screenshots"
os.environ["UNSEENET_INSECURE_FAST_KDF"] = "1"

import unseenet.client.session as sess  # noqa: E402
from unseenet.client.session import Session  # noqa: E402
from unseenet.client.tui import (BrowseDialog, ComposeDialog, GroupInfoDialog,  # noqa: E402
                                 NamesDialog, NodesDialog, ReadScreen, UnseenetApp)
from unseenet.core.store import Store  # noqa: E402
from unseenet.core.vault import Vault  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}
ONION = "k3qx…7tid.onion"
SIZE = (120, 34)
sess.DEFAULT_POW = 10


def person(tmp: Path, nick: str, name: str, addr: str) -> Session:
    s = Session(Vault.open(tmp / f"{nick}.vault", "screenshots", **KDF), status=lambda *_: None)
    s.new_identity(nick, name)
    s.add_node(addr)
    s.data["starter_groups"] = True       # the project's groups are not on this node
    return s


async def fill(tmp: Path, addr: str) -> tuple[Path, dict[str, str]]:
    """Groups, posts and a private message from three made-up people."""
    me = person(tmp, "andreas", "Andreas", addr)
    sonia = person(tmp, "sonia", "Sonia", addr)
    mikkel = person(tmp, "mikkel", "Mikkel", addr)
    await me.ensure_inbox()

    snak = await mikkel.create_group("dk.snak", "open", title="Small talk, in Danish or English",
                                     description="About everything and nothing", min_pow=10)
    q = await mikkel.post(snak, "Unseenet from a USB stick?",
                          "Has anyone tried the portable client on a library computer?\n"
                          "Does it really leave nothing behind?\n")
    r = await sonia.post(snak, "Re: Unseenet from a USB stick?",
                         "> Has anyone tried the portable client on a library computer?\n\n"
                         "Yes, on Windows. Your vault stays on the stick, encrypted.\n"
                         "Boot the stick instead if you want nothing on the computer.\n",
                         references=[q])
    await me.post(snak, "Re: Unseenet from a USB stick?",
                  "> Boot the stick instead if you want nothing on the computer.\n\n"
                  "And the bootable stick runs from memory, so it can't write to the disk\n"
                  "even by accident.\n", references=[q, r])
    n = await mikkel.post(snak, "Which newsreader do you use?",
                          "tin works with Unseenet too, through the local proxy.\n")
    await sonia.post(snak, "Re: Which newsreader do you use?",
                     "Just unseenet-tui. The chat view is nice for small groups.\n", references=[n])
    await sonia.post(snak, "Weekend plans", "Anyone going to the scout camp?\n")

    marsvin = await sonia.create_group("dk.snak.marsvin", "open", title="Guinea pigs",
                                       description="Pictures, care and stories", min_pow=10,
                                       rules="Be kind. Guinea pigs only.")
    await sonia.post(marsvin, "Our new guinea pig", "Her name is Kaj. She eats everything.\n")

    chat = await mikkel.create_group("dk.snak.chat", "open", view="chat", low_latency=True,
                                      title="Quick chat", min_pow=10)
    await mikkel.post(chat, "chat", "Anyone around?\n")
    await sonia.post(chat, "chat", "Yes! Just set up a node on the Raspberry Pi\n")
    await me.post(chat, "chat", "Nice - send me its onion address and I'll peer with it\n")
    await mikkel.post(chat, "chat", "Same here\n")

    radio = await me.create_group("alt.radio.hams", "open", title="Amateur radio", min_pow=10)
    await me.post(radio, "QSL cards", "Who still sends paper QSL cards?\n")

    await sonia.send_private(me.my_inbox, "Dinner on Sunday?",
                             "Mum asks if you come for dinner on Sunday. Bring the dog.\n")

    for gid in (snak, marsvin, chat, radio):
        me.subscribe(gid)
    me.add_contact(sonia.identity().key_text, "Sonia")
    for gid in (snak, marsvin, chat, radio):
        await me.fetch_group(gid)
        me.mark_rules_seen(gid)
    me.data.setdefault("views", {})[chat] = "chat"
    me.save()
    for s in (me, sonia, mikkel):
        await s.close()
    return tmp / "andreas.vault", {"snak": snak, "chat": chat, "marsvin": marsvin}


async def wait_for(pilot, cond, tries=300) -> bool:
    for _ in range(tries):
        if cond():
            return True
        await pilot.pause(0.05)
    return False


async def shoot(vault: Path, groups: dict[str, str], out: Path) -> list[Path]:
    app = UnseenetApp(vault)
    saved: list[Path] = []

    async def save(name: str) -> None:
        await pilot.pause(0.6)
        path = out / f"client-{name}.svg"
        svg = app.export_screenshot(title="unseenet-tui")
        # The node runs on 127.0.0.1 here; show an onion address of the same width
        svg = re.sub(r"127\.0\.0\.1:(\d+)",
                     lambda m: ONION[:len(m.group(0)) - 1] + "…" if len(m.group(0)) < len(ONION)
                     else ONION.ljust(len(m.group(0))), svg)
        path.write_text(svg, encoding="utf-8")
        saved.append(path)

    async def close() -> None:
        await pilot.press("escape")
        await pilot.pause(0.3)

    async with app.run_test(size=SIZE) as pilot:
        assert await wait_for(pilot, lambda: app.session is not None
                              and all(g in app.groups for g in groups.values())), "no groups"
        # The main window: groups, threads, the selected post
        app.select_group(groups["snak"])
        assert await wait_for(pilot, lambda: len(app.messages) >= 6), "no posts"
        app.query_one("#threads").focus()
        await pilot.press("down")
        await save("main")

        # Reading a post on the whole screen
        await pilot.press("f")
        assert await wait_for(pilot, lambda: isinstance(app.screen, ReadScreen))
        await save("read")
        await close()

        # Writing a reply
        await pilot.press("r")
        assert await wait_for(pilot, lambda: isinstance(app.screen, ComposeDialog))
        await pilot.press(*"Thanks, I'll try it on Saturday.")
        await save("compose")
        await close()

        # About the group (?)
        app.select_group(groups["marsvin"])
        await pilot.pause(0.5)
        app.query_one("#threads").focus()
        await pilot.press("question_mark")
        assert await wait_for(pilot, lambda: isinstance(app.screen, GroupInfoDialog))
        await save("group-info")
        await close()

        # A chat group
        app.select_group(groups["chat"])
        assert await wait_for(pilot, lambda: len(app.messages) >= 4), "no chat"
        await save("chat")
        await pilot.press("escape")             # leave the input line, letters are keys again

        # Browsing the groups on the node (g)
        await pilot.press("g")
        assert await wait_for(pilot, lambda: isinstance(app.screen, BrowseDialog))
        await pilot.pause(1.0)
        await save("browse")
        await close()

        # Names (@), nodes (o) and the command palette (Ctrl+P)
        app.action_names()
        assert await wait_for(pilot, lambda: isinstance(app.screen, NamesDialog))
        await save("names")
        await close()
        app.action_node_info()
        assert await wait_for(pilot, lambda: isinstance(app.screen, NodesDialog))
        await save("nodes")
        await close()
        await pilot.press("ctrl+p")
        await pilot.pause(0.5)
        await save("palette")
        await close()
        await pilot.press("q")
    return saved


async def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "img"
    out.mkdir(parents=True, exist_ok=True)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), name="node1"))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    with tempfile.TemporaryDirectory(prefix="unseenet-shots-") as tmp:
        vault, groups = await fill(Path(tmp), addr)
        for path in await shoot(vault, groups, out):
            print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
    server.close()


if __name__ == "__main__":
    asyncio.run(main())
