"""MkDocs hooks for the documentation site (see mkdocs.yml, ``hooks:``).

Puts the newest release and the newest development build into the header
lines at the top of the front page, where docs/index.md has the marker
``<!-- unseenet:versions -->``. They are looked up once per build, from the
GitHub API (with ``GITHUB_TOKEN`` if it is set), so the reader's browser
asks nobody. The docs workflow builds the site again after every release
and development build, which keeps the numbers current.

Without a network the release comes from the newest ``v*`` git tag and the
development build is left out, as it is when it is not newer than the
release (right after a release). If neither is known the marker just
disappears.
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


def _git_release() -> str | None:
    try:
        out = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"],
                             capture_output=True, text=True, timeout=10, check=True)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _day(stamp: str | None) -> str:
    if not stamp:
        return ""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).strftime("%-d %b %Y")
    except ValueError:
        return ""


def versions() -> tuple[dict | None, dict | None]:
    """(newest release, newest development build), each {version, url, date}."""
    release = dev = None
    try:
        for r in _api_releases():
            if r.get("draft"):
                continue
            tag = r.get("tag_name", "")
            if tag == "dev" and dev is None:
                m = re.search(r"(\d+\.\d+\.\d+\S*)", r.get("name") or "")
                if m:
                    dev = {"version": m.group(1), "url": r["html_url"],
                           "date": _day(r.get("published_at"))}
            elif re.fullmatch(r"v\d+\.\d+\.\d+\S*", tag) and release is None:
                release = {"version": tag[1:], "url": r["html_url"],
                           "date": _day(r.get("published_at")),
                           "pre": bool(r.get("prerelease"))}
    except Exception as exc:  # no network, rate limit: fall back to git
        log.info("unseenet: could not ask GitHub for releases (%s); using git", exc)
        tag = _git_release()
        if tag:
            release = {"version": tag[1:], "url": f"{RELEASES}/tag/{tag}", "date": "", "pre": False}
    return release, dev


def _newer(dev: dict, release: dict) -> bool:
    """Whether the development build is newer than the release (right after a
    release, the dev build is older until the next one is made)."""
    try:
        from packaging.version import Version  # comes with mkdocs
        return Version(dev["version"]) > Version(release["version"])
    except Exception:
        return True


def header_lines() -> str:
    release, dev = versions()
    if dev and release and not _newer(dev, release):
        dev = None
    out = []
    if release:
        note = " ".join(x for x in (release["date"],) if x)
        out.append(f'    <dt>Release</dt><dd><a href="{html.escape(release["url"])}">'
                   f'{html.escape(release["version"])}</a>'
                   + (f' <span class="un-dim">{html.escape(note)}</span>' if note else "")
                   + "</dd>")
    if dev:
        out.append(f'    <dt>Development</dt><dd><a href="{html.escape(dev["url"])}">'
                   f'{html.escape(dev["version"])}</a>'
                   + (f' <span class="un-dim">{html.escape(dev["date"])}</span>' if dev["date"] else "")
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
