"""The release post in unseenet.announce is Markdown (#611): a title, the notes with
issue links and headings that fit, where to get it - and it renders in the clients."""
import importlib.util
import json
from pathlib import Path

from unseenet.core import markup

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("announce", ROOT / "tools" / "announce.py")
announce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(announce)


def test_issue_links_not_in_code_or_links():
    text = ("Fixed (#518), see unseenet/unseenet-gui#237 and unseenet-tui#90; "
            "`#12 in code`, [#7](https://x) and a heading #nope.")
    out = announce.link_issues(text)
    assert "[#518](https://github.com/unseenet/unseenet/issues/518)" in out
    assert "[unseenet/unseenet-gui#237](https://github.com/unseenet/unseenet-gui/issues/237)" in out
    assert "[unseenet-tui#90](https://github.com/unseenet/unseenet-tui/issues/90)" in out
    assert "`#12 in code`" in out and "[#7](https://x)" in out and "#nope" in out


def test_headings_fit_under_the_title():
    out = announce.fit_headings("### Added\n- x\n#### Deeper\n```\n### not a heading\n```")
    assert out.splitlines()[:3] == ["## Added", "- x", "### Deeper"]
    assert "### not a heading" in out                          # inside code: left alone


def test_release_post_is_markdown_that_renders():
    subject, body = announce.release_post("v0.5.0")
    assert subject == "Unseenet 0.5.0 released"
    assert body.startswith("# Unseenet 0.5.0\n")
    assert "## Get it" in body and "releases/tag/v0.5.0" in body
    assert "pipx upgrade unseenet-tui" in body
    assert len(body.encode()) <= markup.MAX_TEXT
    tree = markup.body(body, markup.MARKDOWN_TYPE, "post")
    flat = json.dumps(tree)
    assert '"t": "h"' in flat
    assert "https://github.com/unseenet/unseenet/issues/518" in flat
    levels = [n["n"] for n in tree if n.get("t") == "h"]
    assert levels[0] == 1 and 2 in levels and max(levels) <= markup.MAX_HEADING


def test_test_release_says_so(monkeypatch):
    monkeypatch.setattr(announce, "changelog_section", lambda v: "- **Something** (#1)\n")
    subject, body = announce.release_post("v0.6.0rc1")
    assert subject.endswith("test release") and "> **A test release:**" in body
    assert "--pre" in body
    assert body.startswith("# Unseenet 0.6.0rc1")


def test_a_too_long_section_becomes_its_lead(monkeypatch):
    long = "**Lead line.**\n\n### Added\n\n" + ("- a line of notes\n" * 30000)
    monkeypatch.setattr(announce, "changelog_section", lambda v: long)
    _, body = announce.release_post("v9.9.9")
    assert "too long for one post" in body and len(body.encode()) <= markup.MAX_TEXT
    assert "**Update the nodes first" in body


def test_people_read_markdown_programs_read_plain():
    assert announce.MARKDOWN_POSTS == ("release", "message")


# The other repositories' releases (announce-repos.yml)
def _rel(tag, at, **kw):
    return {"tag_name": tag, "published_at": at, "html_url": f"https://github.com/unseenet/x/releases/tag/{tag}",
            "body": f"Notes for {tag} (#12).", **kw}


def _fetch(path):
    if "/actions/workflows/" in path:
        return {"workflow_runs": [{"run_started_at": "2026-10-29T10:00:00Z"}]}
    if path.startswith("/repos/unseenet/unseenet-gui/"):
        return [_rel("v0.3.1", "2026-10-29T15:57:29Z"), _rel("v0.3.0", "2026-10-29T10:58:43Z"),
                _rel("v0.2.0", "2026-10-25T12:52:17Z"), _rel("v0.4.0a1", "2026-10-29T12:00:00Z"),
                _rel("v0.4.0", "2026-10-29T12:00:00Z", draft=True)]
    if path.startswith("/repos/unseenet/unseenet-entrance/"):
        return [_rel("web-20261029.1904", "2026-10-29T19:05:05Z"),
                _rel("dev", "2026-10-29T13:00:00Z", prerelease=True)]
    if path.startswith("/repos/unseenet/unseenet-portable/"):
        return [_rel("v0.6.3.post1", "2026-10-29T19:18:36Z")]
    return []


def test_other_releases_only_stable_ones_in_the_window():
    since = announce.default_since(_fetch)
    assert since == "2026-10-29T10:00:00Z"
    got = announce.new_releases(since, fetch=_fetch, until="2026-10-29T19:00:00Z")
    assert [(r, x["tag_name"]) for r, x in got] == [("unseenet-gui", "v0.3.0"), ("unseenet-gui", "v0.3.1")]
    got = announce.new_releases(since, latest_only=True, fetch=_fetch)
    assert [(r, x["tag_name"]) for r, x in got] == [("unseenet-gui", "v0.3.1"), ("unseenet-portable", "v0.6.3.post1")]


def test_other_release_post_has_the_same_frame_and_links_its_own_issues():
    subject, body = announce.repo_release_post("unseenet-gui", _rel("v0.3.1", "2026-10-29T15:57:29Z"))
    assert subject == "Unseenet graphical client 0.3.1 released"
    assert body.startswith("# Unseenet graphical client 0.3.1\n\nNotes for v0.3.1")
    assert "[#12](https://github.com/unseenet/unseenet-gui/issues/12)" in body
    assert "## Get it" in body and "/unseenet-gui/blob/v0.3.1/CHANGELOG.md" in body
    tree = markup.body(body, markup.MARKDOWN_TYPE, "post")
    assert "https://github.com/unseenet/unseenet-gui/issues/12" in json.dumps(tree)
    assert [n["n"] for n in tree if n.get("t") == "h"] == [1, 2]
