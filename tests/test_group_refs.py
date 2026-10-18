"""#172: groups named in a text with #."""

from unseenet.core.groups import GroupRef, group_refs


def names(text):
    return [r.text for r in group_refs(text)]


def test_group_refs_found():
    assert names("Spørg i #dk.snak.marsvin, de ved det.") == ["#dk.snak.marsvin"]
    assert names("#dk.snak") == ["#dk.snak"]
    assert names("(#alt.test) og #unseenet!") == ["#alt.test", "#unseenet"]
    assert names("Slut med punktum: #dk.snak.") == ["#dk.snak"]
    assert names("#dk.snak og igen #dk.snak") == ["#dk.snak"]          # once
    assert names("#dk.snak@abcd") == ["#dk.snak@abcd"]
    assert names("#comp.lang.c++ er god") == ["#comp.lang.c++"]


def test_group_refs_not_found():
    assert names("# Overskrift") == []                 # markdown heading
    assert names("issue #170 og #12") == []            # numbers are not groups
    assert names("https://unseenet.org/docs/#install") == []
    assert names("a#dk.snak") == []                    # inside a word
    assert names("#Dk.Snak") == []                     # names are lowercase
    assert names("#dk.supernørder") == []              # names are a-z
    assert names("##dk.snak") == []
    assert names("") == [] and names(None) == []


def test_group_ref_matches():
    gid = "dk.snak@" + "abcdefghijklmnop"
    assert GroupRef("dk.snak").matches(gid)
    assert GroupRef("dk.snak", "abcd").matches(gid)
    assert not GroupRef("dk.snak", "bbbb").matches(gid)
    assert not GroupRef("dk").matches(gid)
    assert not GroupRef("dk.snak").matches("not a group id")
