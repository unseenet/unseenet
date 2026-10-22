"""What a node knows about itself, for its operator: the local stats interface.

The node counts what it does - articles accepted and rejected (by reason), sent
to and pulled from peers, connections - and keeps its last log lines. A program
such as ``unseenet-monitor`` reads a snapshot as JSON from a Unix socket in the
node's data directory (or from 127.0.0.1, never any other address): one request
line, one JSON line back.

    stats            the snapshot below
    log [n]          the last n log lines (default 100), one JSON list

Nothing here is about readers: no addresses (over Tor there are none), and no
record of which group or article anyone read - only how many articles were
served in total. That is what the node's logging policy (UN-RFC 0011) promises.

Snapshot (``"v": 1``)::

    {"v": 1, "time": ..., "node": {name, version, key, onion, started, uptime, policy},
     "tor": {"state": "running"|"off"|"down", "bootstrap": 100, "summary": "..."},
     "traffic": {"accepted": {"client": n, "peer": n, "pull": n}, "rejected": {reason: n},
                 "served": n, "sent": n,
                 "per_minute": {"accepted": [60 values, oldest first], "rejected": [...],
                                "sent": [...], "served": [...]}},
     "connections": {"open": n, "peers_open": n, "total": n, "max_clients": n, "refused": n},
     "peers": [{name, address, authenticated_by, queue, sent, last_sent, last_error,
                last_error_at, pulled, last_pull, last_pull_result}],
     "store": {"groups": n, "articles": n, "bytes": n, "db_bytes": n, "disk_free": n,
               "busiest": [[group, articles], ...], "removed_groups": n},
     "warnings": ["..."]}
"""

from __future__ import annotations

import asyncio
import collections
import ipaddress
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

VERSION = 1
MINUTES = 60
LOG_LINES = 300
MAX_REQUEST = 200


class _Series:
    """Counts per minute for the last hour."""

    def __init__(self) -> None:
        self.buckets: collections.deque = collections.deque([0] * MINUTES, maxlen=MINUTES)
        self.minute = int(time.time() // 60)

    def _roll(self) -> None:
        now = int(time.time() // 60)
        for _ in range(min(now - self.minute, MINUTES)):
            self.buckets.append(0)
        self.minute = now

    def add(self, n: int = 1) -> None:
        self._roll()
        self.buckets[-1] += n

    def values(self) -> list[int]:
        self._roll()
        return list(self.buckets)


class _LogTail(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.lines: collections.deque = collections.deque(maxlen=LOG_LINES)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                                            "%Y-%m-%d %H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:  # noqa: BLE001
            pass


class PeerStats:
    def __init__(self, name: str, address: str, authenticated_by: str) -> None:
        self.name, self.address, self.authenticated_by = name, address, authenticated_by
        self.sent = 0
        self.last_sent: float | None = None
        self.last_error: str | None = None
        self.last_error_at: float | None = None
        self.pulled = 0
        self.last_pull: float | None = None
        self.last_pull_result: str | None = None


class Stats:
    def __init__(self) -> None:
        self.started = time.time()
        self.accepted = collections.Counter()      # client / peer / pull
        self.rejected = collections.Counter()      # by UN-RFC 0005 reason
        self.served = 0
        self.sent = 0
        self.series = {k: _Series() for k in ("accepted", "rejected", "sent", "served")}
        self.open = 0
        self.peers_open = 0
        self.total = 0
        self.refused = 0                           # clients turned away while full (#296)
        self.peers: dict[str, PeerStats] = {}
        self.log = _LogTail()
        self.tor = None                            # the node's TorProcess, if any
        self.onion: str | None = None
        self._lock = asyncio.Lock()

    # --- what the node reports -------------------------------------------
    def accepted_one(self, how: str) -> None:
        self.accepted[how] += 1
        self.series["accepted"].add()

    def rejected_one(self, reason: str) -> None:
        self.rejected[reason or "other"] += 1
        self.series["rejected"].add()

    def served_one(self) -> None:
        self.served += 1
        self.series["served"].add()

    def note(self, text: str) -> None:
        """A line for the monitor's log only (the node prints it to its own output)."""
        self.log.lines.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} INFO unseenet.node: {text}")

    def peer(self, name: str, address: str = "", authenticated_by: str = "") -> PeerStats:
        if name not in self.peers:
            self.peers[name] = PeerStats(name, address, authenticated_by)
        return self.peers[name]

    def sent_to(self, name: str, n: int) -> None:
        p = self.peer(name)
        if n:
            p.sent += n
            p.last_sent = time.time()
            self.sent += n
            self.series["sent"].add(n)
        p.last_error = None

    def peer_error(self, name: str, error: str) -> None:
        p = self.peer(name)
        p.last_error, p.last_error_at = error, time.time()

    def pulled_from(self, name: str, accepted: int, result: str) -> None:
        p = self.peer(name)
        p.pulled += accepted
        p.last_pull, p.last_pull_result = time.time(), result

    def session_opened(self) -> None:
        self.open += 1
        self.total += 1

    def session_closed(self, was_peer: bool) -> None:
        self.open = max(0, self.open - 1)
        if was_peer:
            self.peers_open = max(0, self.peers_open - 1)

    def peer_authenticated(self) -> None:
        self.peers_open += 1

    def client_refused(self) -> None:
        self.refused += 1

    # --- the snapshot -------------------------------------------------------
    async def _tor_state(self) -> dict:
        tor = self.tor
        if tor is None:
            return {"state": "off"}
        if not tor.alive() or tor.control is None:
            return {"state": "down"}
        try:
            # shield: on timeout the command still reads its whole reply, so the
            # control connection stays in step for the node's own commands (#127)
            line = (await asyncio.wait_for(asyncio.shield(
                tor.control.command("GETINFO status/bootstrap-phase")), 5))[0]
        except (OSError, ConnectionError, asyncio.TimeoutError, IndexError):
            return {"state": "down"}
        fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
        try:
            progress = int(fields.get("PROGRESS", "0"))
        except ValueError:
            progress = 0
        return {"state": "running", "bootstrap": progress,
                "summary": fields.get("SUMMARY", "").strip('"')}

    async def snapshot(self, node, data_dir: Path | None = None) -> dict:
        async with self._lock:
            tor = await self._tor_state()
        store, cfg = node.store, node.config
        counts = store.group_sizes()
        db = store.path
        now = time.time()
        peers = []
        for pc in cfg.peers:
            p = self.peer(pc.name)
            p.address = pc.address
            p.authenticated_by = "key" if pc.key else ("password" if pc.password else "none")
            peers.append({"name": p.name, "address": p.address,
                          "authenticated_by": p.authenticated_by,
                          "queue": store.queue_length(p.name), "sent": p.sent,
                          "last_sent": p.last_sent, "last_error": p.last_error,
                          "last_error_at": p.last_error_at, "pulled": p.pulled,
                          "last_pull": p.last_pull, "last_pull_result": p.last_pull_result})
        disk_free = None
        if data_dir is not None:
            try:
                disk_free = shutil.disk_usage(data_dir).free
            except OSError:
                pass
        snap = {
            "v": VERSION, "time": now,
            "node": {"name": cfg.name, "version": node.node_info()["software"],
                     "key": node.key.key_text, "onion": self.onion, "started": self.started,
                     "uptime": now - self.started, "policy": node.node_info()["policy"],
                     "peers_configured": len(cfg.peers)},
            "tor": tor,
            "traffic": {"accepted": dict(self.accepted), "rejected": dict(self.rejected),
                        "served": self.served, "sent": self.sent,
                        "per_minute": {k: s.values() for k, s in self.series.items()}},
            "connections": {"open": self.open, "peers_open": self.peers_open, "total": self.total,
                            "max_clients": node.client_limit, "refused": self.refused},
            "peers": peers,
            "store": {"groups": store.group_count(), "articles": sum(counts.values()),
                      "bytes": store.total_bytes(),
                      "db_bytes": db.stat().st_size if db and db.exists() else None,
                      "disk_free": disk_free,
                      "busiest": sorted(counts.items(), key=lambda kv: -kv[1])[:10],
                      "removed_groups": store.tombstone_count()},
        }
        snap["warnings"] = warnings(snap)
        return snap


def warnings(snap: dict) -> list[str]:
    """Things an operator should look at."""
    out = []
    tor = snap["tor"]
    if tor.get("state") == "down":
        out.append("Tor is not running: the node cannot be reached")
    elif tor.get("state") == "running" and tor.get("bootstrap", 100) < 100:
        out.append(f"Tor is still starting ({tor['bootstrap']}%)")
    day = 24 * 3600
    for p in snap["peers"]:
        if p["last_error"] and (not p["last_sent"] or p["last_error_at"] - p["last_sent"] > day) \
                and snap["node"]["uptime"] > 600:
            out.append(f"peer {p['name']}: {p['last_error']}")
        if p["queue"] > 1000:
            out.append(f"peer {p['name']}: {p['queue']} articles waiting")
    free = snap["store"].get("disk_free")
    if free is not None and free < 500 * 1024 * 1024:
        out.append(f"only {free // (1024 * 1024)} MB free on the data disk")
    return out


# ----------------------------------------------------------------------
# The interface: a Unix socket, or 127.0.0.1 (never another address)
# ----------------------------------------------------------------------
def parse_listen(value: str) -> tuple[str, str | int]:
    """("unix", path) or ("tcp", port) for a loopback address; refuses anything else."""
    if value.startswith("unix:") or "/" in value or value.endswith(".sock"):
        return "unix", value.removeprefix("unix:")
    host, _, port = value.rpartition(":")
    host = host.strip("[]") or "127.0.0.1"
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError(f"the stats interface only listens on this computer, not on {host!r}")
    return "tcp", int(port)


# Unix socket paths are limited by sun_path: 104 bytes on macOS and the BSDs,
# 108 on Linux, including the closing NUL.
UNIX_PATH_MAX = 103 if sys.platform == "darwin" or "bsd" in sys.platform else 107


async def serve(stats: Stats, node, listen: str, data_dir: Path | None = None):
    kind, where = parse_listen(listen)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=300)
                if not line:
                    break
                parts = line.decode("utf-8", "replace").strip().split()
                if not parts or len(line) > MAX_REQUEST:
                    continue
                if parts[0] == "stats":
                    reply = await stats.snapshot(node, data_dir)
                elif parts[0] == "log":
                    n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 100
                    reply = list(stats.log.lines)[-min(n, LOG_LINES):]
                else:
                    reply = {"error": "unknown request; try 'stats' or 'log 100'"}
                writer.write(json.dumps(reply, separators=(",", ":")).encode() + b"\n")
                await writer.drain()
        except (ConnectionError, asyncio.TimeoutError, OSError):
            pass
        finally:
            writer.close()

    if kind == "unix":
        path = Path(where)
        if len(os.fsencode(path)) > UNIX_PATH_MAX:
            raise ValueError(f"the monitor socket path is too long for this system "
                             f"({len(os.fsencode(path))} bytes, at most {UNIX_PATH_MAX}): {path}")
        path.unlink(missing_ok=True)
        old = os.umask(0o117)                     # owner and group only: rw-rw----
        try:
            server = await asyncio.start_unix_server(handle, path=str(path))
        finally:
            os.umask(old)
        return server
    return await asyncio.start_server(handle, "127.0.0.1", where)


async def fetch(listen: str, request: str = "stats", timeout: float = 10):
    """Ask a node's stats interface (used by unseenet-monitor and the tests)."""
    kind, where = parse_listen(listen)
    if kind == "unix":
        conn = asyncio.open_unix_connection(str(where))
    else:
        conn = asyncio.open_connection("127.0.0.1", where)
    reader, writer = await asyncio.wait_for(conn, timeout)
    try:
        writer.write(request.encode() + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout)
        if not line:
            raise ConnectionError("the node closed the connection")
        return json.loads(line)
    finally:
        writer.close()
