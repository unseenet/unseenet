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
