"""Markdown in a profile's about and a group's charter (#211, UN-RFC 0022 4.1, 0014 2.1)."""

import json

from unseenet.core import crypto, markup
from unseenet.core import profiles as prof
from unseenet.core.groups import Manifest, make_manifest

HOME = """# Andreas

I make **Unseenet** - Usenet, unseen.

- Python and Tor
- [the code](https://github.com/unseenet/unseenet)

![me](blob1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)
"""


def _types(nodes, out=None):
    out = [] if out is None else out
    for n in nodes:
        if isinstance(n, list):
            _types(n, out)
            continue
        out.append(n["t"])
        for key in ("c", "items"):
            if isinstance(n.get(key), list):
                _types(n[key], out)
    return out


def test_manifest_text_is_markdown_without_images():
    tree = markup.manifest_text(HOME, markup.MARKDOWN_TYPE)
    kinds = _types(tree)
    assert {"h", "strong", "ul", "link"} <= set(kinds)
    assert "image" not in kinds                         # a manifest cannot hold blobs
    assert "[image: me]" in json.dumps(tree)
    assert markup.parse(HOME) != tree                   # posts do keep the image


def test_plain_and_unknown_types_stay_plain():
    for t in (None, markup.PLAIN_TYPE, "text/x-something"):
        tree = markup.manifest_text(HOME, t)
        assert set(_types(tree)) <= {"p", "text", "br"}
        assert "# Andreas" in json.dumps(tree)


def test_text_type_for():
    assert markup.text_type_for(True, "hi") == markup.MARKDOWN_TYPE
    assert markup.text_type_for(True, "  ") is None     # no text, no type
    assert markup.text_type_for(False, "hi") is None    # plain is the default


def test_profile_carries_about_type():
    obj = prof.make_profile(HOME, markdown=True)
    assert obj["about_type"] == markup.MARKDOWN_TYPE
    assert "about_type" not in prof.make_profile(HOME)               # plain: left out
    assert "about_type" not in prof.make_profile("", markdown=True)  # nothing to type
    ident = crypto.Identity.generate()
    art = prof.profile_manifest(ident, obj, pow_bits=0)
    p = prof.profile_from_manifest(Manifest.from_article(art))
    assert p.about_type == markup.MARKDOWN_TYPE and p.about.startswith("# Andreas")


def test_profile_rejects_a_silly_type():
    import pytest
    with pytest.raises(prof.ProfileError):
        prof.check_profile({"v": 1, "about": "x", "about_type": "x" * 500})
    with pytest.raises(prof.ProfileError):
        prof.check_profile({"v": 1, "about": "x", "about_type": 3})


def test_manifest_charter_type():
    owner = crypto.Identity.generate()
    art = make_manifest(owner, "dk.snak", "open", charter="# Rules\n\n- be kind",
                        charter_type=markup.MARKDOWN_TYPE, pow_bits=0)
    m = Manifest.from_article(art)
    assert m.charter_type == markup.MARKDOWN_TYPE
    art = make_manifest(owner, "dk.snak", "open", charter_type=markup.MARKDOWN_TYPE, pow_bits=0)
    assert "charter_type" not in json.loads(art.body)     # no charter, no type
    assert Manifest.from_article(make_manifest(owner, "dk.snak", "open", charter="x",
                                               pow_bits=0)).charter_type is None



def test_charter_under_its_earlier_name():
    """UN-RFC 0014 section 2.2: a manifest signed when the fields were called ``rules`` and
    ``rules_type`` still has its charter; a republished one is written with the new names."""
    from unseenet.core.groups import canonical_json, charter_fields, manifest_article, with_charter
    owner = crypto.Identity.generate()
    art = make_manifest(owner, "dk.snak", "open", pow_bits=0)
    old = {**json.loads(art.body), "rules": "# Regler\n\n- vær søde",
           "rules_type": markup.MARKDOWN_TYPE}
    assert charter_fields(old) == ("# Regler\n\n- vær søde", markup.MARKDOWN_TYPE)
    assert with_charter(old)["charter_type"] == markup.MARKDOWN_TYPE
    assert "rules" not in with_charter(old) and "rules_type" not in with_charter(old)
    assert charter_fields({"charter": "new", "rules": "old"}) == ("new", None)   # new name wins
    art.body = canonical_json(old)        # as signed before the change (not re-signed here)
    m = Manifest.from_article(art)
    assert m.charter.startswith("# Regler") and m.charter_type == markup.MARKDOWN_TYPE
    again = json.loads(manifest_article(owner, m.group_id, dict(old, serial=2), pow_bits=0).body)
    assert again["charter"].startswith("# Regler") and again["charter_type"] == markup.MARKDOWN_TYPE
    assert "rules" not in again and "rules_type" not in again
