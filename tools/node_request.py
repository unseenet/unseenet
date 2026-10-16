#!/usr/bin/env python3
"""Handle "Add my node" issues (.github/ISSUE_TEMPLATE/add-node.yml).

    python tools/node_request.py check  --event $GITHUB_EVENT_PATH --report report.md
    python tools/node_request.py add    --event $GITHUB_EVENT_PATH --report report.md

``check`` validates the form and connects to the node over Tor: it must
answer, speak Unseenet, and report the node key given in the issue (node
information, UN-RFC 0011) - which shows that whoever filed the issue gave a
matching address and key. ``add`` does the same, then adds the node to
src/unseenet/nodes.json. Both write a Markdown report for the issue and exit
non-zero if the node cannot be listed.

The issue text is untrusted input: it is only ever parsed here, in Python,
never put on a command line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from unseenet.core import crypto  # noqa: E402
from unseenet.known_nodes import parse_node_list  # noqa: E402

NODES = ROOT / "src" / "unseenet" / "nodes.json"
FIELDS = {"Node name": "name", "Onion address": "address", "Node key": "node_key",
          "Operator key (optional)": "operator", "Description": "description"}
ONION = re.compile(r"^[a-z2-7]{56}\.onion(:\d{1,5})?$")
NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def parse_issue(body: str) -> dict[str, str]:
    """Issue forms arrive as '### Label' followed by the answer."""
    out, current = {}, None
    for line in (body or "").splitlines():
        heading = re.match(r"^###\s+(.*)$", line)
        if heading:
            current = FIELDS.get(heading.group(1).strip())
            if current:
                out[current] = ""
            continue
        if current:
            out[current] += line + "\n"
    cleaned = {}
    for key, value in out.items():
        value = value.strip()
        cleaned[key] = "" if value == "_No response_" else value
    return cleaned


def validate(f: dict[str, str]) -> list[str]:
    errors = []
    if not NAME.match(f.get("name", "")):
        errors.append("**Node name**: use 1-64 letters, digits, `-` or `_`.")
    if not ONION.match(f.get("address", "")):
        errors.append("**Onion address**: expected 56 characters followed by `.onion` "
                      "(and `:port` only if it is not 119).")
    for field, label, required in (("node_key", "Node key", True), ("operator", "Operator key", False)):
        value = f.get(field, "")
        if not value and not required:
            continue
        try:
            crypto.key_from_text(value)
        except crypto.CryptoError:
            errors.append(f"**{label}**: expected `ed25519:` followed by the key.")
    if not 0 < len(f.get("description", "")) <= 200:
        errors.append("**Description**: 1-200 characters.")
    return errors


def listed(address: str) -> str | None:
    _, nodes = parse_node_list(NODES.read_text())
    host = address.split(":")[0]
    for n in nodes:
        if n.address.split(":")[0] == host:
            return n.name
    return None


async def check_node(address: str, node_key: str) -> list[str]:
    """Connect over Tor; the node must report the given node key."""
    from unseenet.core.tor import TorProcess, open_connection
    from unseenet.nntp import Client
    problems = []
    with tempfile.TemporaryDirectory(prefix="unseenet-check-") as tmp:
        tor = TorProcess(Path(tmp), TorProcess.find_binary())
        await tor.start(timeout=180)
        try:
            reader, writer = await asyncio.wait_for(open_connection(address, tor.socks_port), 180)
            client = Client(reader, writer)
            await client._response()
            caps = await client.fetch_capabilities()
            if "UNSEENET 1" not in caps:
                problems.append("The node answers, but not as an Unseenet node (`UNSEENET 1` missing).")
            elif client.capability("UNSEENET-NODEINFO") is None:
                problems.append("The node publishes no node information (UN-RFC 0011); update it.")
            else:
                lines = await client.multiline("LIST UNSEENET.NODEINFO", 215)
                info = json.loads(lines[0]) if lines else {}
                reported = info.get("node_key")
                if not reported:
                    problems.append("The node does not report a node key; update it to a version "
                                    "with UN-RFC 0016.")
                elif crypto.key_from_text(reported) != crypto.key_from_text(node_key):
                    problems.append(f"The node reports node key `{reported}`, not the one in the issue.")
            await client.quit()
        except (OSError, ConnectionError, asyncio.TimeoutError) as exc:
            problems.append(f"Could not reach the node over Tor: {exc}")
        finally:
            await tor.stop()
    return problems


def add(f: dict[str, str]) -> None:
    data = json.loads(NODES.read_text())
    entry = {"name": f["name"], "address": f["address"], "node_key": f["node_key"]}
    if f.get("operator"):
        entry["operator"] = f["operator"]
    entry["description"] = f["description"]
    data["nodes"].append(entry)
    data["updated"] = date.today().isoformat()
    NODES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    parse_node_list(NODES.read_text())          # still a valid list


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["check", "add"])
    p.add_argument("--event", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--no-network", action="store_true", help="skip the Tor check (tests)")
    args = p.parse_args()

    issue = json.loads(args.event.read_text())["issue"]
    f = parse_issue(issue.get("body", ""))
    errors = validate(f)
    if not errors and listed(f["address"]):
        errors.append(f"This address is already on the list (as `{listed(f['address'])}`).")
    if not errors and not args.no_network:
        errors = asyncio.run(check_node(f["address"], f["node_key"]))

    if errors:
        args.report.write_text("Thanks! The automatic check found problems:\n\n"
                               + "\n".join(f"- {e}" for e in errors)
                               + "\n\nEdit the issue to fix them; the check runs again.\n")
        sys.exit(1)
    if args.action == "check":
        args.report.write_text(
            f"Automatic check passed: `{f['address']}` answered over Tor as an Unseenet node "
            f"and reported the node key given here.\n\nA maintainer will look at it; when the "
            f"request gets the `accepted` label, the node is added and announced.\n")
        return
    add(f)
    args.report.write_text(
        f"Added **{f['name']}** to the list of known nodes. The new list is posted to "
        f"`unseenet.nodes` on Unseenet, and clients pick it up the next time they connect. "
        f"Thank you for running a node!\n")


if __name__ == "__main__":
    main()
