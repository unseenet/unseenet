"""Lists kept by councils (UN-RFC 0020, #56): the node list rules, pure."""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from unseenet.core import carrying as ca
from unseenet.core import crypto
from unseenet.core import lists as ls
from unseenet.core import proposals as pr
from unseenet.core.announcements import Announcement

DAY = timedelta(days=1)
TODAY = date(2026, 12, 1)
REPLICAS = {crypto.Identity.generate().key_text for _ in range(3)}
R1, R2, R3 = sorted(REPLICAS)
ONION = "a" * 56 + ".onion"
COUNCIL = ls.ListCouncil({"nodes": "unseenet.nodes@abcdefghijklmnop"},
                         "unseenet.lists.claims@abcdefghijklmnop",
                         "unseenet.lists.reports@abcdefghijklmnop",
                         {"unseenet": "0.7.2"})


def key(n: int) -> str:
    return "ed25519:" + chr(ord("a") + n) * 52


def at(d: date, hour=12) -> datetime:
    return datetime.combine(d, time(hour), timezone.utc)


def announcement(k, *, d=TODAY - 3 * DAY, address=f"onion:{ONION}", patterns=("*",),
                 operator=None, addresses=()):
    return Announcement(k, address, f"node-{k[8:12]}", {"groups": list(patterns)}, at(d),
                        tuple(addresses), operator, None, "", list(patterns))


def report(by, d, reached=(), missed=(), disconnected=(), incomplete=(), software=None):
    body = ls.report_body(d, reached, missed, disconnected=disconnected, incomplete=incomplete,
                          software=software)
    return ls.parse_report(body, key=by, date=at(d + DAY, 1))


def days_reached(k, n, *, by=R1, software=None):
    return [report(by, TODAY - i * DAY, reached=[k], software={k: software} if software else None)
            for i in range(n)]


def compute(anns, reports, previous=(), **kw):
    m = ls.Measurements(reports, REPLICAS)
    body, verdicts = ls.node_list(day=TODAY, seq=4, announcements=anns, measurements=m,
                                  network=ca.network_groups(), previous=set(previous),
                                  council=COUNCIL, **kw)
    return body, verdicts


def keys_in(body: str) -> list[str]:
    import json
    return [n["node_key"] for n in json.loads(body)["nodes"]]


def test_a_council_without_lists_and_one_with():
    assert ls.list_council({"council": {}}) is None
    lc = ls.list_council({"lists": {"nodes": "unseenet.nodes@abcdefghijklmnop"},
                          "claims": "c@abcdefghijklmnop", "reports": "r@abcdefghijklmnop",
                          "min_software": {"unseenet": "0.7.2"}})
    assert lc.lists["nodes"].startswith("unseenet.nodes@") and lc.min_software == {"unseenet": "0.7.2"}
    with pytest.raises(ls.ListProblem):
        ls.list_council({"lists": {"people": "p@abcdefghijklmnop"}, "claims": "c@abcdefghijklmnop",
                         "reports": "r@abcdefghijklmnop"})
    with pytest.raises(ls.ListProblem):
        ls.list_council({"lists": {"scribes": "s@abcdefghijklmnop"}, "claims": "c@abcdefghijklmnop",
                         "reports": "r@abcdefghijklmnop"})        # scribes need publishers


def test_versions():
    assert ls.version_key("0.7.2.dev3") < ls.version_key("0.7.2rc1") < ls.version_key("0.7.2")
    assert ls.version_key("0.7.10") > ls.version_key("0.7.9") and ls.version_key("x") is None
    floor = {"unseenet": "0.7.2"}
    assert ls.below_minimum("unseenet 0.7.1", floor) and not ls.below_minimum("unseenet 0.8.0", floor)
    assert not ls.below_minimum("othernode 0.1", floor) and not ls.below_minimum(None, floor)
    assert ls.below_minimum("unseenet banana", floor)


def test_a_report_round_trip_and_its_checks():
    k = key(1)
    r = report(R1, TODAY, reached=[k], incomplete=[k], software={k: "unseenet 0.8.0"})
    assert r.day == TODAY and k in r.incomplete and r.software[k] == "unseenet 0.8.0"
    good = ls.report_body(TODAY, [k], [])
    with pytest.raises(ls.ListProblem):                     # posted days later
        ls.parse_report(good, key=R1, date=at(TODAY + 3 * DAY))
    bad = ls.report_body(TODAY, [k], [k])
    with pytest.raises(ls.ListProblem):
        ls.parse_report(bad, key=R1, date=at(TODAY))
    with pytest.raises(ls.ListProblem):                     # disconnected but never reached
        ls.parse_report(ls.report_body(TODAY, [], [k], disconnected=[k]), key=R1, date=at(TODAY))
    assert ls.report_subject(TODAY) == "report 2026-12-01"


def test_only_members_reports_count_and_the_newest_per_day():
    k = key(1)
    outsider = crypto.Identity.generate().key_text
    early = ls.parse_report(ls.report_body(TODAY, [], [k]), key=R1, date=at(TODAY, 20))
    late = ls.parse_report(ls.report_body(TODAY, [k], []), key=R1, date=at(TODAY + DAY, 2))
    m = ls.Measurements([early, late, report(outsider, TODAY - DAY, reached=[k])], REPLICAS)
    assert m.reached(TODAY, k) and not m.reached(TODAY - DAY, k)


def test_a_new_node_needs_five_of_seven_days_and_to_be_connected():
    k = key(1)
    body, v = compute([announcement(k)], days_reached(k, 4))
    assert keys_in(body) == [] and "4 of the last 7" in v[k].why
    body, v = compute([announcement(k)], days_reached(k, 5))
    assert keys_in(body) == [k] and v[k].listed
    # reached, but not connected the last day it was reached
    reps = days_reached(k, 4) + [report(R2, TODAY, reached=[k], disconnected=[k])]
    reps = [r for r in reps if not (r.key == R1 and r.day == TODAY)]
    reps += [report(R1, TODAY - 5 * DAY, reached=[k])]
    body, v = compute([announcement(k)], reps)
    assert keys_in(body) == [] and "UN-RFC 0021" in v[k].why
    # one other replica that found it connected is enough
    body, _ = compute([announcement(k)], reps + [report(R3, TODAY, reached=[k])])
    assert keys_in(body) == [k]


def test_the_rules_that_hold_for_every_node():
    k = key(1)
    reps = days_reached(k, 7)
    assert keys_in(compute([announcement(k, address="test:10.0.0.5:1119")], reps)[0]) == []
    assert keys_in(compute([announcement(k, d=TODAY - 31 * DAY)], reps)[0]) == []   # stale
    assert keys_in(compute([announcement(k, d=TODAY + DAY)], reps)[0]) == []        # tomorrow's
    only_alt = announcement(k, patterns=("alt.*",))
    _, v = compute([only_alt], reps)
    assert not v[k].listed and "network's own groups" in v[k].why
    _, v = compute([announcement(k)], days_reached(k, 7, software="unseenet 0.7.1"))
    assert not v[k].listed and "below the council's minimum" in v[k].why
    assert v[k] == compute([announcement(k)], days_reached(k, 7, software="unseenet 0.7.1"),
                           previous=[k])[1][k]          # listed or not, the minimum counts


def test_test_addresses_are_never_listed_but_other_addresses_are():
    k = key(1)
    a = announcement(k, addresses=("test:10.0.0.5:1119", "i2p:somewhere"), operator=key(9))
    import json
    (e,) = json.loads(compute([a], days_reached(k, 7))[0])["nodes"]
    assert e["addresses"] == ["i2p:somewhere"] and e["operator"] == key(9)
    assert e["address"] == f"onion:{ONION}" and e["node_key"] == k


def test_a_listed_node_stays_until_down_for_ten_days():
    k = key(1)
    a = announcement(k)
    # nobody reached it today: a new node would not come on, a listed one stays
    missed = [report(R1, TODAY - i * DAY, missed=[k]) for i in range(9)]
    assert keys_in(compute([a], missed, previous=[k])[0]) == [k]
    assert keys_in(compute([a], missed)[0]) == []
    # a day without any report is not a day down
    gap = [report(R1, TODAY - i * DAY, missed=[k]) for i in range(11) if i != 4]
    assert keys_in(compute([a], gap, previous=[k])[0]) == [k]
    # ten days reported and never connected and complete: off
    down = [report(R1, TODAY - i * DAY, reached=[k], incomplete=[k]) for i in range(10)]
    body, v = compute([a], down, previous=[k])
    assert keys_in(body) == [] and "10 days" in v[k].why
    # one replica that reached it well on one of those days keeps it on
    assert keys_in(compute([a], down + [report(R2, TODAY - 6 * DAY, reached=[k])],
                           previous=[k])[0]) == [k]


def test_imported_entries_stay_for_their_grace():
    k, j = key(1), key(2)
    imported = {k: {"name": "old", "address": ONION, "node_key": k},
                j: {"name": "older", "address": ONION, "node_key": j}}
    # k not announced yet, j announced but not measured enough: both stay
    body, v = compute([announcement(j)], [], imported=imported, genesis=TODAY - 30 * DAY)
    assert keys_in(body) == [k, j] or keys_in(body) == sorted([k, j])
    assert "not announced yet" in v[k].why
    # after 180 days only the rules count
    body, _ = compute([announcement(j)], [], imported=imported, genesis=TODAY - 181 * DAY)
    assert keys_in(body) == []


def test_decisions_remove_restore_and_set():
    k = key(1)
    a, reps = announcement(k), days_reached(k, 7)
    rm = ls.Decision(TODAY - DAY, "aaaa", {"remove": {"list": "nodes", "entry": k}})
    back = ls.Decision(TODAY, "bbbb", {"restore": {"list": "nodes", "entry": k}})
    _, v = compute([a], reps, decisions=ls.decisions_until([rm], TODAY))
    assert not v[k].listed and "decision" in v[k].why
    assert keys_in(compute([a], reps, decisions=ls.decisions_until([rm, back], TODAY))[0]) == [k]
    assert not compute([a], reps, decisions=ls.decisions_until([rm, back], TODAY - DAY))[1][k].listed
    easier = ls.Decision(TODAY - DAY, "cccc", {"set": {"need_days": 2}})
    assert keys_in(compute([a], days_reached(k, 2),
                           decisions=ls.decisions_until([easier], TODAY))[0]) == [k]


def test_list_changes_are_checked_in_proposals():
    gid = "unseenet.lists@abcdefghijklmnop"
    pr.make_proposal(gid, 1, {"list": {"remove": {"list": "nodes", "entry": key(1)}}}, "abuse")
    pr.make_proposal(gid, 1, {"list": {"reserve": "nic"}}, "for registries")
    pr.make_proposal(gid, 1, {"list": {"set": {"grace_days": 14}}}, "slow networks")
    for bad in ({"remove": key(1)}, {"remove": {"list": "people", "entry": "x"}},
                {"reserve": "Not A Name"}, {"set": {"grace_days": 1}}, {"set": {"x": 3}},
                {"remove": {"list": "nodes", "entry": "x"}, "reserve": "a"}, {"delete": "x"}):
        with pytest.raises(pr.ProposalProblem):
            pr.make_proposal(gid, 1, {"list": bad}, "x")


def test_at_most_per_operator_and_the_listed_first():
    op = key(9)
    ks = [key(i) for i in range(1, 5)]
    anns = [announcement(k, operator=op) for k in ks]
    reps = [report(R1, TODAY - i * DAY, reached=ks) for i in range(7)]
    two = ls.decisions_until([ls.Decision(TODAY, "x", {"set": {"max_per_operator": 2}})], TODAY)
    body, v = compute(anns, reps, previous=[ks[3]], decisions=two)
    assert keys_in(body) == sorted([ks[3], ks[0]])
    assert "as many listed nodes" in v[ks[1]].why


def test_same_inputs_same_list_and_its_updated_field():
    k, j = key(1), key(2)
    anns, reps = [announcement(j), announcement(k)], days_reached(k, 7) + days_reached(j, 7, by=R2)
    a = compute(anns, reps)[0]
    b = compute(list(reversed(anns)), list(reversed(reps)))[0]
    assert a == b and '"updated":"council 4 day 2026-12-01"' in a
    assert ls.updated_day("council 4 day 2026-12-01") == (4, TODAY)
    assert ls.updated_day("2026-10-17") is None
    from unseenet.known_nodes import parse_node_list
    assert [n.node_key for n in parse_node_list(a)[1]] == sorted([k, j])


def test_canaries_and_connection_verdicts():
    a, b, c, d = key(1), key(2), key(3), key(4)
    body = ls.canary_body(a, TODAY, "bm9uY2U")
    assert ls.read_canary(body, TODAY) == a and ls.read_canary(body, TODAY + DAY) is None
    assert ls.canary_subject(a, TODAY).startswith("canary ")
    R = ls.Reading
    every = {"alt.x@abcdefghijklmnop", "dk.y@abcdefghijklmnop"}
    readings = {a: R({a, b, c}, set(every), ["*"]),
                b: R({a, b, c}, set(every), ["*"]),
                c: R({a, b, c}, {"alt.x@abcdefghijklmnop"}, ["*"]),     # lacks dk.y
                d: R({d}, set(every), ["*"])}                           # an island
    disc, inc = ls.connection_verdicts(readings, {a, b, c, d})
    assert disc == {d} and inc == {c}
    # a node that carries only alt.* is complete without dk.y
    readings[c].patterns = ["alt.*"]
    assert ls.connection_verdicts(readings, {a, b, c, d})[1] == set()
    # nothing posted yesterday: no verdict
    assert ls.connection_verdicts(readings, set()) == (set(), set())


def test_the_sources_list_is_the_import_and_the_decisions():
    """UN-RFC 0020 section 6.8: nothing is measured; a passed ``sources`` replaces it."""
    start = {"files": ["https://github.com/unseenet/{repo}/releases/download/{tag}/{name}"],
             "index": ["https://pypi.org/simple/"]}
    body = ls.import_body({"sources": start})
    assert ls.imported_sources(body) == start
    day = date(2026, 11, 20)
    got = ls.sources_list(day=day, seq=3, imported=start, decisions=ls.DecisionState())
    updated, sources = ls.parse_sources_list(got)
    assert updated == "council 3 day 2026-11-20" and list(sources.files) == start["files"]
    new = {"files": ["https://codeberg.org/unseenet/{repo}/releases/download/{tag}/{name}",
                     start["files"][0]], "index": start["index"]}
    ls.check_list_change({"sources": new})
    dec = ls.decisions_until([ls.Decision(date(2026, 11, 18), "abcd", {"sources": new})], day)
    _, sources = ls.parse_sources_list(ls.sources_list(day=day, seq=3, imported=start,
                                                       decisions=dec))
    assert sources.files[0].startswith("https://codeberg.org/")
    assert ls.sources_list(day=day, seq=1, imported=None, decisions=ls.DecisionState()) is None
    for bad in ({"files": ["ftp://x/{name}"], "index": start["index"]},
                {"files": start["files"]}, {"files": [], "index": start["index"]}):
        with pytest.raises(ls.ListProblem):
            ls.check_list_change({"sources": bad})
    with pytest.raises(ls.ListProblem, match="publishers"):
        ls.list_council({"lists": {"sources": "unseenet.sources@" + "a" * 16},
                         "claims": "c@" + "b" * 16, "reports": "r@" + "c" * 16})
