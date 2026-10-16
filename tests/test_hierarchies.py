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
