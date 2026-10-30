"""#781: long entries and comments in a feed are cut by one shared rule (markup.preview),
offered by the local API (?preview=ENTRY,COMMENT,WIDTH) and the CLI's timeline, so the
terminal and the graphical client cut alike (UN-RFC 0034 section 4.2 as amended)."""
from unseenet.core import markup as mk

from test_localapi_owner import _setup

LONG = " ".join(f"Sentence number {i} is here." for i in range(60))


def test_cut_at_a_sentence_with_a_mark():
    p = mk.preview(LONG, lines=3, width=40)
    assert p["cut"] and not p["read_more"]
    assert p["text"].endswith("is here.") and len(p["text"]) <= 3 * 40
    assert p["tree"] and p["tree"][0]["t"] == "p"


def test_not_cut_for_a_line_or_two():
    five = "\n".join("line" for _ in range(5))
    assert mk.preview(five, lines=3, width=40) == {**mk.preview(five, lines=3, width=40), "cut": False, "text": five}
    assert mk.preview("\n".join("x" for _ in range(6)), lines=3, width=40)["cut"]


def test_the_read_more_line_decides_within_twice_the_cut():
    near = "Intro\n\n...\n\nThe rest"
    assert mk.preview(near, lines=3) | {"tree": None} == {"text": "Intro", "cut": True, "read_more": True, "tree": None}
    far = "\n".join(f"line {i}" for i in range(10)) + "\n...\nrest"
    p = mk.preview(far, lines=3, width=40)                  # below twice the cut: ignored
    assert p["cut"] and not p["read_more"] and "line 9" not in p["text"]


def test_a_comment_starts_with_its_own_words():
    q = "Sonia wrote:\n> what she said\n> more of it\n\nMy own words."
    p = mk.preview(q, lines=3, quotes=False)
    assert p["text"] == "My own words." and p["cut"]       # the quote is left out: opened shows it
    assert mk.preview("> only a quote", quotes=False)["text"] == "> only a quote"
    assert mk.preview(q, lines=3)["text"] == q             # an entry keeps what it quotes


def test_never_inside_a_link_a_code_block_or_a_table():
    link = "word " * 30 + "[a link text](https://example.org/very/long/path) and more " * 3
    shown = mk.preview(link, lines=2, width=72)["text"]
    assert shown.count("[") == shown.count("](") == shown.count(")")      # no half link
    code = "Start\n```\n" + "\n".join(f"code {i}" for i in range(20)) + "\n```\nAfter"
    assert mk.preview(code, lines=4)["text"] == "Start"
    table = "Top\n| a | b |\n|---|---|\n" + "\n".join(f"| {i} | x |" for i in range(10))
    assert mk.preview(table, lines=4)["text"] == "Top"


def test_a_chat_line_is_never_cut():
    assert not mk.preview(LONG, kind="chat", lines=1)["cut"]


async def test_the_local_api_gives_each_feed_row_its_cut(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.start_feed({"comments": "open"}))["id"]
    entry = await owner.post(gid, "", LONG + "\n", kind="chat")
    await owner.post(gid, "", "Owner wrote:\n> " + LONG[:60] + "\n\n" + LONG + "\n", kind="chat",
                     references=[entry])
    await owner.fetch_group(gid)
    rows = api.group(gid, preview=(6, 3, 60))["rows"]
    top, comment = rows[0], rows[1]
    assert top["depth"] == 0 and top["preview"]["cut"] and top["preview"]["text"].endswith(".")
    assert comment["depth"] == 1 and comment["preview"]["text"].startswith("Sentence number 0")
    assert len(comment["preview"]["text"]) < len(top["preview"]["text"])          # a shorter cut
    assert all("preview" not in r for r in api.group(gid)["rows"])                 # only when asked
    for s in (owner, other):
        await s.close()
    server.close()
