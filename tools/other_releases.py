#!/usr/bin/env python3
"""The new stable releases of the clients, builds and services people download - the
other repositories, whose releases ``tools/announce.py repos`` posts to unseenet.announce.

Standard library only, so announce-repos.yml can look every hour without installing
anything, and install the core and Tor only when there is something to post:

    python tools/other_releases.py            # prints since=... and count=... for $GITHUB_OUTPUT
    python tools/other_releases.py --since 2026-10-29T00:00:00Z --latest-only

The help bot (and stats) only run at the project, so they are not here; the help bot
retells all releases in plain language in unseenet.help.news.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

OTHER_REPOS = {
    "unseenet-gui": "Unseenet graphical client",
    "unseenet-tui": "Unseenet terminal client",
    "unseenet-portable": "Unseenet portable",
    "unseenet-bootable": "Unseenet bootable images",
    "unseenet-entrance": "Unseenet web entrance",
    "unseenet-gateway": "Unseenet gateway",
    "unseenet-bots": "Unseenet bots",
    "unseenet-watchman": "Unseenet watchman",
}
_STABLE_TAG = re.compile(r"^v\d+(\.\d+)*(\.post\d+)?$")       # no dev, web-..., a/b/rc


def stable_release(r: dict) -> bool:
    return (not r.get("draft") and not r.get("prerelease")
            and bool(_STABLE_TAG.match(r.get("tag_name", ""))))


def github(path: str) -> object:
    req = urllib.request.Request("https://api.github.com" + path,
                                 headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def last_success(fetch=github) -> str | None:
    """When the last successful run of announce-repos.yml started: releases after it are new."""
    repo = os.environ.get("GITHUB_REPOSITORY", "unseenet/unseenet")
    runs = fetch(f"/repos/{repo}/actions/workflows/announce-repos.yml/runs?status=success&per_page=1")
    got = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
    return got[0]["run_started_at"] if got else None


def default_since(fetch=github) -> str:
    """Since the last successful run, or an hour ago the very first time."""
    return last_success(fetch) or \
        (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def this_run_started(fetch=github) -> str:
    """When this run started: the end of what it counts, and where the next run begins,
    so a release is counted by exactly one run."""
    run = os.environ.get("GITHUB_RUN_ID")
    if run:
        repo = os.environ.get("GITHUB_REPOSITORY", "unseenet/unseenet")
        return fetch(f"/repos/{repo}/actions/runs/{run}")["run_started_at"]
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_releases(since: str, latest_only: bool = False, fetch=github,
                 until: str = "9999") -> list[tuple[str, dict]]:
    """The stable releases of OTHER_REPOS published after ``since`` and up to ``until``
    (ISO 8601), oldest first."""
    out = []
    for repo in OTHER_REPOS:
        rels = [r for r in fetch(f"/repos/unseenet/{repo}/releases?per_page=20")
                if stable_release(r) and since < (r.get("published_at") or "") <= until]
        rels.sort(key=lambda r: r["published_at"])
        out += [(repo, r) for r in (rels[-1:] if latest_only else rels)]
    return sorted(out, key=lambda x: x[1]["published_at"])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since")
    p.add_argument("--latest-only", action="store_true")
    args = p.parse_args()
    since, until = args.since or default_since(), this_run_started()
    found = new_releases(since, args.latest_only, until=until)
    print(f"since={since}")
    print(f"until={until}")
    print(f"count={len(found)}")
    for repo, r in found:
        print(f"{repo} {r['tag_name']} {r['published_at']}", file=sys.stderr)


if __name__ == "__main__":
    main()
