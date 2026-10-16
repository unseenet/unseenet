#!/usr/bin/env python3
"""Handle "Add my node" issues (.github/ISSUE_TEMPLATE/add-node.yml).

    python tools/node_request.py check --event $GITHUB_EVENT_PATH --comments c.json --report report.md
    python tools/node_request.py add   --event $GITHUB_EVENT_PATH --comments c.json --report report.md

Three things must hold before a node is listed:

1. The form is valid, and the address is not on the list yet.
2. The node answers over Tor as an Unseenet node and reports the node key
   given in the issue (node information, UN-RFC 0011): address and key
   belong together.
3. **The person asking runs the node.** The node key is public - the node
   shows it to anyone - so knowing it proves nothing. The first check posts
   a challenge in the issue; the operator signs it on the node with
   ``unseenet-node --sign "<challenge>"``, which needs the node's passphrase,
   and pastes the signature as a comment. It must verify with the node key.

``add`` then puts the node in src/unseenet/nodes.json and records who asked,
for the daily health check (tools/node_health.py). Both write a Markdown
report for the issue; ``add`` exits non-zero unless the node was added.

Everything in the issue and its comments is untrusted input: it is only
parsed here, in Python, never put on a command line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import secrets
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from unseenet.core import crypto  # noqa: E402
from unseenet.known_nodes import parse_node_list  # noqa: E402

NODES = ROOT / "src" / "unseenet" / "nodes.json"
HEALTH = ROOT / "tools" / "node-health.json"
BOT = "github-actions[bot]"
FIELDS = {"Node name": "name", "Onion address": "address", "Node key": "node_key",
          "Operator key (optional)": "operator", "Description": "description"}
ONION = re.compile(r"^[a-z2-7]{56}\.onion(:\d{1,5})?$")
NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SIGNATURE = re.compile(r"ed25519:[A-Za-z0-9_-]{86}")


# ---------------------------------------------------------------------------
# the form
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# proof that the person asking runs the node
# ---------------------------------------------------------------------------
def find_challenge(comments: list[dict], repo: str, number: int) -> str | None:
    pattern = re.compile(rf"unseenet-node-claim {re.escape(repo)}#{number} [0-9a-f]{{32}}")
    for c in comments:
        if (c.get("user") or {}).get("login") == BOT:
            m = pattern.search(c.get("body") or "")
            if m:
                return m.group(0)
    return None


def new_challenge(repo: str, number: int) -> str:
    return f"unseenet-node-claim {repo}#{number} {secrets.token_hex(16)}"


def proven(comments: list[dict], challenge: str, node_key: str) -> bool:
    pk = crypto.key_from_text(node_key)
    for c in comments:
        for text in SIGNATURE.findall(c.get("body") or ""):
            try:
                if crypto.verify(pk, crypto.PURPOSE_NODE_CLAIM, challenge.encode(),
                                 crypto.sig_from_text(text)):
                    return True
            except crypto.CryptoError:
                continue
    return False


def how_to_prove(challenge: str) -> str:
    return (
        "**Show that you run this node.** The node key is public, so we need proof that "
        "comes from the node itself. On the node, run\n\n"
        "```bash\n"
        "sudo bash -c 'set -a; . /etc/unseenet-node.env; cd /home/unseenet && \\\n"
        f"  sudo -E -u unseenet unseenet/.venv/bin/unseenet-node --data node-data --sign \"{challenge}\"'\n"
        "```\n\n"
        "(or `unseenet-node --data <your data dir> --sign \"...\"` however you run it) "
        "and paste the line it prints - `ed25519:...` - as a comment here. Only the node's "
        "passphrase can make it; it proves nothing else and can be shown to anyone.\n")


# ---------------------------------------------------------------------------
# the node over Tor
# ---------------------------------------------------------------------------
async def check_node(address: str, node_key: str) -> list[str]:
    """Start Tor, then check_node_via."""
    from unseenet.core.tor import TorProcess
    with tempfile.TemporaryDirectory(prefix="unseenet-check-") as tmp:
        tor = TorProcess(Path(tmp), TorProcess.find_binary())
        await tor.start(timeout=180)
        try:
            return await check_node_via(address, node_key, tor.socks_port)
        finally:
            await tor.stop()


async def check_node_via(address: str, node_key: str, socks_port: int) -> list[str]:
    """Connect through Tor's SOCKS port; the node must report the given node key."""
    from unseenet.core.tor import open_connection
    from unseenet.nntp import Client
    problems = []
    try:
        reader, writer = await asyncio.wait_for(open_connection(address, socks_port), 180)
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
                problems.append(f"The node reports node key `{reported}`, not the one given.")
        await client.quit()
    except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
        problems.append(f"Could not reach the node over Tor: {exc}")
    return problems


# ---------------------------------------------------------------------------
def add(f: dict[str, str], issue: dict) -> None:
    data = json.loads(NODES.read_text())
    entry = {"name": f["name"], "address": f["address"], "node_key": f["node_key"]}
    if f.get("operator"):
        entry["operator"] = f["operator"]
    entry["description"] = f["description"]
    data["nodes"].append(entry)
    data["updated"] = date.today().isoformat()
    NODES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    parse_node_list(NODES.read_text())          # still a valid list
    health = json.loads(HEALTH.read_text()) if HEALTH.exists() else {"nodes": {}}
    health["nodes"][f["address"]] = {"issue": issue["number"],
                                     "requested_by": (issue.get("user") or {}).get("login", "")}
    HEALTH.write_text(json.dumps(health, indent=2, sort_keys=True) + "\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["check", "add"])
    p.add_argument("--event", type=Path, required=True)
    p.add_argument("--comments", type=Path, help="the issue's comments, as the GitHub API gives them")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--no-network", action="store_true", help="skip the Tor check (tests)")
    args = p.parse_args()

    event = json.loads(args.event.read_text())
    issue = event["issue"]
    repo = event["repository"]["full_name"]
    comments = json.loads(args.comments.read_text()) if args.comments and args.comments.exists() else []

    f = parse_issue(issue.get("body", ""))
    errors = validate(f)
    if not errors and listed(f["address"]):
        errors.append(f"This address is already on the list (as `{listed(f['address'])}`).")
    if not errors and not args.no_network:
        errors = asyncio.run(check_node(f["address"], f["node_key"]))

    challenge = find_challenge(comments, repo, issue["number"])
    fresh = challenge is None
    if fresh:
        challenge = new_challenge(repo, issue["number"])
    key_ok = not any("Node key" in e for e in validate(f))
    owner_ok = not fresh and key_ok and proven(comments, challenge, f["node_key"])

    parts = []
    if errors:
        parts.append("The automatic check found problems:\n\n" + "\n".join(f"- {e}" for e in errors)
                     + "\n\nEdit the issue to fix them; the check runs again.")
    else:
        parts.append(f"The node answered over Tor as an Unseenet node and reported the node key "
                     f"given here. ✓")
    if owner_ok:
        parts.append("The signature proves that whoever asked runs this node. ✓")
    else:
        if not fresh and comments and SIGNATURE.search(" ".join(c.get("body") or "" for c in comments)):
            parts.append("A signature was posted, but it does not verify with this node key and the "
                         "challenge below. Sign exactly the challenge, on this node.")
        parts.append(how_to_prove(challenge))
    ready = not errors and owner_ok

    if args.action == "check":
        parts.append("Everything checks out. A maintainer will add the node by labelling this "
                     "request `accepted`." if ready else "")
        args.report.write_text("\n\n".join(p for p in parts if p) + "\n")
        return
    if not ready:
        args.report.write_text("Not added yet:\n\n" + "\n\n".join(p for p in parts if p) + "\n")
        sys.exit(1)
    add(f, issue)
    args.report.write_text(
        f"Added **{f['name']}** to the list of known nodes. The new list is posted to "
        f"`unseenet.nodes` on Unseenet, and clients pick it up the next time they connect.\n\n"
        f"The list is checked every day: if the node cannot be reached for 3 days, you get a "
        f"note here; after 10 days it is taken off the list (ask again when it is back). "
        f"Thank you for running a node!\n")


if __name__ == "__main__":
    main()
