"""The plain-words "About Unseenet" text every client shows (core/about.py)."""

import json

from unseenet.core import about


def test_every_section_has_text():
    for s in (*about.SECTIONS, about.STATUS):
        assert s.title and s.paragraphs and all(p.strip() for p in s.paragraphs)
    assert {c.name for c in about.COMPARISONS} >= {"Discord", "Matrix", "Nostr", "The old Usenet"}


def test_says_it_does_chat_discussion_and_private_posts():
    # What sets Unseenet apart in everyday terms comes right after "What is Unseenet?"
    second = about.SECTIONS[1]
    text = " ".join(second.paragraphs)
    assert "chat" in second.title.lower() and "discussion" in second.title.lower()
    assert "private posts" in text and "quoting" in text


def test_says_honestly_where_it_stands():
    status = " ".join(about.STATUS.paragraphs)
    assert "pre-alpha" in status and "security review" in status
    assert about.STATUS.title in about.as_text()           # never left out of a client
    titles = [s.title for s in about.SECTIONS]
    assert "The other side of the coin" in titles          # the price is said, not hidden


def test_as_dict_is_json_and_complete():
    d = json.loads(json.dumps(about.as_dict("1.2.3")))
    assert d["version"] == "1.2.3" and d["links"]["source"] == about.REPO_URL
    assert len(d["sections"]) == len(about.SECTIONS)
    assert len(d["comparisons"]["items"]) == len(about.COMPARISONS)
