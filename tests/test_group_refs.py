"""#172, UN-RFC 0031 3.4.2: groups named in a text with ! (# is a tag, UN-RFC 0052)."""

from unseenet.core import tags as tg
from unseenet.core.groups import GroupRef, group_refs


def names(text):
    return [r.text for r in group_refs(text)]


def test_group_refs_found():
    assert names("Spørg i !dk.snak.marsvin, de ved det.") == ["!dk.snak.marsvin"]
    assert names("!dk.snak") == ["!dk.snak"]
    assert names("(!alt.test) og !unseenet.") == ["!alt.test", "!unseenet"]
    assert names("Slut med punktum: !dk.snak.") == ["!dk.snak"]
    assert names("!dk.snak og igen !dk.snak") == ["!dk.snak"]          # once
    assert names("!dk.snak@abcd") == ["!dk.snak@abcd"]
    assert names("!comp.lang.c++ er god") == ["!comp.lang.c++"]


def test_group_refs_not_found():
    assert names("Hej! Hvordan går det!") == []           # an exclamation
    assert names("![et billede](billede.png)") == []      # a Markdown image
    assert names("issue !170 og !12") == []               # numbers are not groups
    assert names("a!dk.snak") == []                       # inside a word
    assert names("!Dk.Snak") == []                        # names are lowercase
    assert names("!dk.supernørder") == []                 # names are a-z
    assert names("!!dk.snak") == []
    assert names("#dk.snak") == []                        # a tag now, not a group
    assert names("") == [] and names(None) == []


def test_tags_in_text():
    """UN-RFC 0052 section 3: #word in what the author writes goes into the header."""
    assert tg.in_text("Om #Linux og #økonomi, ikke # Overskrift eller #170.") == ["linux", "økonomi"]
    assert tg.in_text("https://unseenet.org/docs/#install og a#b") == []
    assert tg.in_text("#c-sharp, #3d og #linux igen #linux") == ["c-sharp", "3d", "linux"]
    assert tg.in_text("!dk.snak") == []


def test_group_ref_matches():
    gid = "dk.snak@" + "abcdefghijklmnop"
    assert GroupRef("dk.snak").matches(gid)
    assert GroupRef("dk.snak", "abcd").matches(gid)
    assert not GroupRef("dk.snak", "bbbb").matches(gid)
    assert not GroupRef("dk").matches(gid)
    assert not GroupRef("dk.snak").matches("not a group id")
    assert GroupRef("dk.snak", "abcd").text == "!dk.snak@abcd"


def test_group_links_in_rendered_text():
    """#172: the terminal client shows !group references as clickable links."""
    from unseenet.client import richtext
    from unseenet.core import markup
    text = richtext.blocks(markup.body("Spørg i !dk.marsvin, ikke *!dk.snak*. Se [!x.y](https://e.org)\n",
                                       markup.MARKDOWN_TYPE, "post"))
    clicks = [s.style.meta.get("@click") for s in text.spans
              if s.style and not isinstance(s.style, str) and s.style.meta]
    assert clicks == ["app.group_ref('!dk.marsvin')", "app.group_ref('!dk.snak')"]
    assert "!dk.marsvin" in text.plain
