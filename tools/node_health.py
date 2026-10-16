#!/usr/bin/env python3
"""Daily check of the known nodes (src/unseenet/nodes.json), run by node-health.yml.

Each listed node is reached over Tor and must report its node key. A node
that fails is noted in tools/node-health.json with the day it first failed:

- after WARN_DAYS its operator gets a note (on the issue that listed it, or a
  new issue for nodes listed otherwise);
- after REMOVE_DAYS it is taken off the list, and the new list is announced;
- when it answers again, the failure is forgotten.

If *every* node fails, the problem is almost certainly on our side (the
runner's network, Tor), so nothing is counted that day.

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
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from unseenet.known_nodes import parse_node_list  # noqa: E402

NODES = ROOT / "src" / "unseenet" / "nodes.json"
HEALTH = ROOT / "tools" / "node-health.json"
WARN_DAYS = 3
REMOVE_DAYS = 10


async def check_all(nodes) -> dict[str, list[str]]:
    """{address: problems} for every node, with one Tor and one retry for failures."""
    from unseenet.core.tor import TorProcess
    import node_request
    results = {}
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
        finally:
            await tor.stop()
    return results


def update(results: dict[str, list[str]], today: date) -> dict:
    """Apply one day's results to nodes.json and node-health.json; return the actions."""
    data = json.loads(NODES.read_text())
    health = json.loads(HEALTH.read_text()) if HEALTH.exists() else {"nodes": {}}
    actions = {"changed": False, "announce": False, "comments": [], "issues": [], "summary": []}
    if results and all(results.values()):
        actions["summary"].append("Every node failed - probably the runner's network; nothing counted.")
        return actions

    keep = []
    for node in data["nodes"]:
        address, name = node["address"], node.get("name", node["address"])
        entry = health["nodes"].setdefault(address, {})
        problems = results.get(address, [])
        issue, who = entry.get("issue"), entry.get("requested_by")
        mention = f"@{who} " if who else ""
        if not problems:
            if entry.get("first_failed"):
                actions["summary"].append(f"{name}: back after failing since {entry['first_failed']}")
                if issue and entry.get("warned"):
                    actions["comments"].append({"issue": issue, "body":
                        f"{mention}**{name}** answers again - thank you. Nothing else to do."})
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
            text = (f"{mention}**{name}** (`{address}`) could not be reached for {days} days and "
                    f"has been taken off the list of known nodes. When it is back, ask again with "
                    f"the *Add my node* form.\n\nLast problem: {problems[0]}")
            if issue:
                actions["comments"].append({"issue": issue, "body": text})
            else:
                actions["issues"].append({"title": f"Known node {name} removed: unreachable", "body": text})
            continue
        if days >= WARN_DAYS and not entry.get("warned"):
            entry["warned"] = True
            actions["changed"] = True
            text = (f"{mention}**{name}** (`{address}`) has not answered since "
                    f"{entry['first_failed']}. If it is not reachable for {REMOVE_DAYS} days, it is "
                    f"taken off the list of known nodes.\n\nLast problem: {problems[0]}")
            if issue:
                actions["comments"].append({"issue": issue, "body": text})
            else:
                actions["issues"].append({"title": f"Known node {name} is unreachable", "body": text})
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
    if args.results:
        results = json.loads(args.results.read_text())
    else:
        results = asyncio.run(check_all(nodes))
    today = date.fromisoformat(args.today) if args.today else date.today()
    actions = update(results, today)
    args.actions.write_text(json.dumps(actions, indent=2))
    for line in actions["summary"] or ["All nodes answered."]:
        print(line)


if __name__ == "__main__":
    main()
