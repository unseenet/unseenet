"""Emoji for pickers (#362): categories, names, search, and GET /api/emoji."""
import pytest

from unseenet.core import markup

aiohttp = pytest.importorskip("aiohttp")

from unseenet.client.localapi import LocalAPI               # noqa: E402
from tests.test_localapi import Running, fast               # noqa: E402,F401


def test_categories_cover_the_table_once():
    table, cats, names = markup.emoji_table(), markup.emoji_categories(), markup.emoji_names()
    codes = [c for cat in cats for c in cat["codes"]]
    assert [c["name"] for c in cats][:2] == ["Smileys & Emotion", "People & Body"]
    assert len(codes) == len(set(codes)) == len(names)
    assert all(c in table for c in codes)
    glyphs = {table[c] for c in codes}
    assert glyphs == set(table.values())            # every emoji has a cell, once
    assert "party popper" in names["tada"]


@pytest.mark.parametrize("query, first", [
    ("ta", "taco"), (":tada", "tada"), ("TADA:", "tada"), ("thumbs", "thumbsup"), ("approve", "+1"), ("party", "tada"),
])
def test_find_emoji_order(query, first):
    found = markup.find_emoji(query, 20)
    assert first in found
    if query.strip(":").lower() in first:
        assert found.index(first) < 3


def test_find_emoji_one_per_glyph_and_limit():
    table = markup.emoji_table()
    found = markup.find_emoji("thumbsup", 50)
    glyphs = [table[c] for c in found]
    assert len(glyphs) == len(set(glyphs))
    assert len(markup.find_emoji("a", 5)) == 5
    assert markup.find_emoji("", 5) == [] and markup.find_emoji("::", 5) == []
    assert markup.find_emoji("zzzzqqq", 5) == []
    starts = markup.find_emoji("sm", 8)
    assert all(c.startswith("sm") for c in starts[:3])
    assert [len(c) for c in starts[:3]] == sorted(len(c) for c in starts[:3])


async def test_api_emoji_while_locked(tmp_path):
    async with Running(LocalAPI(tmp_path / "me.vault")) as r:
        status, body = await r.get("/api/emoji")
        assert status == 200
        assert body["table"]["tada"] == "🎉"
        assert body["categories"][0]["codes"][0] in body["table"]
        assert "party" in body["names"]["tada"]
        assert (await r.get("/api/emoji", token=False))[0] == 401
