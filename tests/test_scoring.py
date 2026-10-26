"""#615: your own rules for the feed and groups - the language, scores, the order, "Why?"."""
from unseenet.client import scoring as sc

NOW = 1_800_000_000.0
DAY = 86400


def post(i, **kw):
    kw.setdefault("when", NOW - 3600)
    kw.setdefault("group", "dk.snak")
    return sc.Post(id=f"<{i}@x>", **kw)


CTX = sc.Context(following=frozenset({"ed25519:mia"}), contacts=frozenset({"ed25519:mia", "ed25519:bo"}),
                 ignored=frozenset({"ed25519:troll"}), my_reactions={"ed25519:sonia": 7}, now=NOW)


def test_without_rules_nothing_changes():
    posts = [post(1, when=NOW - 3 * DAY), post(2, when=NOW - DAY), post(3, when=NOW - 2 * DAY)]
    assert [p.id for p, _ in sc.feed(sc.parse(""), posts, CTX)] == ["<2@x>", "<3@x>", "<1@x>"]
    th = [[post(1)], [post(2)]]
    assert [t[1][0][0].id for t in sc.threads(sc.parse(""), th, CTX)] == ["<1@x>", "<2@x>"]


def test_comments_and_case():
    rs = sc.parse("""VERSION 1
# why: I want my friends first
+10 IF Author IN Following   # friends
#-30 if seen                  taken out for now
+5 if subject matches "Kage # og kaffe"   # a # in quotes is text
""")
    assert not rs.problems and len(rs.rules) == 2
    r = sc.score(rs, post(1, author="ed25519:mia", subject="kage # OG KAFFE i dag"), CTX)
    assert r.score == 15 and [ln for ln, _, _ in r.why] == [3, 5]
    assert sc.score(rs, post(2, author="x", seen=True), CTX).score == 0     # the commented rule


def test_counters_and_caps():
    rs = sc.parse("+2 per time I reacted to author max 10\n+5 per contacts who reacted max 25\n"
                  "-1 per days old max 30")                     # plural works too
    p = post(1, author="ed25519:sonia", reacted_by=frozenset({"ed25519:mia", "ed25519:bo", "z"}),
             when=NOW - 40 * DAY)
    r = sc.score(rs, p, CTX)
    assert r.score == 10 + 10 - 30 and not rs.problems


def test_conditions():
    rs = sc.parse("""+1 if author in contacts and not seen
+2 if (from a bot or has pictures) and group is dk.*
+4 if older than 2 days
+8 if reactions >= 3
+16 if I posted in thread or thread in watched
+32 if author is "Mia"
""")
    assert not rs.problems
    ctx = sc.Context(contacts=frozenset({"ed25519:mia"}), watched_threads=frozenset({"<t@x>"}), now=NOW)
    p = post(1, author="ed25519:mia", author_name="Mia", pictures=True, when=NOW - 3 * DAY,
             reactions=3, thread="<t@x>")
    assert sc.score(rs, p, ctx).score == 63
    assert sc.score(rs, post(2, group="se.prat", seen=True), ctx).score == 0


def test_scopes():
    rs = sc.parse("""+1 if read
[feed]
+10 if read
[groups]
+100 if read
[dk.*]
+1000 if read
[all]
+5 if read
""")
    p = post(1, read=True)
    assert sc.score(rs, p, CTX, "feed").score == 1 + 10 + 1000 + 5
    assert sc.score(rs, p, CTX, "groups").score == 1 + 100 + 1000 + 5
    assert sc.score(rs, post(2, read=True, group="se.prat"), CTX, "groups").score == 106


def test_show_hide_and_sort_in_the_feed():
    rs = sc.parse("""+10 if author in following
-100 if author in ignored
show if score >= 0
sort by score, then date
""")
    posts = [post(1, author="a", when=NOW - 10), post(2, author="ed25519:mia", when=NOW - 99),
             post(3, author="ed25519:troll"), post(4, author="b", when=NOW - 5)]
    got = sc.feed(rs, posts, CTX)
    assert [p.id for p, _ in got] == ["<2@x>", "<4@x>", "<1@x>"]          # troll hidden
    hidden = sc.score(rs, posts[2], CTX)
    assert not hidden.shown and "hidden" in hidden.explain()


def test_threads_keep_their_order_inside():
    rs = sc.parse("""[groups]
+20 if I posted in thread
-50 if subject matches "politik"
fold if score < 0
highlight if score >= 20
mark read if thread in ignored
hide if author in ignored
sort by score
""")
    a = [post("a1", subject="kage"), post("a2", subject="re: kage", i_posted_in_thread=True)]
    b = [post("b1", subject="politik"), post("b2", subject="re: politik", author="ed25519:troll")]
    c = [post("c1", author="ed25519:troll")]
    out = sc.threads(rs, [b, a, c], CTX, "dk.snak")
    assert [t[1][0][0].id for t in out] == ["<a1@x>", "<b1@x>"]           # c: every post hidden
    assert [p.id for p, _ in out[0][1]] == ["<a1@x>", "<a2@x>"]           # the order inside kept
    assert out[0][0] == 20 and "highlight" in out[0][1][1][1].actions
    assert "fold" in out[1][1][0][1].actions and not out[1][1][1][1].shown


def test_problems_say_where_and_what():
    rs = sc.parse("""+10 if autor in following
+5 if author in friends
show score >= 0
fold if seen
+3 per banana
+1 if subject matches politik
+1 if subject matches "open
+20 if seen
""")
    msgs = {p.line: p.message for p in rs.problems}
    assert "did you mean 'author'" in msgs[1]
    assert "following | contacts | ignored" in msgs[2]
    assert "expected 'if'" in msgs[3] and "did you mean" not in msgs[3]
    assert "not something to count" in msgs[5]
    assert "text in quotes" in msgs[6] and 7 in msgs
    assert [r.line for r in rs.rules] == [4, 8]                     # the rest still work
    assert str(rs.problems[0]).startswith("line 1:")


def test_fold_is_for_groups_and_newer_versions_say_so():
    assert "not the feed" in sc.parse("[feed]\nfold if seen").problems[0].message
    rs = sc.parse("version 2\n+5 if moon is full\n+1 if seen")
    assert "written for version 2" in rs.problems[0].message and len(rs.rules) == 1


def test_limits():
    many = "\n".join("+1 if seen" for _ in range(sc.MAX_RULES + 3))
    rs = sc.parse(many)
    assert len(rs.rules) == sc.MAX_RULES and "more than" in rs.problems[0].message
    big = "+1 if seen   # " + "x" * 3000
    assert "bytes" in sc.parse(big).problems[0].message
    assert "more than" in sc.parse("+99999 if seen").problems[0].message


def test_why():
    rs = sc.parse("+10 if author in following\n-30 if seen\ndim if score < 0")
    r = sc.score(rs, post(1, author="ed25519:mia", seen=True), CTX, "groups")
    text = r.explain()
    assert "line 1: +10 if author in following  → +10" in text and "line 2: -30 if seen  → -30" in text
    assert "line 3: dim if score < 0" in text and text.endswith("score -20")


def test_the_help_names_every_word():
    """The help shown beside every client's editor names everything the language knows."""
    import re
    words = set(re.findall(r"[a-z]+", sc.HELP.lower()))
    for name in [*sc.COUNTERS, *sc.ACTIONS, *sc.SORT_KEYS, *sc.LISTS, *sc.THREAD_LISTS,
                 *sc.UNITS, "ascending", "matches", "pictures", "bot", "posted", "older", "newer",
                 "if", "per", "max", "and", "or", "not"]:
        for w in name.split():
            assert w in words or w + "s" in words, f"{w!r} is not in the help"
    for op in sc.OPS:
        assert op in sc.HELP
    assert max(len(line) for line in sc.HELP.splitlines()) <= 64       # fits beside an editor, no scrolling


def test_the_help_s_examples_are_rules():
    """Every example in the help is a rule the language understands."""
    import re
    starts = ("+", "-", "show ", "hide ", "sort ", "fold ", "dim ", "highlight ", "mark read ")
    examples = []
    for line in sc.HELP.splitlines():
        rule = re.split(r"\s{2,}(?=[a-z(])", line.strip(), maxsplit=1)[0]   # the rule, not the note
        if rule.startswith(starts) and not rule.startswith("-30 if seen  #"):
            examples.append(rule)
    assert len(examples) >= 10
    for rule in examples:
        rs = sc.parse(rule)
        assert not rs.problems and len(rs.rules) == 1, (rule, rs.problems)
    for cond in ("author in following", "from a bot", "older than 7 days", "score >= 10",
                 "group is dk.*", 'subject matches "text"', "new replies since seen"):
        assert not sc.parse(f"+1 if {cond}").problems, cond
