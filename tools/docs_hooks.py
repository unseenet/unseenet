"""MkDocs hooks for the documentation site (see mkdocs.yml, ``hooks:``).

Puts the newest release, pre-release and development build into the header
lines at the top of the front page, where docs/index.md has the marker
``<!-- unseenet:versions -->``. They are looked up once per build, from the
GitHub API (with ``GITHUB_TOKEN`` if it is set), so the reader's browser
asks nobody. The docs workflow builds the site again after every release
and development build, which keeps the numbers current.

A pre-release (0.3.0a1) is shown only when it is newer than the release,
and the development build only when it is newer than both. Without a
network the versions come from the ``v*`` git tags and the development
build is left out. If nothing is known the marker just disappears.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import subprocess
import urllib.request
from datetime import datetime

log = logging.getLogger("mkdocs.hooks.unseenet")

REPO = "unseenet/unseenet"
MARKER = "<!-- unseenet:versions -->"
RELEASES = f"https://github.com/{REPO}/releases"

_lines: str | None = None


def _api_releases() -> list[dict]:
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases?per_page=30",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "unseenet-docs"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _day(stamp: str | None) -> str:
    if not stamp:
        return ""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).strftime("%-d %b %Y")
    except ValueError:
        return ""


def _version(text: str):
    from packaging.version import InvalidVersion, Version  # comes with mkdocs
    try:
        return Version(text)
    except InvalidVersion:
        return None


def versions() -> list[tuple[str, dict]]:
    """The header lines: [(label, {version, url, date})], newest last.

    Release is the newest full release; Pre-release (an alpha, beta or
    candidate, by its version number) and Development only when they are
    newer than everything above them - right after a release the dev build
    is the one from before it until the next is made.
    """
    found: list[dict] = []   # {version, url, date, kind}
    try:
        for r in _api_releases():
            if r.get("draft"):
                continue
            tag = r.get("tag_name", "")
            if tag == "dev":
                m = re.search(r"(\d+\.\d+\.\d+\S*)", r.get("name") or "")
                if m:
                    found.append({"version": m.group(1), "url": r["html_url"],
                                  "date": _day(r.get("published_at")), "kind": "dev"})
            elif re.fullmatch(r"v\d+\.\d+\.\d+\S*", tag):
                found.append({"version": tag[1:], "url": r["html_url"],
                              "date": _day(r.get("published_at")), "kind": "tag"})
    except Exception as exc:  # no network, rate limit: fall back to git
        log.info("unseenet: could not ask GitHub for releases (%s); using git", exc)
        for tag in _git_tags():
            found.append({"version": tag[1:], "url": f"{RELEASES}/tag/{tag}", "date": "", "kind": "tag"})

    def newest(items):
        items = [x for x in items if x["v"] is not None]
        return max(items, key=lambda x: x["v"]) if items else None

    for x in found:
        x["v"] = _version(x["version"])
    tags = [x for x in found if x["kind"] == "tag"]
    release = newest([x for x in tags if x["v"] and not x["v"].is_prerelease])
    pre = newest([x for x in tags if x["v"] and x["v"].is_prerelease])
    dev = newest([x for x in found if x["kind"] == "dev"])

    lines, top = [], None
    for label, item in (("Release", release), ("Pre-release", pre), ("Development", dev)):
        if item and (top is None or item["v"] > top):
            lines.append((label, item))
            top = item["v"]
    return lines


def _git_tags() -> list[str]:
    try:
        out = subprocess.run(["git", "tag", "--list", "v[0-9]*"],
                             capture_output=True, text=True, timeout=10, check=True)
        return out.stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []


def header_lines() -> str:
    out = []
    for label, item in versions():
        out.append(f'    <dt>{label}</dt><dd><a href="{html.escape(item["url"])}">'
                   f'{html.escape(item["version"])}</a>'
                   + (f' <span class="un-dim">{html.escape(item["date"])}</span>' if item["date"] else "")
                   + "</dd>")
    return "\n".join(out)


def on_page_markdown(markdown: str, page, config, files) -> str:
    global _lines
    if MARKER not in markdown:
        return markdown
    if _lines is None:
        _lines = header_lines()
        log.info("unseenet: front page versions: %s",
                 re.sub(r"<[^>]+>", "", _lines).replace("\n", "; ").strip() or "none")
    return markdown.replace(MARKER, _lines)
