#!/usr/bin/env python3
"""The project's own nodes peer with each other, every one with every other.

    python tools/project/project_peers.py unseenet-node1
        print the [[peer]] sections unseenet-node1 needs: one for every other
        project node in src/unseenet/nodes.json
    python tools/project/project_peers.py unseenet-node1 --check /home/unseenet/node.toml
        say which of them that node.toml is missing (exit 1 if any), and
        which peers it has that are not project nodes (fine, just shown)

A project node is a node on the list whose `operator` is the project key.
When a project node is added (an Oracle Cloud node, say), run this with
--check on every project node, add what is missing, and restart the node:
`sudo systemctl restart unseenet-node`. Peering is two-way, so the new node
needs the others too (docs/node/peering.md).

No secrets: everything here is public (addresses and node keys).
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from unseenet.core import crypto  # noqa: E402
from unseenet.known_nodes import PROJECT_KEY, parse_node_list  # noqa: E402

NODES = ROOT / "src" / "unseenet" / "nodes.json"


def project_nodes(text: str) -> list:
    _, nodes = parse_node_list(text)
    return [n for n in nodes if n.operator == PROJECT_KEY and n.node_key]


def peer_section(node) -> str:
    address = node.address if ":" in node.address else node.address + ":119"
    return (f'[[peer]]\nname = "{node.name}"\naddress = "{address}"\n'
            f'key = "{node.node_key}"\n'
            f'groups = "*"\npull = "*"\naccept = "*"\n')


def needed(me: str, nodes: list) -> list:
    if me not in {n.name for n in nodes}:
        raise SystemExit(f"{me} is not a project node in nodes.json "
                         f"(project nodes: {', '.join(n.name for n in nodes) or 'none'})")
    return [n for n in nodes if n.name != me]


def missing(want: list, toml_text: str) -> tuple[list, list[str]]:
    """(project nodes the config lacks, names of its other peers). Matched by node key."""
    peers = tomllib.loads(toml_text).get("peer", [])
    have = set()
    for p in peers:
        try:
            have.add(crypto.key_from_text(p["key"]))
        except (KeyError, crypto.CryptoError):
            continue
    keys = {crypto.key_from_text(n.node_key) for n in want}
    lacking = [n for n in want if crypto.key_from_text(n.node_key) not in have]
    others = [p.get("name", "?") for p in peers
              if "key" not in p or crypto.key_from_text(p["key"]) not in keys]
    return lacking, others


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("node", help="this node's name in nodes.json, e.g. unseenet-node1")
    p.add_argument("--check", type=Path, metavar="NODE_TOML")
    args = p.parse_args()
    want = needed(args.node, project_nodes(NODES.read_text()))
    if not args.check:
        print("\n".join(peer_section(n) for n in want), end="")
        return
    lacking, others = missing(want, args.check.read_text())
    for name in others:
        print(f"other peer (not a project node): {name}")
    if not lacking:
        print(f"{args.node} peers with all {len(want)} other project nodes.")
        return
    print(f"{args.node} is missing {len(lacking)} project node(s); add to {args.check}:\n")
    print("\n".join(peer_section(n) for n in lacking), end="")
    sys.exit(1)


if __name__ == "__main__":
    main()
