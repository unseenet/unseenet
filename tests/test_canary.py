"""Canaries: are the listed nodes connected? (UN-RFC 0021, tools/canary.py; no network)"""

import importlib
import json
import sys
from datetime import date
from pathlib import Path

from unseenet.core import crypto
from unseenet.known_nodes import CANARY_GROUP

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def load(name):
    return importlib.import_module(name)              # tools/ is on sys.path


cn = load("canary")
DAY = date(2026, 10, 16)
P = "unseenet@ph5fc5hop5232qsz"


def reading(seen=(), groups=(P,), excludes=""):
    return cn.Reading(seen=set(seen), groups=set(groups), excludes=excludes)


def test_canary_roundtrip():
    key, other = crypto.Identity.generate(), crypto.Identity.generate()
    raw = cn.canary_article(key, "node1", "ed25519:abc", DAY, bits=4)
    assert b"Newsgroups: " + CANARY_GROUP.encode() in raw
    assert cn.read_canary(raw, key.public_key, DAY) == "ed25519:abc"
    assert cn.read_canary(raw, other.public_key, DAY) is None          # not our poster
    assert cn.read_canary(raw, key.public_key, date(2026, 10, 15)) is None
    assert cn.read_canary(raw.replace(b"node1", b"node2"), key.public_key, DAY) is None
    # every canary is a new article
    assert raw != cn.canary_article(key, "node1", "ed25519:abc", DAY, bits=4)


def test_all_connected():
    r = {k: reading(seen="ABC") for k in "ABC"}
    assert cn.verdicts(r, set("ABC"), {}) == {"A": [], "B": [], "C": []}


def test_island():
    """C peers with nobody: its canary stays home, and it has nobody else's."""
    r = {"A": reading(seen="AB"), "B": reading(seen="AB"), "C": reading(seen="C")}
    v = cn.verdicts(r, set("ABC"), {"A": "na", "B": "nb", "C": "nc"})
    assert v["A"] == v["B"] == []
    assert len(v["C"]) == 2
    assert "reached 1 of the 3" in v["C"][0] and "na, nb" in v["C"][1]


def test_split_network_fails_both_halves():
    r = {"A": reading(seen="AB"), "B": reading(seen="AB"),
         "C": reading(seen="CD"), "D": reading(seen="CD")}
    v = cn.verdicts(r, set("ABCD"), {})
    assert all(v[k] for k in "ABCD")


def test_one_broken_node_does_not_fail_the_rest():
    r = {"A": reading(seen="ABC"), "B": reading(seen="ABC"), "C": reading(seen="ABC"),
         "D": reading(seen="D")}
    v = cn.verdicts(r, set("ABCD"), {})
    assert v["A"] == v["B"] == v["C"] == [] and v["D"]


def test_pull_only_node_gets_in_but_not_out():
    """D pulls from the others but nobody takes what it pushes."""
    r = {"A": reading(seen="ABC"), "B": reading(seen="ABC"), "C": reading(seen="ABC"),
         "D": reading(seen="ABCD")}
    v = cn.verdicts(r, set("ABCD"), {})
    assert len(v["D"]) == 1 and "Not connected: its canary" in v["D"][0]


def test_new_node_is_not_judged_on_its_own_canary():
    r = {"A": reading(seen="AB"), "B": reading(seen="AB"), "N": reading(seen="AB")}
    assert cn.verdicts(r, set("AB"), {})["N"] == []


def test_single_node_is_connected():
    assert cn.verdicts({"A": reading(seen="A")}, {"A"}, {}) == {"A": []}


def test_nothing_posted_yesterday_judges_nothing():
    r = {"A": reading(groups=()), "B": reading()}
    assert cn.verdicts(r, set(), {}) == {"A": [], "B": []}


def test_complete_and_excludes():
    dk, alt = "dk.snak@x", "alt.test@x"
    full, seen = (P, dk, alt), "ABCDE"
    r = {"A": reading(seen, full), "B": reading(seen, full), "E": reading(seen, full),
         "C": reading(seen, (P, dk), excludes="alt.*"),
         "D": reading(seen, (P, dk))}
    v = cn.verdicts(r, set(seen), {})
    assert v["A"] == v["B"] == v["C"] == v["E"] == []      # C says what it leaves out
    assert len(v["D"]) == 1 and "alt.test@x" in v["D"][0]


def test_group_on_a_minority_does_not_count():
    r = {"A": reading(seen="ABC", groups=(P, "new@x")), "B": reading(seen="ABC"),
         "C": reading(seen="ABC")}
    assert cn.verdicts(r, set("ABC"), {}) == {"A": [], "B": [], "C": []}


def test_project_groups_cannot_be_excluded():
    r = {k: reading(seen="AB") for k in "AB"}
    r["B"] = reading(seen="AB", groups=(), excludes="unseenet*")
    v = cn.verdicts(r, set("AB"), {})
    assert v["A"] == [] and "project groups" in v["B"][0]


def test_health_counts_connection_problems(tmp_path, monkeypatch):
    nh = load("node_health")
    nodes, health = tmp_path / "nodes.json", tmp_path / "health.json"
    a, b = "a" * 56 + ".onion", "b" * 56 + ".onion"
    nodes.write_text(json.dumps({"v": 1, "updated": "x", "nodes": [
        {"name": "na", "address": a}, {"name": "nb", "address": b}]}))
    health.write_text(json.dumps({"nodes": {b: {"issue": 12, "requested_by": "op"}}}))
    monkeypatch.setattr(nh, "NODES", nodes)
    monkeypatch.setattr(nh, "HEALTH", health)
    reach = {a: [], b: []}
    island = {a: [], b: ["Not connected: ..."]}

    act = nh.update(reach, date(2026, 10, 1), island, {"ka", "kb"})
    stored = json.loads(health.read_text())
    assert stored["canaries"] == {"date": "2026-10-01", "posted": ["ka", "kb"]}
    assert stored["nodes"][b]["first_failed"] == "2026-10-01"
    assert nh.posted_yesterday(stored, date(2026, 10, 2)) == {"ka", "kb"}
    assert nh.posted_yesterday(stored, date(2026, 10, 3)) == set()
    act = nh.update(reach, date(2026, 10, 4), island, set())
    assert "Not connected" in act["comments"][0]["body"]
    act = nh.update(reach, date(2026, 10, 11), island, set())
    assert act["announce"] and "taken off" in act["comments"][0]["body"]

    # every node disconnected is still counted: they all answered
    nodes.write_text(json.dumps({"v": 1, "updated": "x", "nodes": [
        {"name": "na", "address": a}, {"name": "nb", "address": b}]}))
    act = nh.update(reach, date(2026, 10, 12), {a: ["x"], b: ["x"]}, set())
    assert act["changed"] and "nothing counted" not in " ".join(act["summary"])


def _fake_network(monkeypatch, delivers_out: bool, delivers_in: bool):
    """New node N and listed node A; canaries move only as told."""
    from types import SimpleNamespace
    have = {"N": set(), "A": set()}

    async def post(address, port, key, name, node_key, day):
        have[address].add(node_key)
        if address == "N" and delivers_out:
            have["A"].add(node_key)
        if address == "A" and delivers_in:
            have["N"].add(node_key)
        return None

    async def read(address, port, poster, day):
        return cn.Reading(seen=set(have[address]), groups={CANARY_GROUP})

    monkeypatch.setattr(cn, "post_canary", post)
    monkeypatch.setattr(cn, "read_node", read)
    new = SimpleNamespace(name="new", address="N", node_key="kN")
    listed = [SimpleNamespace(name="na", address="A", node_key="kA")]
    return new, listed


def test_request_check(monkeypatch):
    import asyncio
    key = crypto.Identity.generate()
    for out, inn, expect in ((True, True, 0), (False, True, 1), (True, False, 1), (False, False, 2)):
        new, listed = _fake_network(monkeypatch, out, inn)
        problems = asyncio.run(cn.request_check(new, listed, 0, key, DAY, timeout=0, every=0))
        assert len(problems) == expect, (out, inn, problems)
    new, listed = _fake_network(monkeypatch, True, False)
    problems = asyncio.run(cn.request_check(new, listed, 0, key, DAY, timeout=0, every=0))
    assert "**na** did not reach this node" in problems[0]


def test_request_check_waits_for_the_canary_group(monkeypatch):
    import asyncio
    new, listed = _fake_network(monkeypatch, True, True)

    async def read(address, port, poster, day):
        return cn.Reading()

    monkeypatch.setattr(cn, "read_node", read)
    key = crypto.Identity.generate()
    assert asyncio.run(cn.request_check(new, listed, 0, key, DAY, timeout=0, every=0)) is None
