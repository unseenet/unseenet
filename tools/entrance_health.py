#!/usr/bin/env python3
"""Daily check of the listed web entrances (src/unseenet/entrances.json), run by
entrance-health.yml - as node_health.py does for nodes (unseenet-entrance#3).

Each entrance is reached at its open-web address (HTTPS) and its onion (over
Tor) as in tools/entrance_check.py: it must answer, name its operator, tunnel
to a known node, and serve the web client as a signed version names it.

- **Files that differ** from the signed version it says it serves: taken off
  the list at once (UN-RFC 0043 7.6) - that is what outside watching is for.
- **Not reachable**, not tunnelling or not naming its operator: noted with the
  day it first failed; a note to the operator after WARN_DAYS, off the list
  after REMOVE_DAYS, forgotten when it passes again.
- **A version no longer in the signed list** (posts expire): a note only, after
  WARN_DAYS - it should update itself; nothing it serves is wrong.

The project's own entrances (operator: the project key) are never taken off by
this check; their problems become an issue. If every entrance fails, the
problem is probably on our side and nothing is counted that day.

    python tools/entrance_health.py --actions actions.json
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

from unseenet.known_nodes import parse_entrance_list  # noqa: E402

import entrance_check as ec  # noqa: E402

ENTRANCES = ROOT / "src" / "unseenet" / "entrances.json"
HEALTH = ROOT / "tools" / "entrance-health.json"
WARN_DAYS = 3
REMOVE_DAYS = 10
GUIDE = "https://unseenet.org/entrance/listed/"


def load_health() -> dict:
    try:
        data = json.loads(HEALTH.read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("entrances", {})
    return data


async def check_all(entrances: list[dict]) -> dict[str, dict]:
    """{name: {"problems": [...], "changed": bool, "outdated": bool}}."""
    from unseenet.core.tor import TorProcess
    from entrance_request import known_node
    node = known_node()
    out: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="unseenet-entrance-health-") as tmp:
        tor = None
        if any(e.get("onion") for e in entrances):
            tor = TorProcess(Path(tmp), TorProcess.find_binary())
            await tor.start(timeout=180)
        try:
            for e in entrances:
                rec = {"problems": [], "changed": False, "outdated": False}
                for base, over_tor in ec.addresses(e):
                    r = await ec.check_at(base, socks_port=tor.socks_port if over_tor and tor else None,
                                          operator=e.get("operator", ""), node=node)
                    rec["changed"] |= r.unchanged is False
                    for p in r.problems:
                        if "which no signed post" in p:
                            rec["outdated"] = True
                        else:
                            rec["problems"].append(p)
                out[e["name"]] = rec
        finally:
            if tor is not None:
                await tor.stop()
    return out


def update(results: dict[str, dict], today: date, project_key: str = ec.PROJECT_KEY) -> dict:
    """Apply one day's results to entrances.json and entrance-health.json; the actions."""
    data = json.loads(ENTRANCES.read_text())
    health = load_health()
    actions = {"changed": False, "announce": False, "comments": [], "issues": [], "summary": []}
    if results and all(r["problems"] for r in results.values()):
        actions["summary"].append("Every entrance failed - probably the runner's network; "
                                  "nothing counted.")
        return actions
    keep = []
    for e in data["entrances"]:
        name = e["name"]
        res = results.get(name, {"problems": [], "changed": False, "outdated": False})
        entry = health["entrances"].setdefault(name, {})
        issue, who = entry.get("issue"), entry.get("requested_by")
        mention = f"@{who} " if who else ""
        ours = e.get("operator") == project_key

        def tell(title: str, text: str) -> None:
            if issue:
                actions["comments"].append({"issue": issue, "body": text})
            else:
                actions["issues"].append({"title": title, "body": text})

        if res["changed"]:
            listing = "\n".join(f"- {p}" for p in res["problems"])
            if ours:
                actions["summary"].append(f"{name}: SERVES CHANGED FILES (the project's own)")
                tell(f"Web entrance {name} serves changed files",
                     f"**{name}** serves files that differ from the signed web client.\n\n{listing}")
                keep.append(e)
                continue
            actions["announce"] = actions["changed"] = True
            health["entrances"].pop(name, None)
            actions["summary"].append(f"{name}: serves changed files - removed")
            tell(f"Web entrance {name} removed",
                 f"{mention}**{name}** serves files that differ from the signed web client, "
                 "so it has been taken off the list of web entrances at once (UN-RFC 0043 "
                 f"7.6).\n\n{listing}\n\nIf this was a mistake, fix it and ask again.")
            continue

        if not res["problems"]:
            if entry.get("first_failed"):
                actions["summary"].append(f"{name}: fine again after failing since "
                                          f"{entry['first_failed']}")
                if issue and entry.get("warned"):
                    actions["comments"].append({"issue": issue, "body":
                        f"{mention}**{name}** passes the daily check again - thank you."})
                for k in ("first_failed", "last_error", "warned"):
                    entry.pop(k, None)
                actions["changed"] = True
        else:
            if not entry.get("first_failed"):
                entry["first_failed"] = today.isoformat()
                actions["changed"] = True
            if entry.get("last_error") != res["problems"][0]:
                entry["last_error"] = res["problems"][0]
                actions["changed"] = True
            days = (today - date.fromisoformat(entry["first_failed"])).days
            actions["summary"].append(f"{name}: failing for {days} days - {res['problems'][0]}")
            listing = "\n".join(f"- {p}" for p in res["problems"])
            if days >= REMOVE_DAYS and not ours:
                actions["announce"] = actions["changed"] = True
                health["entrances"].pop(name, None)
                tell(f"Web entrance {name} removed",
                     f"{mention}**{name}** has failed the daily check for {days} days and has "
                     "been taken off the list of web entrances. When it is fixed, ask again "
                     f"with the *Add my entrance* form.\n\nProblems found today:\n\n{listing}")
                continue
            if days >= WARN_DAYS and not entry.get("warned"):
                entry["warned"] = True
                actions["changed"] = True
                after = ("" if ours else f" If it still fails after {REMOVE_DAYS} days, it is "
                         "taken off the list of web entrances.")
                tell(f"Web entrance {name} fails the daily check",
                     f"{mention}**{name}** has failed the daily check since "
                     f"{entry['first_failed']}.{after} See [running an entrance]({GUIDE})."
                     f"\n\nProblems found today:\n\n{listing}")

        if res["outdated"]:
            since = entry.setdefault("outdated_since", today.isoformat())
            if (today - date.fromisoformat(since)).days >= WARN_DAYS \
                    and not entry.get("told_outdated"):
                entry["told_outdated"] = True
                tell(f"Web entrance {name} serves an old web client",
                     f"{mention}**{name}** serves a version of the web client that is no "
                     "longer in the signed list. Nothing it serves is wrong, but visitors miss "
                     "the newer client: check that it updates itself "
                     "(`ENTRANCE_AUTO_UPDATE`, `python -m unseenet_entrance.release --install`).")
            actions["changed"] = True
        elif entry.pop("outdated_since", None) or entry.pop("told_outdated", None):
            entry.pop("told_outdated", None)
            actions["changed"] = True
        keep.append(e)

    if len(keep) != len(data["entrances"]):
        if not keep:                      # never publish an empty list
            actions["summary"].append("Would remove every entrance - keeping the list as it is.")
            actions["announce"] = False
        else:
            data["entrances"] = keep
            data["updated"] = today.isoformat()
            ENTRANCES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            parse_entrance_list(ENTRANCES.read_text())
    health["entrances"] = {n: v for n, v in health["entrances"].items() if v}
    HEALTH.write_text(json.dumps(health, indent=2, sort_keys=True) + "\n")
    return actions


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--actions", type=Path, required=True)
    p.add_argument("--today", help="YYYY-MM-DD (tests)")
    p.add_argument("--results", type=Path, help="use these results instead of checking (tests)")
    args = p.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    if args.results:
        results = json.loads(args.results.read_text())
    else:
        entrances = json.loads(ENTRANCES.read_text())["entrances"]
        results = asyncio.run(check_all(entrances))
    actions = update(results, today)
    args.actions.write_text(json.dumps(actions, indent=2))
    for line in actions["summary"] or ["All entrances passed."]:
        print(line)


if __name__ == "__main__":
    main()
