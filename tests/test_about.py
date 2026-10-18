"""The plain-words "About Unseenet" text every client shows (core/about.py)."""

import json

from unseenet.core import about


def test_every_section_has_text():
    for s in (*about.SECTIONS, about.STATUS):
        assert s.title and s.paragraphs and all(p.strip() for p in s.paragraphs)
    assert {c.name for c in about.COMPARISONS} >= {"Discord", "Matrix", "Nostr", "The old Usenet"}


def test_says_honestly_where_it_stands():
    status = " ".join(about.STATUS.paragraphs)
    assert "pre-alpha" in status and "security review" in status
    assert about.STATUS.title in about.as_text()           # never left out of a client


def test_as_dict_is_json_and_complete():
    d = json.loads(json.dumps(about.as_dict("1.2.3")))
    assert d["version"] == "1.2.3" and d["links"]["source"] == about.REPO_URL
    assert len(d["sections"]) == len(about.SECTIONS)
    assert len(d["comparisons"]["items"]) == len(about.COMPARISONS)
