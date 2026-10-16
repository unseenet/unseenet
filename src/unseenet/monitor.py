"""unseenet-monitor: how your Unseenet node is doing, at a glance.

A program of its own: it only reads the node's local stats interface (see
``unseenet.node.stats``) and cannot change anything. The node runs on whether
the monitor is open or not.

    unseenet-monitor                          the node in ./node-data, or the usual places
    unseenet-monitor --node /home/unseenet/node-data/monitor.sock
    unseenet-monitor --node a.sock --node b.sock     several nodes: n / p to switch

The socket belongs to the node's user, so run it as that user, e.g.
``sudo -u unseenet unseenet-monitor``.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (DataTable, Footer, Header, Label, RichLog, Sparkline, Static,
                             TabbedContent, TabPane)

from . import __version__
from .console import console_css
from .node.stats import fetch

REFRESH = 2.0
PLACES = ["node-data/monitor.sock", "~/node-data/monitor.sock",
          "/home/unseenet/node-data/monitor.sock", "/var/lib/unseenet/monitor.sock"]

CSS = """
Screen { background: $surface; }
#top { height: auto; }
#node { width: 1fr; height: auto; padding: 0 1; border: solid $primary-darken-2; }
#traffic { width: 1fr; height: auto; padding: 0 1; border: solid $primary-darken-2; }
.spark-row { height: 1; }
.spark-label { width: 9; }
.spark-count { width: 12; text-align: right; }
Sparkline { width: 1fr; height: 1; }
#warnings { height: auto; padding: 0 1; color: $warning; }
#warnings.ok { color: $success; }
TabbedContent { height: 1fr; }
DataTable { height: 1fr; }
RichLog { height: 1fr; }
#status { height: 1; background: $boost; color: $text-muted; padding: 0 1; }
"""


def ago(t: float | None, now: float | None = None) -> str:
    if not t:
        return "never"
    s = int((now or time.time()) - t)
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60}m ago"
    return f"{s // 86400}d ago"


def duration(seconds: float) -> str:
    s = int(seconds)
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return f"{d}d {h}h {m}m" if d else f"{h}h {m}m" if h else f"{m}m {s % 60}s"


def size(n: int | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def find_nodes() -> list[str]:
    found = []
    for p in PLACES:
        path = Path(p).expanduser()
        if path.exists():
            found.append(str(path))
    return found


class MonitorApp(App):
    TITLE = "unseenet-monitor"
    CSS = CSS + console_css()
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("n", "next_node", "Next node"),
        Binding("p", "previous_node", "Previous node"),
        Binding("1", "tab('peers')", "Peers"),
        Binding("2", "tab('groups')", "Groups"),
        Binding("3", "tab('rejected')", "Rejected"),
        Binding("4", "tab('log')", "Log"),
    ]

    def __init__(self, nodes: list[str], refresh: float = REFRESH):
        super().__init__()
        self.nodes = nodes
        self.index = 0
        self.refresh_every = refresh
        self.snapshot: dict | None = None
        self._log_seen: list[str] = []

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action in ("next_node", "previous_node"):
            return len(self.nodes) > 1
        return True

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            yield Static("Connecting ...", id="node")
            with Vertical(id="traffic"):
                yield Label("Per minute, last hour   hour / all", classes="title")
                for key, label in (("accepted", "in"), ("sent", "to peers"),
                                   ("served", "read"), ("rejected", "rejected")):
                    with Horizontal(classes="spark-row"):
                        yield Label(label, classes="spark-label")
                        yield Sparkline([0] * 60, id=f"spark-{key}", summary_function=max)
                        yield Label("", id=f"lbl-{key}", classes="spark-count")
        yield Static("", id="warnings")
        with TabbedContent(initial="peers"):
            with TabPane("Peers", id="peers"):
                yield DataTable(id="peers-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Groups", id="groups"):
                yield DataTable(id="groups-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Rejected", id="rejected"):
                yield DataTable(id="rejected-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Log", id="log"):
                yield RichLog(id="log-view", wrap=True, markup=False, highlight=False)
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#peers-table", DataTable).add_columns(
            "Peer", "Auth", "Queue", "Sent", "Last sent", "Pulled", "Last pull", "State")
        self.query_one("#groups-table", DataTable).add_columns("Group", "Articles")
        self.query_one("#rejected-table", DataTable).add_columns("Reason", "Articles")
        self.poll()
        self.set_interval(self.refresh_every, self.poll)

    # --- data --------------------------------------------------------------
    @work(exclusive=True, group="poll", exit_on_error=False)
    async def poll(self) -> None:
        where = self.nodes[self.index]
        try:
            snap = await fetch(where)
            lines = await fetch(where, "log 200")
        except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
            self.show_down(where, exc)
            return
        self.snapshot = snap
        self.show(snap, lines, where)

    def show_down(self, where: str, exc: Exception) -> None:
        hint = (" - is the node running, and are you its user? (sudo -u unseenet ...)"
                if isinstance(exc, (FileNotFoundError, PermissionError, ConnectionRefusedError))
                else "")
        self.query_one("#node", Static).update(f"[b]{where}[/b]\n\nNot reachable: {exc}{hint}")
        self.query_one("#warnings", Static).update("")
        self.query_one("#status", Static).update(f"{where}  ·  not reachable  ·  "
                                                 f"{time.strftime('%H:%M:%S')}")

    def show(self, snap: dict, lines: list[str], where: str) -> None:
        now = snap["time"]
        node, tor, conn = snap["node"], snap["tor"], snap["connections"]
        store, traffic = snap["store"], snap["traffic"]
        self.sub_title = (f"{node['name']}  ·  node {self.index + 1} of {len(self.nodes)}"
                          if len(self.nodes) > 1 else node["name"])
        tor_text = {"off": "off", "down": "[red]down[/red]"}.get(
            tor["state"], f"{tor.get('bootstrap', '?')}%")
        policy = node.get("policy", {})
        onion = node.get("onion") or "-"
        if len(onion) > 30:
            onion = onion[:12] + "…" + onion[-17:]
        # short lines: two of these boxes fit side by side in 80 columns
        self.query_one("#node", Static).update(
            f"[b]{short(node['name'], 20)}[/b]  {node['version'].replace('unseenet ', '')}\n"
            f"Onion  {onion}\n"
            f"Key    {short(node['key'], 28)}\n"
            f"Up     {duration(node['uptime'])}   Tor {tor_text}\n"
            f"Conns  {conn['open']} now ({conn['peers_open']} peers), {conn['total']} all\n"
            f"Store  {store['groups']} groups, {store['articles']} articles\n"
            f"Size   {size(store['bytes'])}, {size(store.get('disk_free'))} free\n"
            f"Rules  {policy.get('min_pow', '?')} bits, {policy.get('retention_days', '?')} days, "
            f"new: {policy.get('new_groups', '?')}")
        per = traffic["per_minute"]
        totals = {"accepted": sum(traffic["accepted"].values()), "sent": traffic["sent"],
                  "served": traffic["served"], "rejected": sum(traffic["rejected"].values())}
        for key in per:
            self.query_one(f"#spark-{key}", Sparkline).data = per[key]
            self.query_one(f"#lbl-{key}", Label).update(f"{sum(per[key])} / {totals[key]}")
        warn = self.query_one("#warnings", Static)
        warn.set_class(not snap["warnings"], "ok")
        warn.update("  ".join(f"! {w}" for w in snap["warnings"]) or "All well.")

        peers = self.query_one("#peers-table", DataTable)
        peers.clear()
        for p in snap["peers"]:
            state = (f"[red]{short(p['last_error'], 40)}[/red]" if p["last_error"]
                     else "[green]ok[/green]")
            peers.add_row(p["name"], p["authenticated_by"], str(p["queue"]), str(p["sent"]),
                          ago(p["last_sent"], now), str(p["pulled"]), ago(p["last_pull"], now),
                          state)
        if not snap["peers"]:
            peers.add_row("(no peers configured)", "", "", "", "", "", "", "")
        groups = self.query_one("#groups-table", DataTable)
        groups.clear()
        for gid, n in store["busiest"]:
            groups.add_row(gid, str(n))
        rejected = self.query_one("#rejected-table", DataTable)
        rejected.clear()
        for reason, n in sorted(traffic["rejected"].items(), key=lambda kv: -kv[1]):
            rejected.add_row(reason, str(n))
        log = self.query_one("#log-view", RichLog)
        if not lines:
            lines = ["(Nothing logged since the node started. Accepted articles, peers and "
                     "catching up are logged here as they happen.)"]
        new = lines[len(self._log_seen):] if lines[: len(self._log_seen)] == self._log_seen else lines
        if new is lines:
            log.clear()
        for line in new:
            log.write(line)
        self._log_seen = list(lines)
        self.query_one("#status", Static).update(
            f"{where}  ·  updated {time.strftime('%H:%M:%S')}  ·  every {self.refresh_every:g}s")

    # --- actions --------------------------------------------------------------
    def action_refresh(self) -> None:
        self.poll()

    def _switch(self, step: int) -> None:
        self.index = (self.index + step) % len(self.nodes)
        self._log_seen = []
        self.query_one("#log-view", RichLog).clear()
        self.poll()

    def action_next_node(self) -> None:
        self._switch(+1)

    def action_previous_node(self) -> None:
        self._switch(-1)

    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="unseenet-monitor",
                                description="Watch your Unseenet node: traffic, peers, health.")
    p.add_argument("--node", action="append", metavar="SOCKET",
                   help="the node's stats socket (monitor.sock in its data directory), or "
                        "127.0.0.1:PORT; give it more than once for several nodes")
    p.add_argument("--refresh", type=float, default=REFRESH, help="seconds between updates")
    p.add_argument("--version", action="version", version=f"unseenet-monitor {__version__}")
    args = p.parse_args(argv)
    nodes = args.node or find_nodes()
    if not nodes:
        p.exit(2, "No node found. Give its stats socket with --node "
                  "(monitor.sock in the node's data directory).\n")
    MonitorApp(nodes, args.refresh).run()


if __name__ == "__main__":
    main()
