#!/usr/bin/env python3
"""Post the project's announcements to Unseenet, over Tor (used by GitHub Actions).

    python tools/announce.py nodes
        post src/unseenet/nodes.json to unseenet.nodes (UN-RFC 0010)
    python tools/announce.py hierarchies
        post src/unseenet/hierarchies.json to unseenet.hierarchies (UN-RFC 0018)
    python tools/announce.py checkgroups
        post src/unseenet/checkgroups.json, the project's list of its groups,
        to unseenet.checkgroups (UN-RFC 0018 section 5)
    python tools/announce.py release v0.2.0
        post that version's CHANGELOG section to unseenet.announce, as Markdown
        (UN-RFC 0031): a title, the notes, and where to get it (#611)
    python tools/announce.py repos [--since 2026-10-29T00:00:00Z] [--until ...] [--latest-only]
        post the stable releases of the clients, builds and services (OTHER_REPOS) that
        came since the last successful hourly run to unseenet.announce, one post each,
        with the same frame as the core's (announce-repos.yml)
    python tools/announce.py message --subject "..." --body-file text.md
        post anything to unseenet.announce, as Markdown
    python tools/announce.py client-release dev SHA256SUMS.txt SHA256SUMS.txt.sig
        post a build's signed checksums to unseenet.releases, where clients learn
        that it exists (#264); the signature is checked first
    --dry-run  build and sign the article, print it, post nothing

The signing key comes from the environment, as a hex seed:
UNSEENET_ANNOUNCE_SEED. It is a *poster* in the project's channel groups, listed in
their manifests by the project key, which owns them and never leaves the
project's own vault. If this key leaks, the owner removes it from the
manifests and makes a new one; the groups and the project key are not at risk.

The article is posted to every known node that answers (the nodes replicate
it anyway; a duplicate is fine), so one node being down does not matter.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from unseenet.core import crypto  # noqa: E402
from unseenet.core import markup  # noqa: E402
from unseenet.core.poster import Poster  # noqa: E402
from unseenet.hierarchies import (CHECKGROUPS_GROUP, HIERARCHIES_GROUP,  # noqa: E402
                                  parse_hierarchy_list, parse_root_list)
from other_releases import OTHER_REPOS, default_since, new_releases  # noqa: E402
from unseenet.known_nodes import ANNOUNCE_GROUP, ENTRANCES_GROUP, NODES_GROUP, RELEASES_GROUP, parse_entrance_list, parse_node_list  # noqa: E402

FROM = "Unseenet project"
REPO = "https://github.com/unseenet/unseenet"
GROUP_MIN_POW = 20


def is_test_release(version: str) -> bool:
    """An alpha, beta or release candidate (PEP 440), e.g. 0.2.1a1."""
    return re.search(r"\d(a|b|rc)\d+$", version) is not None


def changelog_section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m and is_test_release(version):      # its notes are what is not released yet
        m = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m:
        sys.exit(f"CHANGELOG.md has no section for {version}")
    return m.group(1).strip() + "\n"


# Markdown for the clients (UN-RFC 0031, #611): issue references become links, the
# changelog's headings fit under the post's own title, and a section too long for a post
# becomes its lead and a link to the whole of it.
_CODE = re.compile(r"(```.*?```|`[^`\n]*`)", re.S)
_ISSUE = re.compile(r"(?<![\w#/\[`.-])((?:(?:unseenet/)?(unseenet(?:-[a-z]+)*))?#(\d+))(?![\w\]])")
_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")
MAX_BODY = markup.MAX_TEXT - 8 * 1024            # room for the frame around the notes


def link_issues(text: str, repo: str = "unseenet") -> str:
    """``#518`` and ``unseenet/unseenet-gui#237`` as links to the issue - not inside code or
    an existing link. A bare ``#518`` is an issue of ``repo``, whose notes these are."""
    def link(m: re.Match) -> str:
        return _issue_link(m, repo)

    def outside(part: str) -> str:
        pieces, last = [], 0
        for m in _LINK.finditer(part):                       # leave [text](url) alone
            pieces.append(_ISSUE.sub(link, part[last:m.start()]))
            pieces.append(m.group(0))
            last = m.end()
        pieces.append(_ISSUE.sub(link, part[last:]))
        return "".join(pieces)
    out = []
    for i, part in enumerate(_CODE.split(text)):
        out.append(part if i % 2 else outside(part))
    return "".join(out)


def _issue_link(m: re.Match, default: str = "unseenet") -> str:
    repo = m.group(2) or default
    return f"[{m.group(1)}](https://github.com/unseenet/{repo}/issues/{m.group(3)})"


def fit_headings(text: str) -> str:
    """The changelog's ``### Added`` under the post's ``#`` title: one level up, so the
    levels go # title, ## Added, ## Get it - never deeper than the renderer's 3."""
    def up(m: re.Match) -> str:
        level = max(2, min(markup.MAX_HEADING, len(m.group(1)) - 1))
        return "#" * level + " "
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        out.append(line if fenced else re.sub(r"^(#{2,6})\s+", up, line))
    return "\n".join(out)


def notes_markdown(version: str, tag: str) -> str:
    """The changelog section for ``version`` as the post's middle: links, headings, and
    no longer than a post may be (UN-RFC 0031 MAX_TEXT)."""
    notes = fit_headings(link_issues(changelog_section(version)))
    if len(notes.encode("utf-8")) > MAX_BODY:            # the lead, and the rest by link
        lead = notes.split("\n## ", 1)[0].rstrip()
        notes = (lead + f"\n\nThe notes are too long for one post: the whole of them are in "
                 f"[CHANGELOG.md]({REPO}/blob/{tag}/CHANGELOG.md).\n")
    return notes


def release_post(tag: str) -> tuple[str, str]:
    """The release post for ``unseenet.announce``: Markdown, a title, the notes and where to
    get it (#611)."""
    version = tag.lstrip("v")
    notes = notes_markdown(version, tag)
    get = (f"## Get it\n\n"
           f"- **Portable and bootable** (Tor inside; Windows, macOS, Linux; the all-in-one "
           f"USB zip): [release {version}]({REPO}/releases/tag/{tag}) - check them against "
           f"`SHA256SUMS.txt` on the same page\n")
    if is_test_release(version):
        body = (f"# Unseenet {version}\n\n"
                f"> **A test release:** please try it and report what you find. For everyday "
                f"use, stay with the newest full release.\n\n"
                f"{notes}\n---\n\n{get}"
                f"- **With Python:** `pipx install --pip-args=--pre unseenet-tui`\n"
                f"- **Full changelog:** [CHANGELOG.md]({REPO}/blob/{tag}/CHANGELOG.md)\n")
        return f"Unseenet {version} - test release", body
    first = "" if "update the nodes first" in notes.lower()[:600] else \
        "**Update the nodes first, then the clients.**\n\n"
    body = (f"# Unseenet {version}\n\n{first}{notes}\n---\n\n{get}"
            f"- **With Python:** `pipx upgrade unseenet-tui` (or `pipx install unseenet-tui`)\n"
            f"- **Full changelog:** [CHANGELOG.md]({REPO}/blob/{tag}/CHANGELOG.md)\n")
    return f"Unseenet {version} released", body


# The releases of the other repositories people download (the clients, the builds and the
# services; OTHER_REPOS in other_releases.py): announce-repos.yml looks every hour and
# posts each new stable release with the same frame as the core's.
ORG = "https://github.com/unseenet"


def repo_release_post(repo: str, r: dict) -> tuple[str, str]:
    """A release of one of OTHER_REPOS, for ``unseenet.announce``: the same Markdown frame
    as the core's, with the release's own notes (from its CHANGELOG)."""
    name, tag = OTHER_REPOS[repo], r["tag_name"]
    version = tag.lstrip("v")
    notes = fit_headings(link_issues((r.get("body") or "").strip(), repo)).strip()
    if len(notes.encode("utf-8")) > MAX_BODY:
        notes = (notes.split("\n## ", 1)[0].rstrip()[:MAX_BODY // 2]
                 + f"\n\nThe notes are too long for one post: the whole of them are on the "
                 f"[release page]({r['html_url']}).")
    body = (f"# {name} {version}\n\n{notes or 'No notes for this release.'}\n\n---\n\n"
            f"## Get it\n\n- **Release page:** [{repo} {version}]({r['html_url']})\n"
            f"- **Full changelog:** [CHANGELOG.md]({ORG}/{repo}/blob/{tag}/CHANGELOG.md)\n")
    return f"{name} {version} released", body


def nodes_post() -> tuple[str, str]:
    text = (ROOT / "src" / "unseenet" / "nodes.json").read_text(encoding="utf-8")
    updated, nodes = parse_node_list(text)          # never post a list clients would reject
    return f"Known nodes, {updated} ({len(nodes)})", text if text.endswith("\n") else text + "\n"


def entrances_post() -> tuple[str, str]:
    text = (ROOT / "src" / "unseenet" / "entrances.json").read_text(encoding="utf-8")
    updated, entrances = parse_entrance_list(text)   # never post a list clients would reject
    return f"Known web entrances, {updated} ({len(entrances)})", text if text.endswith("\n") else text + "\n"


def hierarchies_post() -> tuple[str, str]:
    text = (ROOT / "src" / "unseenet" / "hierarchies.json").read_text(encoding="utf-8")
    updated, entries = parse_root_list(text, strict=True)   # never post a list with mistakes
    return f"Hierarchies, {updated} ({len(entries)})", text if text.endswith("\n") else text + "\n"


def checkgroups_post() -> tuple[str, str]:
    text = (ROOT / "src" / "unseenet" / "checkgroups.json").read_text(encoding="utf-8")
    lst = parse_hierarchy_list(text, "unseenet")
    data = json.loads(text)
    if len(lst.groups) != len(data["groups"]):          # never post a list with mistakes
        raise SystemExit("checkgroups.json has an entry that does not count")
    return f"Groups of unseenet, {lst.updated} ({len(lst.groups)})", text if text.endswith("\n") else text + "\n"


# what people read is Markdown (#611); lists and release checksums are read by programs
MARKDOWN_POSTS = ("release", "message")


async def post_everywhere(group: str, subject: str, body: str, key: crypto.Identity,
                          addresses: list[str], dry_run: bool,
                          content_type: str = markup.PLAIN_TYPE) -> int:
    """Post to every node that answers, through the core's headless API (#166)."""
    poster = Poster(key, addresses, from_name=FROM, tor="own",
                    log=lambda msg: print("  " + msg, flush=True))
    art = poster.build(group, subject, body, content_type=content_type)
    if dry_run:
        print(art.finalize(key, 8).to_bytes().decode())
        return 0
    async with poster:
        result = await poster.post_article(art, GROUP_MIN_POW)
    return len(result.accepted)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=["nodes", "entrances", "hierarchies", "checkgroups", "release", "message",
                                    "client-release", "repos"])
    p.add_argument("tag", nargs="?", help="release: the tag, e.g. v0.2.0; client-release: the channel")
    p.add_argument("files", nargs="*", type=Path, help="client-release: SHA256SUMS.txt and its .sig")
    p.add_argument("--subject")
    p.add_argument("--body-file", type=Path)
    p.add_argument("--since", help="repos: releases after this time (ISO 8601); "
                   "default: the last successful run, or an hour ago")
    p.add_argument("--until", default="9999", help="repos: and published up to this time")
    p.add_argument("--latest-only", action="store_true", help="repos: only the newest per repository")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.what == "repos":
        return post_repos(args)

    if args.what == "nodes":
        group, (subject, body) = NODES_GROUP, nodes_post()
    elif args.what == "entrances":
        group, (subject, body) = ENTRANCES_GROUP, entrances_post()
    elif args.what == "hierarchies":
        group, (subject, body) = HIERARCHIES_GROUP, hierarchies_post()
    elif args.what == "checkgroups":
        group, (subject, body) = CHECKGROUPS_GROUP, checkgroups_post()
    elif args.what == "release":
        if not args.tag:
            sys.exit("release needs the tag")
        group, (subject, body) = ANNOUNCE_GROUP, release_post(args.tag)
    elif args.what == "client-release":
        from unseenet import update
        if args.tag not in ("stable", "dev") or len(args.files) != 2:
            sys.exit("client-release needs the channel, SHA256SUMS.txt and SHA256SUMS.txt.sig")
        group = RELEASES_GROUP
        subject, body = update.release_post(args.files[0].read_bytes(), args.files[1].read_text(encoding="utf-8"), args.tag)
    else:
        if not (args.subject and args.body_file):
            sys.exit("message needs --subject and --body-file")
        body = args.body_file.read_text(encoding="utf-8")
        group, subject, body = ANNOUNCE_GROUP, args.subject, body if body.endswith("\n") else body + "\n"

    key = announce_key(args.dry_run)
    print(f"Posting as {key.key_text} to {group}: {subject}", flush=True)
    ctype = markup.MARKDOWN_TYPE if args.what in MARKDOWN_POSTS else markup.PLAIN_TYPE
    ok = asyncio.run(post_everywhere(group, subject, body, key, node_addresses(), args.dry_run, ctype))
    if not args.dry_run and ok == 0:
        sys.exit("no node took the post")


def announce_key(dry_run: bool) -> crypto.Identity:
    seed = os.environ.get("UNSEENET_ANNOUNCE_SEED", "").strip()
    if dry_run and not seed:
        return crypto.Identity.generate()
    if not seed:
        sys.exit("UNSEENET_ANNOUNCE_SEED is not set")
    return crypto.Identity.from_seed(bytes.fromhex(seed))


def node_addresses() -> list[str]:
    _, nodes = parse_node_list((ROOT / "src" / "unseenet" / "nodes.json").read_text(encoding="utf-8"))
    return [n.address for n in nodes]


def post_repos(args) -> None:
    """``repos``: each new stable release of OTHER_REPOS as its own post."""
    since = args.since or default_since()
    found = new_releases(since, args.latest_only, until=args.until)
    print(f"{len(found)} new release(s) since {since}", flush=True)
    if not found:
        return
    key, addresses, failed = announce_key(args.dry_run), node_addresses(), []
    for repo, r in found:
        subject, body = repo_release_post(repo, r)
        print(f"Posting as {key.key_text} to {ANNOUNCE_GROUP}: {subject}", flush=True)
        ok = asyncio.run(post_everywhere(ANNOUNCE_GROUP, subject, body, key, addresses,
                                         args.dry_run, markup.MARKDOWN_TYPE))
        if not args.dry_run and ok == 0:
            failed.append(subject)
    if failed:                       # the run fails, so the next one tries them again
        sys.exit("no node took: " + "; ".join(failed))


if __name__ == "__main__":
    main()
