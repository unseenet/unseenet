"""The root list of hierarchies (UN-RFC 0018, section 4)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import unseenet.hierarchies as hz
from unseenet.core import crypto
from unseenet.known_nodes import PROJECT_KEY

ROOT = Path(__file__).resolve().parent.parent


def root_list(*entries, v=1):
    return json.dumps({"v": v, "updated": "2026-10-16", "hierarchies": list(entries)})


def governed(name="games", key=None):
    key = key or crypto.Identity.generate()
    return {"name": name, "policy": "governed", "maintainer": key.key_text,
            "list": f"{name}.list@{key.fingerprint}"}


def test_project_list_is_valid_and_says_what_section_9_says():
    updated, entries = hz.builtin_root_list()
    assert updated
    project = entries["unseenet"]
    assert project.policy == "governed" and project.maintainer == PROJECT_KEY
    assert project.list.endswith("@ph5fc5hop5232qsz")
    assert entries["alt"].policy == entries["test"].policy == "free"
    for name in ("comp", "humanities", "misc", "news", "rec", "sci", "soc", "talk",
                 "control", "junk", "local", "inbox", "all", "example", "invalid"):
        assert entries[name].policy == "reserved", name
    assert not any(len(n) == 2 for n in entries)      # country codes are regional by rule


def test_whole_list_invalid():
    with pytest.raises(ValueError):
        hz.parse_root_list("not json")
    with pytest.raises(ValueError):
        hz.parse_root_list(root_list(v=2))
    with pytest.raises(ValueError, match="more than once"):
        hz.parse_root_list(root_list({"name": "alt", "policy": "free"},
                                     {"name": "alt", "policy": "reserved"}))
    with pytest.raises(ValueError):
        hz.parse_root_list(root_list(*({"name": f"h{i}", "policy": "free"} for i in range(201))))


def test_malformed_entry_becomes_reserved_unless_strict():
    stranger = crypto.Identity.generate()
    bad = governed("games")
    bad["maintainer"] = stranger.key_text              # list group not owned by the maintainer
    text = root_list(bad, {"name": "odd", "policy": "whatever"}, governed("films"),
                     {"name": "Bad Name!", "policy": "free"})
    _, entries = hz.parse_root_list(text)
    assert entries["games"].policy == "reserved" and not entries["games"].maintainer
    assert entries["odd"].policy == "reserved"
    assert entries["films"].policy == "governed"
    assert "Bad Name!" not in entries
    with pytest.raises(ValueError, match="not owned"):
        hz.parse_root_list(text, strict=True)


def test_free_and_reserved_entries_carry_no_maintainer():
    key = crypto.Identity.generate()
    _, entries = hz.parse_root_list(root_list(
        {"name": "alt", "policy": "free", "maintainer": key.key_text, "list": f"alt.l@{key.fingerprint}"}))
    assert entries["alt"].maintainer == "" and entries["alt"].list == ""


def test_announce_posts_the_project_list():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "announce.py"), "hierarchies", "--dry-run"],
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert "Newsgroups: unseenet.hierarchies@ph5fc5hop5232qsz" in out.stdout
    assert '"unseenet"' in out.stdout


def hierarchy_list(hierarchy, groups, sub=()):
    return json.dumps({"v": 1, "hierarchy": hierarchy, "updated": "x",
                       "groups": [{"group": g} for g in groups], "sub": list(sub)})


def test_project_checkgroups_endorse_the_project_groups():
    lst = hz.builtin_checkgroups()
    assert lst.hierarchy == "unseenet" and len(lst.groups) == 11
    assert all(g.endswith("@ph5fc5hop5232qsz") for g in lst.groups.values())
    assert lst.groups["unseenet.announce"] == "unseenet.announce@ph5fc5hop5232qsz"


def test_hierarchy_list_rules():
    a, b = crypto.Identity.generate(), crypto.Identity.generate()
    g1, g2 = f"games.chess@{a.fingerprint}", f"games.chess@{b.fingerprint}"
    lst = hz.parse_hierarchy_list(hierarchy_list("games", [g1, f"films.x@{a.fingerprint}"]), "games")
    assert lst.groups == {"games.chess": g1}                     # outside the hierarchy: ignored
    twice = hz.parse_hierarchy_list(hierarchy_list("games", [g1, g2]), "games")
    assert twice.groups == {}                                    # endorsed twice: neither counts
    with pytest.raises(ValueError):
        hz.parse_hierarchy_list(hierarchy_list("films", [g1]), "games")   # not the list asked for


def test_name_status_follows_section_8_1():
    _, root = hz.builtin_root_list()
    lists = {"unseenet": hz.builtin_checkgroups()}
    a, b = crypto.Identity.generate(), crypto.Identity.generate()

    def status(gid, known=()):
        s = hz.name_status(gid, root, lists, set(known))
        return s.status, s.short
    assert status("unseenet.announce@ph5fc5hop5232qsz") == ("endorsed", True)
    assert status(f"unseenet.announce@{a.fingerprint}") == ("unendorsed", False)   # a lookalike
    assert status(f"unseenet.important@{a.fingerprint}") == ("unendorsed", False)
    assert status(f"dk.snak@{a.fingerprint}") == ("free", True)                    # regional
    assert status(f"dk.snak@{a.fingerprint}", [f"dk.snak@{b.fingerprint}"]) == ("free", False)
    assert status(f"alt.x@{a.fingerprint}") == ("free", True)
    assert status(f"games.x@{a.fingerprint}") == ("free", True)                    # unclaimed
    assert status(f"zz.x@{a.fingerprint}") == ("reserved", False)                  # not a country
    assert status(f"comp.lang@{a.fingerprint}") == ("reserved", False)             # Big 8
    # without the hierarchy's list, nothing in it is endorsed
    assert hz.name_status("unseenet.announce@ph5fc5hop5232qsz", root, {}, set()).short is False


def test_sub_hierarchies_decide_deeper_names():
    m = crypto.Identity.generate()
    root = {"games": hz.Hierarchy("games", "governed", m.key_text, f"games.list@{m.fingerprint}")}
    endorsed = f"games.chess@{m.fingerprint}"
    lst = hz.parse_hierarchy_list(hierarchy_list(
        "games", [endorsed, f"games.free.x@{m.fingerprint}"],
        sub=[{"name": "games.free", "policy": "free"}]), "games")
    assert lst.groups == {"games.chess": endorsed}               # names under a sub are not its
    lists = {"games": lst}
    assert hz.name_status(endorsed, root, lists, set()).status == "endorsed"
    assert hz.name_status(f"games.free.x@{m.fingerprint}", root, lists, set()).status == "free"
    assert hz.name_status(f"games.other@{m.fingerprint}", root, lists, set()).status == "unendorsed"


def test_country_codes():
    assert "dk" in hz.COUNTRY_CODES and "se" in hz.COUNTRY_CODES and len(hz.COUNTRY_CODES) == 249
    assert hz.policy_of("dk", {}).policy == "free" and hz.policy_of("zz", {}).policy == "reserved"


def test_announce_posts_checkgroups():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "announce.py"), "checkgroups", "--dry-run"],
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert "Newsgroups: unseenet.checkgroups@ph5fc5hop5232qsz" in out.stdout


def test_client_group_labels(tmp_path):
    """What the client shows for a group (UN-RFC 0018 section 8.1)."""
    from unseenet.client.session import Session
    from unseenet.core.vault import Vault
    s = Session(Vault.open(tmp_path / "v.vault", "pw", ops=1, mem=8192 * 1024), status=lambda *_: None)
    s.new_identity("a", "A")
    assert s.group_label("unseenet.announce@ph5fc5hop5232qsz") == "unseenet.announce"
    fake = "unseenet.announce@abcdefghijklmnop"
    assert s.group_label(fake) == "unseenet.announce@abcd"
    assert s.group_label("dk.snak@abcdefghijklmnop") == "dk.snak"
    assert s.group_label("dk.snak@abcdefghijklmnop", {"dk.snak@bbcdefghijklmnop"}) == "dk.snak@abcd"
    assert s.group_label("comp.lang@abcdefghijklmnop") == "comp.lang@abcd"       # reserved
    from unseenet.client import naming
    assert "does not vouch" in naming.group_warning(s, fake)
    assert naming.group_warning(s, "dk.snak@abcdefghijklmnop") is None


def _list(hierarchy, *, sub=(), blocked=()):
    return json.dumps({"v": 1, "hierarchy": hierarchy, "groups": [], "sub": list(sub),
                       "blocked": list(blocked)})


def test_blocks_follow_delegation():
    """Section 5.4: blocks of every maintainer on the way down count; a delegated
    maintainer blocks only in its own part; free sub-hierarchies keep the parent's."""
    a, b = crypto.Identity.generate(), crypto.Identity.generate()
    x, y = crypto.Identity.generate().key_text, crypto.Identity.generate().key_text
    root = {"dk": hz.Hierarchy("dk", "governed", a.key_text, f"dk.liste@{a.fingerprint}")}
    dk = hz.parse_hierarchy_list(_list("dk", sub=[
        {"name": "dk.snak", "policy": "governed", "maintainer": b.key_text,
         "list": f"dk.snak.liste@{b.fingerprint}"},
        {"name": "dk.fri", "policy": "free"}],
        blocked=[{"key": x, "reason": "trusler i flere grupper"}]), "dk")
    snak = hz.parse_hierarchy_list(_list("dk.snak", blocked=[{"key": y, "reason": "spam"}]), "dk.snak")
    lists = {"dk": dk, "dk.snak": snak}
    assert hz.blocks_for("dk.snak.biler", root, lists) == {x: ("dk", "trusler i flere grupper"),
                                                          y: ("dk.snak", "spam")}
    assert hz.blocks_for("dk.snak", root, lists).keys() == {x, y}
    assert hz.blocks_for("dk.politik", root, lists).keys() == {x}
    assert hz.blocks_for("dk.fri.noget", root, lists).keys() == {x}      # free: parent still counts
    assert hz.blocks_for("se.snak", root, lists) == {}
    assert [s.name for s in hz.sub_lists_needed("dk.snak.biler", root, {"dk": dk})] == ["dk.snak"]


def test_block_entries_are_checked():
    k = crypto.Identity.generate().key_text
    k2 = crypto.Identity.generate().key_text
    lst = hz.parse_hierarchy_list(_list("dk", blocked=[
        {"key": k, "reason": ""},                                  # no reason: ignored
        {"key": "nonsense", "reason": "x"},                        # no key: ignored
        {"key": k2, "reason": "a", "until": "2000-01-01T00:00:00+00:00"},
        "not an object"]), "dk")
    assert [b.key for b in lst.blocked] == [k2]
    root = {"dk": hz.Hierarchy("dk", "governed", k, "dk.l@x")}
    assert hz.blocks_for("dk.snak", root, {"dk": lst}) == {}         # expired
    twice = hz.parse_hierarchy_list(_list("dk", blocked=[{"key": k, "reason": "a"},
                                                         {"key": k, "reason": "b"}]), "dk")
    assert twice.blocked == ()
