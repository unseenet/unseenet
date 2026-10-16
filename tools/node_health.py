#!/usr/bin/env python3
"""Daily check of the known nodes (src/unseenet/nodes.json), run by node-health.yml.

Each listed node is reached over Tor and must report its node key. It must
also be connected to the other listed nodes and carry their groups, checked
with daily canary posts (UN-RFC 0021, tools/canary.py). A node that fails is
noted in tools/node-health.json with the day it first failed:

- after WARN_DAYS its operator gets a note (on the issue that listed it, or a
  new issue for nodes listed otherwise);
- after REMOVE_DAYS it is taken off the list, and the new list is announced;
- when it answers again, the failure is forgotten.

If *every* node is unreachable, the problem is almost certainly on our side
(the runner's network, Tor), so nothing is counted that day.

    python tools/node_health.py --actions actions.json

writes what the workflow should do: whether files changed, whether the list
must be announced, and the comments and issues to post.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from unseenet.known_nodes import parse_node_list  # noqa: E402

NODES = ROOT / "src" / "unseenet" / "nodes.json"
HEALTH = ROOT / "tools" / "node-health.json"
WARN_DAYS = 3
REMOVE_DAYS = 10
REQUIREMENTS = "https://unseenet.org/node/operations/#getting-your-node-listed"


def _problems(problems: list[str]) -> str:
    return "Problems found today:\n\n" + "\n".join(f"- {p}" for p in problems)


async def check_all(nodes, today: date, posted_yesterday: set[str]):
    """Reach every node, then read and post canaries.

    Returns ({address: reach problems}, {address: connection problems},
    node keys whose canary was posted today).
    """
    from unseenet.core.tor import TorProcess
    import canary
    import node_request
    results, connection, posted = {}, {}, set()
    with tempfile.TemporaryDirectory(prefix="unseenet-health-") as tmp:
        tor = TorProcess(Path(tmp), TorProcess.find_binary())
        await tor.start(timeout=180)
        try:
            for attempt in (1, 2):
                for n in nodes:
                    if results.get(n.address) == []:
                        continue
                    results[n.address] = await node_request.check_node_via(
                        n.address, n.node_key, tor.socks_port)
                if all(not v for v in results.values()):
                    break
                await asyncio.sleep(60)                  # descriptors, circuits: try once more
            key = canary.poster_key()
            if key is not None:
                connection, posted = await check_canaries(
                    [n for n in nodes if not results.get(n.address) and n.node_key],
                    tor.socks_port, key, today, posted_yesterday)
        finally:
            await tor.stop()
    return results, connection, posted


async def check_canaries(nodes, socks_port: int, key, today: date, posted_yesterday: set[str]):
    """UN-RFC 0021: read yesterday's canaries everywhere, judge, post today's."""
    import canary
    yesterday = today - timedelta(days=1)
    readings, problems, posted = {}, {}, set()
    for n in nodes:
        try:
            readings[n.node_key] = await canary.read_node(n.address, socks_port, key.public_key,
                                                         yesterday)
        except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
            print(f"{n.name}: could not read canaries ({exc})")
    carrying = sum(canary.CANARY_GROUP in r.groups for r in readings.values())
    if 2 * carrying <= len(readings):
        # until most listed nodes carry unseenet.canary (the project creates it with
        # tools/project/create_groups.py), canaries prove nothing: judge nobody
        print(f"unseenet.canary is carried by {carrying} of {len(readings)} nodes; "
              f"no canaries posted or judged")
        return {}, set()
    names = {n.node_key: n.name for n in nodes}
    by_key = canary.verdicts(readings, posted_yesterday & set(readings), names)
    for n in nodes:
        problems[n.address] = list(by_key.get(n.node_key, []))
        try:
            refused = await canary.post_canary(n.address, socks_port, key, n.name, n.node_key, today)
        except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
            refused = None
            print(f"{n.name}: could not post its canary ({exc})")
        if refused:
            problems[n.address].append(refused)
        elif n.node_key in names:
            posted.add(n.node_key)
    return problems, posted


def load_health() -> dict:
    return json.loads(HEALTH.read_text()) if HEALTH.exists() else {"nodes": {}}


def posted_yesterday(health: dict, today: date) -> set[str]:
    """Node keys whose canary was posted the day before ``today``."""
    c = health.get("canaries") or {}
    if c.get("date") != (today - timedelta(days=1)).isoformat():
        return set()
    return set(c.get("posted", []))


def update(results: dict[str, list[str]], today: date,
           connection: dict[str, list[str]] | None = None, posted: set[str] | None = None) -> dict:
    """Apply one day's results to nodes.json and node-health.json; return the actions.

    ``results`` are reachability problems, ``connection`` canary problems
    (UN-RFC 0021) for nodes that answered, ``posted`` the node keys whose canary
    was posted today.
    """
    data = json.loads(NODES.read_text())
    health = load_health()
    actions = {"changed": False, "announce": False, "comments": [], "issues": [], "summary": []}
    if results and all(results.values()):
        actions["summary"].append("Every node failed - probably the runner's network; nothing counted.")
        return actions
    if posted is not None:
        health["canaries"] = {"date": today.isoformat(), "posted": sorted(posted)}
        actions["changed"] = True
    connection = connection or {}

    keep = []
    for node in data["nodes"]:
        address, name = node["address"], node.get("name", node["address"])
        entry = health["nodes"].setdefault(address, {})
        problems = results.get(address, []) or connection.get(address, [])
        issue, who = entry.get("issue"), entry.get("requested_by")
        mention = f"@{who} " if who else ""
        if not problems:
            if entry.get("first_failed"):
                actions["summary"].append(f"{name}: fine again after failing since {entry['first_failed']}")
                if issue and entry.get("warned"):
                    actions["comments"].append({"issue": issue, "body":
                        f"{mention}**{name}** passes the daily check again - thank you. "
                        f"Nothing else to do."})
                for k in ("first_failed", "last_error", "warned"):
                    entry.pop(k, None)
                actions["changed"] = True
            keep.append(node)
            continue
        if not entry.get("first_failed"):
            entry["first_failed"] = today.isoformat()
            actions["changed"] = True
        if entry.get("last_error") != problems[0]:
            entry["last_error"] = problems[0]
            actions["changed"] = True
        days = (today - date.fromisoformat(entry["first_failed"])).days
        actions["summary"].append(f"{name}: failing for {days} days - {problems[0]}")
        if days >= REMOVE_DAYS:
            actions["announce"] = actions["changed"] = True
            health["nodes"].pop(address, None)
            text = (f"{mention}**{name}** (`{address}`) has failed the daily check for {days} days "
                    f"and has been taken off the list of known nodes. When it is fixed, ask again "
                    f"with the *Add my node* form.\n\n{_problems(problems)}")
            if issue:
                actions["comments"].append({"issue": issue, "body": text})
            else:
                actions["issues"].append({"title": f"Known node {name} removed", "body": text})
            continue
        if days >= WARN_DAYS and not entry.get("warned"):
            entry["warned"] = True
            actions["changed"] = True
            text = (f"{mention}**{name}** (`{address}`) has failed the daily check since "
                    f"{entry['first_failed']}. If it still fails after {REMOVE_DAYS} days, it is "
                    f"taken off the list of known nodes. See [the requirements]({REQUIREMENTS})."
                    f"\n\n{_problems(problems)}")
            if issue:
                actions["comments"].append({"issue": issue, "body": text})
            else:
                actions["issues"].append({"title": f"Known node {name} fails the daily check",
                                          "body": text})
        keep.append(node)

    if len(keep) != len(data["nodes"]):
        if not keep:                      # never publish an empty list
            actions["summary"].append("Would remove every node - keeping the list as it is.")
            actions["announce"] = False
        else:
            data["nodes"] = keep
            data["updated"] = today.isoformat()
            NODES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            parse_node_list(NODES.read_text())
    health["nodes"] = {a: e for a, e in health["nodes"].items() if e}
    HEALTH.write_text(json.dumps(health, indent=2, sort_keys=True) + "\n")
    return actions


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--actions", type=Path, required=True)
    p.add_argument("--today", help="YYYY-MM-DD (tests)")
    p.add_argument("--results", type=Path, help="use these results instead of checking (tests)")
    args = p.parse_args()
    _, nodes = parse_node_list(NODES.read_text())
    today = date.fromisoformat(args.today) if args.today else date.today()
    if args.results:
        given = json.loads(args.results.read_text())
        results = given.get("reach", given)
        connection, posted = given.get("connection", {}), given.get("posted")
        posted = set(posted) if posted is not None else None
    else:
        results, connection, posted = asyncio.run(
            check_all(nodes, today, posted_yesterday(load_health(), today)))
        if not posted:
            posted = None                   # no key, or nothing taken: keep yesterday's record
    actions = update(results, today, connection, posted)
    args.actions.write_text(json.dumps(actions, indent=2))
    for line in actions["summary"] or ["All nodes answered."]:
        print(line)


if __name__ == "__main__":
    main()
