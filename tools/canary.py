#!/usr/bin/env python3
"""Canaries: are the listed nodes connected? (UN-RFC 0021)

Used by node_health.py (daily) and node_request.py (when a node asks to be
listed). Each day the checker

1. reads, on every listed node that answers, which canaries of the previous
   day it has, which groups it lists, and what it excludes;
2. posts a new canary to each listed node, to that node alone.

From the readings, ``verdicts`` decides for each node whether it is
*connected* (its canary got out to most nodes, and it has every canary that
did) and *complete* (it carries every group most connected nodes carry,
except what it excludes).

The canaries are signed with the GitHub poster key (UNSEENET_ANNOUNCE_SEED),
a poster in unseenet.canary. Without it, nothing is posted and nothing is
judged.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from unseenet.core import crypto  # noqa: E402
from unseenet.core.article import Article, ArticleError, new_article  # noqa: E402
from unseenet.core.encoding import b64  # noqa: E402
from unseenet.known_nodes import CANARY_GROUP  # noqa: E402
from unseenet.nntp import strip_reader_headers  # noqa: E402
from unseenet.node.server import wildmat  # noqa: E402

PROJECT_GROUPS = "unseenet*@ph5fc5hop5232qsz"    # what no listed node may exclude
GROUP_MIN_POW = 20
FROM = "Unseenet project"
SHOW = 5                                          # names listed in a problem before "and N more"


@dataclass
class Reading:
    """What one node showed us today."""
    seen: set[str] = field(default_factory=set)    # node keys of the previous day's canaries
    groups: set[str] = field(default_factory=set)
    excludes: str = ""


# ---------------------------------------------------------------------------
# the articles
# ---------------------------------------------------------------------------
def canary_body(node_key: str, day: date) -> str:
    body = {"v": 1, "node": node_key, "date": day.isoformat(),
            "nonce": b64(secrets.token_bytes(16))}
    return json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n"


def canary_article(key: crypto.Identity, node_name: str, node_key: str, day: date,
                   bits: int) -> bytes:
    art = new_article(CANARY_GROUP, f"canary {node_name} {day.isoformat()}",
                      canary_body(node_key, day), from_name=FROM)
    return art.finalize(key, bits).to_bytes()


def read_canary(raw: bytes, poster: bytes, day: date) -> str | None:
    """The node key a canary of ``day`` was posted to, if ``raw`` is one signed by ``poster``."""
    try:
        art = Article.from_bytes(raw)
        art.verify_signature()
        if art.group != CANARY_GROUP or art.author_key != poster:
            return None
        body = json.loads(art.body)
    except (ArticleError, ValueError, KeyError, crypto.CryptoError):
        return None
    if not isinstance(body, dict) or body.get("v") != 1 or body.get("date") != day.isoformat():
        return None
    node = body.get("node")
    return node if isinstance(node, str) else None


# ---------------------------------------------------------------------------
# deciding
# ---------------------------------------------------------------------------
def _names(keys, names: dict[str, str]) -> str:
    shown = sorted(names.get(k, k) for k in keys)
    more = len(shown) - SHOW
    return ", ".join(shown[:SHOW]) + (f" and {more} more" if more > 0 else "")


def verdicts(readings: dict[str, Reading], posted: set[str],
             names: dict[str, str]) -> dict[str, list[str]]:
    """{node key: problems} for every node that answered today.

    ``readings`` holds the nodes that answered, by node key. ``posted`` is the
    node keys whose canary was posted the previous day; only those can be
    judged on whether their canary got out.
    """
    answered = len(readings)
    if not answered or not posted:
        return {k: [] for k in readings}
    reach = {k: sum(k in r.seen for r in readings.values()) for k in posted}
    in_network = {k for k, n in reach.items() if 2 * n > answered}
    problems: dict[str, list[str]] = {}
    for key, r in readings.items():
        p = []
        if key in posted and key not in in_network:
            p.append(f"Not connected: its canary of yesterday reached {reach[key]} of the "
                     f"{answered} listed nodes that answered, not more than half. Do your peers "
                     f"list this node's key, so they take what it pushes?")
        missing = in_network - r.seen
        if missing:
            p.append(f"Not connected: it does not have yesterday's canaries from "
                     f"{_names(missing, names)}. Does it peer with a listed node, and does that "
                     f"peer list this node's key?")
        problems[key] = p

    connected = [k for k in readings if not problems[k]]
    if connected:
        count: dict[str, int] = {}
        for k in connected:
            for g in readings[k].groups:
                count[g] = count.get(g, 0) + 1
        carried = {g for g, n in count.items() if 2 * n > len(connected)}
        for key, r in readings.items():
            excludes = r.excludes
            bad = sorted(g for g in count if excludes and wildmat(excludes, g)
                         and wildmat(PROJECT_GROUPS, g))           # carried anywhere counts
            missing = sorted(g for g in carried - r.groups
                             if not (excludes and wildmat(excludes, g)))
            if bad:
                problems[key].append(f"Excludes project groups, which every listed node must "
                                     f"carry: {_names(bad, {})}.")
            if missing:
                problems[key].append(f"Not complete: it does not carry {_names(missing, {})}, "
                                     f"which most listed nodes carry. Carry them, or add them "
                                     f"to `excludes` in node.toml so users can see it.")
    return problems


# ---------------------------------------------------------------------------
# the network
# ---------------------------------------------------------------------------
def poster_key() -> crypto.Identity | None:
    import os
    seed = os.environ.get("UNSEENET_ANNOUNCE_SEED", "").strip()
    return crypto.Identity.from_seed(bytes.fromhex(seed)) if seed else None


async def _connect(address: str, socks_port: int):
    from unseenet.core.tor import open_connection
    from unseenet.nntp import Client
    reader, writer = await asyncio.wait_for(open_connection(address, socks_port), 180)
    client = Client(reader, writer)
    await client._response()
    await client.fetch_capabilities()
    return client


async def read_node(address: str, socks_port: int, poster: bytes, day: date) -> Reading:
    """Which canaries of ``day`` the node has, its groups and its excludes."""
    client = await _connect(address, socks_port)
    try:
        r = Reading()
        if client.capability("UNSEENET-NODEINFO") is not None:
            lines = await client.multiline("LIST UNSEENET.NODEINFO", 215)
            info = json.loads(lines[0]) if lines else {}
            r.excludes = str((info.get("policy") or {}).get("excludes") or "")
        r.groups = {line.split()[0] for line in await client.list_active() if line.strip()}
        if CANARY_GROUP in r.groups:
            since = datetime.combine(day - timedelta(days=1), time(), timezone.utc)
            for msgid in await client.newnews(CANARY_GROUP, since.strftime("%Y%m%d %H%M%S")):
                raw = await client.article(msgid)
                # as a reader we get Xref and the like added: they are not signed
                node = read_canary(strip_reader_headers(raw), poster, day) if raw else None
                if node:
                    r.seen.add(node)
        return r
    finally:
        await client.quit()


async def post_canary(address: str, socks_port: int, key: crypto.Identity, node_name: str,
                      node_key: str, day: date) -> str | None:
    """Post today's canary to this node alone. None if it took it, else the problem."""
    client = await _connect(address, socks_port)
    try:
        bits = max(GROUP_MIN_POW, int(client.capability("UNSEENET-MINPOW") or 0))
        code, text = await client.post(canary_article(key, node_name, node_key, day, bits))
    finally:
        await client.quit()
    return None if code == 240 else f"It refused the canary post: {code} {text}"


async def request_check(new, listed, socks_port: int, key: crypto.Identity, today: date,
                        timeout: float = 3600.0, every: float = 300.0) -> list[str] | None:
    """At request time: a canary each way between the new node and the listed network.

    ``new`` and each of ``listed`` have .name, .address and .node_key. Posts one
    canary to the new node and one to the first listed node that takes it, then
    waits until the new node has the listed node's canary and at least one of
    up to three listed nodes has the new node's. Returns the problems, or None
    when the listed nodes do not carry the canary group yet (nothing to check).
    """
    problems = []
    for n in listed[:3]:
        try:
            if CANARY_GROUP not in (await read_node(n.address, socks_port, key.public_key,
                                                    today)).groups:
                return None
            break
        except (OSError, ConnectionError, asyncio.TimeoutError, ValueError):
            continue
    try:
        refused = await post_canary(new.address, socks_port, key, new.name, new.node_key, today)
    except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
        refused = f"Could not post a canary to the node: {exc}"
    if refused:
        return [refused]
    anchor = None
    for n in listed:
        try:
            if await post_canary(n.address, socks_port, key, n.name, n.node_key, today) is None:
                anchor = n
                break
        except (OSError, ConnectionError, asyncio.TimeoutError, ValueError):
            continue
    if anchor is None:
        return ["No listed node took a canary just now, so the connection could not be "
                "checked. It is checked again on the next edit or comment."]
    readers = [anchor] + [n for n in listed if n is not anchor][:2]
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    got_in = got_out = False
    while True:
        try:
            got_in = got_in or anchor.node_key in (
                await read_node(new.address, socks_port, key.public_key, today)).seen
        except (OSError, ConnectionError, asyncio.TimeoutError, ValueError):
            pass
        for n in readers:
            if got_out:
                break
            try:
                got_out = new.node_key in (
                    await read_node(n.address, socks_port, key.public_key, today)).seen
            except (OSError, ConnectionError, asyncio.TimeoutError, ValueError):
                pass
        if (got_in and got_out) or loop.time() + every > end:
            break
        await asyncio.sleep(every)
    minutes = int(timeout // 60)
    if not got_out:
        problems.append(f"A canary posted to this node did not reach the listed nodes within "
                        f"{minutes} minutes. Peer with a listed node, and make sure it lists "
                        f"this node's key, so it takes what this node pushes.")
    if not got_in:
        problems.append(f"A canary posted to **{anchor.name}** did not reach this node within "
                        f"{minutes} minutes. Peer with a listed node (both of you add the other "
                        f"in node.toml), or at least pull from one.")
    return problems
