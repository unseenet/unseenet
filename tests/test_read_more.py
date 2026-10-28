"""UN-RFC 0031 section 3.2.1 (#668): the author's read-more line - where "... more" cuts."""

from unseenet.core import markup


def test_the_first_read_more_line_splits_a_post():
    text = "Første afsnit.\n\n...\n\nResten her.\n\n...\n\nOg mere."
    assert markup.read_more(text) == ("Første afsnit.", "Resten her.\n\n...\n\nOg mere.")
    assert markup.read_more("Kort.\n  …  \nMere.") == ("Kort.", "Mere.")


def test_what_is_not_a_read_more_line():
    assert markup.read_more("Ingen her.\n\nSlut.") is None
    assert markup.read_more("Først ... midt i\nen linje") is None
    assert markup.read_more("En linje\n\n    ...\n\nkode") is None              # indented code
    assert markup.read_more("```\n...\n```\nefter") is None                       # fenced code
    assert markup.read_more("> citat\n...\n\nefter") is None                      # lazy quote line
    assert markup.read_more("> ...") is None
    assert markup.read_more("....") is None and markup.read_more(". . .") is None
    assert markup.read_more("Hej\n...\nmere", kind="chat") is None               # not chat lines
    assert markup.read_more("```\nkode\n```\n...\nmere") == ("```\nkode\n```", "mere")


def test_the_tree_marks_the_place():
    md = "text/markdown; charset=utf-8; variant=unseenet"
    tree = markup.body("**Kort** indledning\n\n...\n\nResten", md)
    assert [b["t"] for b in tree] == ["p", "more", "p"]
    assert [b["t"] for b in markup.body("Kort\n...\nResten", None)] == ["p", "more", "p"]
    assert [b["t"] for b in markup.body("Kun indledning\n...", None)] == ["p", "more"]
    assert "more" not in [b["t"] for b in markup.body("Hej\n...\nmere", md, kind="chat")]
    assert "more" not in [b["t"] for b in markup.body("Ingen", md)]
