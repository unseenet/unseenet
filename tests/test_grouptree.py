from unseenet.client.grouptree import fingerprint_suffix, group_tree


def shape(node, depth=0):
    """The tree as indented lines: '+label' for a folder, '-label' for a leaf."""
    out = []
    for it in node.items if depth else []:
        out.append("  " * depth + "=" + it)
    for c in node.children:
        if c.is_folder:
            out.append("  " * depth + "+" + c.label)
            out.extend(shape(c, depth + 1))
        else:
            out.extend("  " * depth + "-" + c.label for _ in c.items)
    return out


def tree(top, *names):
    return group_tree(top, [(n, n) for n in names])


def test_prefix_is_dropped():
    t = tree("alt", "alt.news.wikipedia", "alt.folklore")
    assert shape(t) == ["-folklore", "-news.wikipedia"]


def test_shared_part_becomes_a_folder():
    t = tree("alt", "alt.history.egypt", "alt.history.denmark", "alt.news.wikipedia")
    assert shape(t) == ["+history", "  -denmark", "  -egypt", "-news.wikipedia"]
    assert [f.path for f in t.folders()] == ["alt.history"]


def test_single_way_on_is_joined():
    t = tree("test", "test.usenet.comp.misc", "test.usenet.comp.lang.python",
             "test.nostr.a", "test.nostr.b", "test.portal")
    assert shape(t) == ["+nostr", "  -a", "  -b", "-portal",
                        "+usenet.comp", "  -lang.python", "  -misc"]


def test_group_named_like_its_folder():
    t = tree("alt", "alt.history", "alt.history.egypt", "alt.history.denmark")
    h = t.children[0]
    assert h.is_folder and h.items == ["alt.history"] and h.own_label == "history"
    assert [c.label for c in h.children] == ["denmark", "egypt"]


def test_group_named_like_the_hierarchy():
    t = tree("unseenet", "unseenet", "unseenet.admin")
    assert t.items == ["unseenet"]
    assert shape(t) == ["-admin"]


def test_same_name_twice_stays_two_leaves():
    t = group_tree("alt", [("alt.x", "a"), ("alt.x", "b"), ("alt.y", "c")])
    x = t.children[0]
    assert not x.is_folder and x.items == ["a", "b"]


def test_other_hierarchies_ignored():
    t = tree("alt", "alt.a", "altx.b", "comp.c")
    assert [n for n in t.all_items()] == ["alt.a"]


def test_fingerprint_suffix():
    assert fingerprint_suffix("alt.x@ab12") == "@ab12"
    assert fingerprint_suffix("alt.x") == ""
