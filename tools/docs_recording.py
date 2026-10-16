#!/usr/bin/env python3
"""A screen recording of unseenet-tui for the documentation (docs/img/demo.cast).

Starts a node on this machine (no Tor), fills it with the same made-up groups,
posts and people as tools/docs_screenshots.py, and then runs the real client
in a pseudo-terminal, typing into it like a person would. Everything the
client draws is saved as an asciicast (asciinema's format), which the docs
play with the bundled player. ``--gif`` also renders an animated GIF with
agg (https://github.com/asciinema/agg), for the README and announcements.

    python tools/docs_recording.py                     # docs/img/demo.cast
    python tools/docs_recording.py --gif docs/img/demo.gif
    python tools/docs_recording.py --debug             # print the screen after each step

Needs ``pip install pexpect`` (and ``pyte`` for --debug). Nothing touches
your own vault or the network. The client talks to the local node directly,
so the recording leaves out Tor starting, which takes 10-30 seconds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import docs_screenshots as shots  # noqa: E402  (sets the screenshot passphrase and fast KDF)
from unseenet.core.store import Store  # noqa: E402
from unseenet.node.server import Node, NodeConfig  # noqa: E402

COLS, ROWS = 120, 34
ONION = "k3qxv7tid.onion"
PASSPHRASE = shots.os.environ["UNSEENET_PASSPHRASE"]

DOWN, UP, ENTER, ESC, TAB = "\x1b[B", "\x1b[A", "\r", "\x1b", "\t"
CTRL_P, CTRL_S, SHIFT_TAB = "\x10", "\x13", "\x1b[Z"

# What the recording shows: (seconds to wait first, keys, typed?)
# "typed" sends the text a character at a time, like a person typing.
SCRIPT: list[tuple[float, str, bool]] = [
    (2.0, PASSPHRASE, True),     # unlock the vault
    (0.6, ENTER, False),
    (3.5, DOWN, False),          # down the list of groups ...
    (0.5, DOWN, False),
    (0.5, DOWN, False),
    (0.5, DOWN, False),
    (0.5, DOWN, False),
    (0.8, ENTER, False),         # ... and open dk.snak
    (2.5, DOWN, False),          # down to Sonia's answer about USB sticks
    (0.7, DOWN, False),
    (0.7, DOWN, False),
    (1.2, DOWN, False),
    (2.0, "f", False),           # read it on the whole screen
    (3.5, ESC, False),
    (1.0, "r", False),           # write a reply
    (1.2, "Thanks - I'll try it on the library computer on Saturday.", True),
    (1.5, CTRL_S, False),
    (4.0, SHIFT_TAB, False),     # over to the chat group
    (0.8, DOWN, False),
    (0.8, ENTER, False),
    (2.0, "Hi all - just found this group!", True),
    (0.6, ENTER, False),
    (3.0, ESC, False),
    (1.0, "g", False),           # browse the groups on the node
    (3.0, ESC, False),
    (1.0, CTRL_P, False),        # the command palette
    (1.0, "moder", True),
    (2.5, ESC, False),
]


class Recorder:
    """Reads a child's output and keeps it as timed asciicast events."""

    def __init__(self, child, debug: bool):
        self.child, self.events, self.start = child, [], time.monotonic()
        self.stopped = False          # set before the client is stopped: its goodbye is not shown
        self.screen = self.stream = None
        if debug:
            import pyte
            self.screen = pyte.Screen(COLS, ROWS)
            self.stream = pyte.ByteStream(self.screen)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        while True:
            try:
                data = self.child.read_nonblocking(65536, timeout=0.2)
            except Exception as exc:  # noqa: BLE001  - pexpect.TIMEOUT or EOF
                if type(exc).__name__ == "TIMEOUT":
                    continue
                return
            if self.stopped:
                return
            self.events.append((time.monotonic() - self.start, data))
            if self.stream:
                self.stream.feed(data)

    def dump(self, label: str) -> None:
        if self.screen:
            print(f"----- {label}")
            print("\n".join(line.rstrip() for line in self.screen.display))


def serve_node() -> tuple[str, asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    ready: dict[str, str] = {}

    async def start() -> None:
        node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), name="node1"))
        server = await node.serve("127.0.0.1", 0)
        ready["addr"] = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(start())
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    while "addr" not in ready:
        time.sleep(0.05)
    return ready["addr"], loop


def to_cast(events: list[tuple[float, bytes]], addr: str, prompt: str) -> list[str]:
    """Asciicast v2 lines. Merges output that arrives within 20 ms, shows the
    local node as an onion address, and starts with the command being typed."""
    host = re.escape(addr)
    fake = (ONION + " " * len(addr))[:len(addr)]   # same width, so nothing moves
    header = {"version": 2, "width": COLS, "height": ROWS,
              "title": "Unseenet - the terminal client",
              "env": {"TERM": "xterm-256color", "SHELL": "/bin/sh"}}
    lines = [json.dumps(header)]
    t = 0.3
    lines.append(json.dumps([t, "o", prompt]))
    for ch in "sh start-linux.sh":
        t += 0.09
        lines.append(json.dumps([round(t, 3), "o", ch]))
    t += 0.5
    lines.append(json.dumps([round(t, 3), "o", "\r\n"]))
    offset = t + 0.3
    merged: list[tuple[float, bytes]] = []
    for at, data in events:
        if merged and at - merged[-1][0] < 0.02:
            merged[-1] = (merged[-1][0], merged[-1][1] + data)
        else:
            merged.append((at, data))
    for at, data in merged:
        text = re.sub(host, fake, data.decode("utf-8", "replace"))
        lines.append(json.dumps([round(at + offset, 3), "o", text]))
    return lines


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default=str(ROOT / "docs" / "img" / "demo.cast"))
    p.add_argument("--gif", help="also render an animated GIF here (needs agg)")
    p.add_argument("--home", help="the portable folder to show (default: a temporary 'Unseenet')")
    p.add_argument("--debug", action="store_true", help="print the screen after each step")
    args = p.parse_args()

    import pexpect

    addr, loop = serve_node()
    with tempfile.TemporaryDirectory(prefix="unseenet-rec-") as tmp:
        vault, _groups = asyncio.run_coroutine_threadsafe(shots.fill(Path(tmp), addr), loop).result()
        home = Path(args.home) if args.home else Path(tmp) / "Unseenet"
        (home / "data").mkdir(parents=True, exist_ok=True)
        target = home / "data" / "unseenet.vault"
        shutil.copy(vault, target)

        env = {k: v for k, v in os.environ.items() if k != "UNSEENET_PASSPHRASE"}
        env.update(TERM="xterm-256color", COLORTERM="truecolor", UNSEENET_INSECURE_FAST_KDF="1",
                   UNSEENET_HOME=str(home), PYTHONPATH=str(ROOT / "src"))
        child = pexpect.spawn(sys.executable, ["-m", "unseenet.client.tui", "--vault", str(target)],
                              env=env, cwd=str(home), dimensions=(ROWS, COLS))
        rec = Recorder(child, args.debug)
        for i, (wait, keys, typed) in enumerate(SCRIPT):
            time.sleep(wait)
            rec.dump(f"before step {i}: {keys!r}")
            if typed:
                for ch in keys:
                    child.send(ch)
                    time.sleep(0.07)
            else:
                child.send(keys)
        time.sleep(1.5)
        rec.dump("end")
        rec.stopped = True
        child.terminate(force=True)
        rec.thread.join(timeout=2)

    prompt = f"\x1b[32m{home.parent.name if args.home else 'usb'}\x1b[0m:\x1b[34m{home.name}\x1b[0m$ "
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(to_cast(rec.events, addr, prompt)) + "\n", encoding="utf-8")
    print(out)
    if args.gif:
        agg = shutil.which("agg") or "agg"
        subprocess.run([agg, "--font-family", "Fira Code,DejaVu Sans Mono", "--font-size", "14",
                        "--theme", "monokai", "--idle-time-limit", "2", "--last-frame-duration", "3",
                        str(out), args.gif], check=True)
        print(args.gif)


if __name__ == "__main__":
    main()
