#!/usr/bin/env python3
"""Handle "Add my entrance" issues (.github/ISSUE_TEMPLATE/add-entrance.yml), as
node_request.py does for nodes (unseenet-entrance#3).

    python tools/entrance_request.py check --event $GITHUB_EVENT_PATH --comments c.json --report report.md
    python tools/entrance_request.py add   --event $GITHUB_EVENT_PATH --comments c.json --report report.md

Before an entrance is listed in src/unseenet/entrances.json (UN-RFC 0043 8.1):

1. The form is valid, the operator promises section 5, and the addresses are not
   on the list yet.
2. **The person asking runs it.** The first check posts a challenge in the issue;
   the operator sets ``ENTRANCE_CLAIM`` to it, and the entrance shows it in
   ``/.well-known/unseenet-entrance`` at every address given.
3. At each address - over HTTPS, and over Tor for the onion - it names the
   operator given, serves the web client **unchanged** from a signed version,
   and tunnels to a known node (tools/entrance_check.py).

``add`` checks again, puts it in the list and records who asked, for the daily
check (tools/entrance_health.py). Everything in the issue and its comments is
untrusted input: only parsed here, in Python, never put on a command line.
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
sys.path.insert(0, str(ROOT / "tools"))

from unseenet.core import crypto  # noqa: E402
from unseenet.known_nodes import parse_entrance_list, parse_node_list  # noqa: E402

import entrance_check as ec  # noqa: E402

ENTRANCES = ROOT / "src" / "unseenet" / "entrances.json"
NODES = ROOT / "src" / "unseenet" / "nodes.json"
HEALTH = ROOT / "tools" / "entrance-health.json"
BOT = "github-actions[bot]"
FIELDS = {"Entrance name": "name", "Open-web address": "url", "Onion address": "onion",
          "Operator key": "operator", "Contact (optional)": "contact",
          "Description": "description"}
NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PROMISE = "follows UN-RFC 0043 section 5"


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
    cleaned = {k: ("" if v.strip() == "_No response_" else v.strip()) for k, v in out.items()}
    cleaned["promised"] = "yes" if re.search(r"- \[[xX]\] [^\n]*" + re.escape(PROMISE),
                                             body or "") else ""
    if cleaned.get("url") and not cleaned["url"].endswith("/"):
        cleaned["url"] += "/"
    cleaned["onion"] = cleaned.get("onion", "").lower().removeprefix("http://").rstrip("/")
    return cleaned


def validate(f: dict[str, str]) -> list[str]:
    errors = []
    if not NAME.match(f.get("name", "")):
        errors.append("**Entrance name**: use 1-64 letters, digits, `-` or `_`.")
    if not f.get("url") and not f.get("onion"):
        errors.append("Give an **open-web address**, an **onion address**, or both.")
    if f.get("url") and not ec.URL.match(f["url"]):
        errors.append("**Open-web address**: `https://` and a host (a name or an IP address), "
                      "nothing after it - e.g. `https://203.0.113.7/`.")
    if f.get("onion") and not ec.ONION.match(f["onion"]):
        errors.append("**Onion address**: 56 characters followed by `.onion`.")
    try:
        crypto.key_from_text(f.get("operator", ""))
    except crypto.CryptoError:
        errors.append("**Operator key**: your identity key, `ed25519:` followed by the key "
                      "(the same as `ENTRANCE_OPERATOR`).")
    if not 0 < len(f.get("description", "")) <= 200:
        errors.append("**Description**: 1-200 characters.")
    if len(f.get("contact", "")) > 120:
        errors.append("**Contact**: at most 120 characters.")
    if not f.get("promised"):
        errors.append("Tick that the entrance follows UN-RFC 0043 section 5.")
    return errors


def listed(f: dict[str, str]) -> str | None:
    _, entrances = parse_entrance_list(ENTRANCES.read_text())
    for e in entrances:
        if (f.get("url") and e["url"] and e["url"].rstrip("/") == f["url"].rstrip("/")) \
                or (f.get("onion") and e["onion"] == f["onion"]):
            return e["name"]
    return None


def find_challenge(comments: list[dict], repo: str, number: int) -> str | None:
    pattern = re.compile(rf"unseenet-entrance-claim {re.escape(repo)}#{number} [0-9a-f]{{32}}")
    for c in comments:
        if (c.get("user") or {}).get("login") == BOT:
            m = pattern.search(c.get("body") or "")
            if m:
                return m.group(0)
    return None


def new_challenge(repo: str, number: int) -> str:
    return f"unseenet-entrance-claim {repo}#{number} {secrets.token_hex(16)}"


def how_to_prove(challenge: str) -> str:
    return ("**Show that you run this entrance.** Add this line to "
            "`/etc/unseenet-entrance.env` and run `systemctl restart unseenet-entrance`:\n\n"
            f"```\nENTRANCE_CLAIM=\"{challenge}\"\n```\n\n"
            "Then comment here (anything), and the check runs again. Remove the line once "
            "the entrance is listed.")


def known_node() -> str | None:
    _, nodes = parse_node_list(NODES.read_text())
    return nodes[0].address.split(":")[0] if nodes else None


async def check_entrance(f: dict[str, str], claim: str | None) -> list[ec.Result]:
    """Every check, at every address; Tor is started only for an onion."""
    from unseenet.core.tor import TorProcess
    node = known_node()
    results = []
    tor, tmp = None, None
    try:
        for base, over_tor in ec.addresses(f):
            port = None
            if over_tor:
                if tor is None:
                    tmp = tempfile.TemporaryDirectory(prefix="unseenet-entrance-check-")
                    tor = TorProcess(Path(tmp.name), TorProcess.find_binary())
                    await tor.start(timeout=180)
                port = tor.socks_port
            results.append(await ec.check_at(base, socks_port=port, operator=f["operator"],
                                             claim=claim, node=node))
    finally:
        if tor is not None:
            await tor.stop()
        if tmp is not None:
            tmp.cleanup()
    return results


def add(f: dict[str, str], issue: dict) -> None:
    data = json.loads(ENTRANCES.read_text())
    entry = {"name": f["name"]}
    if f.get("url"):
        entry["url"] = f["url"]
    if f.get("onion"):
        entry["onion"] = f["onion"]
    entry["operator"] = f["operator"]
    if f.get("contact"):
        entry["contact"] = f["contact"]
    entry["description"] = f["description"]
    data["entrances"].append(entry)
    data["updated"] = date.today().isoformat()
    ENTRANCES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    parse_entrance_list(ENTRANCES.read_text())        # still a valid list
    health = json.loads(HEALTH.read_text()) if HEALTH.exists() else {"entrances": {}}
    health["entrances"][f["name"]] = {"issue": issue["number"],
                                      "requested_by": (issue.get("user") or {}).get("login", "")}
    HEALTH.write_text(json.dumps(health, indent=2, sort_keys=True) + "\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["check", "add"])
    p.add_argument("--event", type=Path, required=True)
    p.add_argument("--comments", type=Path, help="the issue's comments, as the GitHub API gives them")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--no-network", action="store_true", help="skip reaching the entrance (tests)")
    args = p.parse_args()

    event = json.loads(args.event.read_text())
    issue = event["issue"]
    repo = event["repository"]["full_name"]
    comments = json.loads(args.comments.read_text()) if args.comments and args.comments.exists() else []

    f = parse_issue(issue.get("body", ""))
    errors = validate(f)
    if not errors and listed(f):
        errors.append(f"This entrance is already on the list (as `{listed(f)}`).")
    challenge = find_challenge(comments, repo, issue["number"])
    fresh = challenge is None
    if fresh:
        challenge = new_challenge(repo, issue["number"])

    parts, results = [], []
    if errors:
        parts.append("The automatic check found problems:\n\n" + "\n".join(f"- {e}" for e in errors)
                     + "\n\nEdit the issue to fix them; the check runs again.")
    elif not args.no_network:
        results = asyncio.run(check_entrance(f, None if fresh else challenge))
    problems = [p for r in results for p in r.problems]
    claim_missing = fresh or any("challenge" in p for p in problems)
    other = [p for p in problems if "challenge" not in p]
    if not errors and results:
        if other:
            parts.append("The check found problems:\n\n" + "\n".join(f"- {p}" for p in other)
                         + "\n\nFix them and comment here; the check runs again.")
        else:
            parts.append("At every address it answered, names the operator given, serves the "
                         "signed web client unchanged (version "
                         + ", ".join(sorted({r.version for r in results if r.version}))
                         + ") and tunnels to a known node. ✓")
        if not claim_missing:
            parts.append("It shows the challenge: whoever asked runs it. ✓")
    if claim_missing and not errors:
        parts.append(how_to_prove(challenge))
    ready = not errors and bool(results) and not problems

    if args.action == "check":
        parts.append("Everything checks out. A maintainer will add the entrance by labelling "
                     "this request `accepted`." if ready else "")
        args.report.write_text("\n\n".join(p for p in parts if p) + "\n")
        return
    if not ready:
        args.report.write_text("Not added yet:\n\n" + "\n\n".join(p for p in parts if p) + "\n")
        sys.exit(1)
    add(f, issue)
    args.report.write_text(
        f"Added **{f['name']}** to the list of web entrances. The new list is posted to "
        "`unseenet.entrances` on Unseenet; web clients and the jump page pick it up. You can "
        "remove `ENTRANCE_CLAIM` now.\n\n"
        "The list is checked every day: an entrance that cannot be reached for 3 days gets a "
        "note here, and after 10 days it is taken off the list (ask again when it is back). "
        "One that serves files other than the signed client is taken off **at once**. Thank "
        "you for running an entrance!\n")


if __name__ == "__main__":
    main()
