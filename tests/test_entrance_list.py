"""Entrances on a list council's entrance list (UN-RFC 0020 6.3, #861): the rules, pure."""

import json
from datetime import date, datetime, time, timedelta, timezone

import pytest

from unseenet.core import crypto
from unseenet.core import entrances as en
from unseenet.core import lists as ls

DAY = timedelta(days=1)
TODAY = date(2026, 12, 1)
REPLICAS = {crypto.Identity.generate().key_text for _ in range(3)}
R1, R2, R3 = sorted(REPLICAS)
PUB = "unseenet.releases@ph5fc5hop5232qsz"
OTHER_PUB = "acme.releases@abcdefghijklmnop"
COUNCIL = ls.ListCouncil({"entrances": "unseenet.entrances@abcdefghijklmnop"},
                         "unseenet.lists.claims@abcdefghijklmnop",
                         "unseenet.lists.reports@abcdefghijklmnop")
SHA = "0" * 64


def key(n: int) -> str:
    return "ed25519:" + chr(ord("a") + n) * 52


def at(d: date, hour=12) -> datetime:
    return datetime.combine(d, time(hour), timezone.utc)


def onion(n: int) -> str:
    return chr(ord("a") + n) * 56 + ".onion"


def entrance(n, *, d=TODAY - 3 * DAY, publisher=PUB, operator=None, url=None):
    body = en.make_body(publisher, at(d), onion=onion(n), url=url, name=f"e{n}",
                        operator=operator)
    return en.parse(body, key=key(n), date=at(d))


def release_post(version: str) -> str:
    return f"Unseenet web client {version}\n\nBuilt from x.\n\n{SHA}  index.html\n{SHA}  a.zip\n"


RELS = {PUB: en.releases([(release_post("1.0"), at(TODAY - 60 * DAY))])}


def served(n, days, version="1.0", *, by=R1, start=0):
    out = []
    for i in range(start, start + days):
        d = TODAY - i * DAY
        body = ls.report_body(d, [key(n)], [], served={key(n): version} if version else None)
        out.append(ls.parse_report(body, key=by, date=at(d + DAY, 1)))
    return out


def missed(n, days, *, by=R1, start=0):
    out = []
    for i in range(start, start + days):
        d = TODAY - i * DAY
        out.append(ls.parse_report(ls.report_body(d, [], [key(n)]), key=by, date=at(d + DAY, 1)))
    return out


def compute(anns, reports, *, previous=(), releases=None, decisions=None, imported=(),
            genesis=None, council=COUNCIL):
    inputs = en.Inputs(list(anns), RELS if releases is None else releases, set(previous),
                       list(imported), genesis)
    return en.entrance_list(day=TODAY, seq=4, inputs=inputs,
                            measurements=ls.Measurements(reports, REPLICAS),
                            council=council, decisions=decisions)


def listed(body):
    return [e.get("key") or e.get("url") or e.get("onion") for e in json.loads(body)["entrances"]]


def test_an_announcement_round_trips_and_is_checked():
    e = entrance(1, operator="@lorensen", url="https://web.example/")
    assert e.publisher == PUB and e.onion == onion(1) and e.url == "https://web.example/"
    assert e.base() == f"http://{onion(1)}/"
    assert e.entry() == {"key": key(1), "publisher": PUB, "url": "https://web.example/",
                         "onion": onion(1), "name": "e1", "operator": "@lorensen"}
    with pytest.raises(en.EntranceProblem):
        en.make_body(PUB, at(TODAY))                       # neither url nor onion
    with pytest.raises(en.EntranceProblem):
        en.make_body("not a group", at(TODAY), onion=onion(1))
    with pytest.raises(en.EntranceProblem):
        en.make_body(PUB, at(TODAY), url="http://plain.example/")
    body = en.make_body(PUB, at(TODAY), onion=onion(1))
    with pytest.raises(en.EntranceProblem):                # dated otherwise than its article
        en.parse(body, key=key(1), date=at(TODAY, 15))
    assert en.parse(body, key=key(1), date=at(TODAY) + timedelta(minutes=10)).onion == onion(1)


def test_info_must_name_the_announced_key():
    assert en.info_names({"key": key(1), "operator": "x"}, key(1))
    assert not en.info_names({"key": key(2)}, key(1))
    assert not en.info_names([], key(1))


def test_release_posts():
    v, files = en.parse_release(release_post("20261021.1145"))
    assert v == "20261021.1145" and files == {"index.html": SHA}     # no zip
    assert en.parse_release("Unseenet web client 1.0\n") is None      # no files
    assert en.parse_release(f"Something else 1.0\n{SHA}  x\n") is None
    assert en.parse_release(f"Unseenet web client 1.0\n{SHA}  ../etc/passwd\n") is None
    rels = en.releases([(release_post("1.0"), at(TODAY - 9 * DAY)),
                        (release_post("1.0"), at(TODAY - 2 * DAY)),
                        (release_post("1.1"), at(TODAY - 3 * DAY))])
    assert rels["1.0"].date == at(TODAY - 9 * DAY)                    # the first post
    assert en.due_version(rels, TODAY, 7) == "1.0"                    # 1.1 is out 3 days
    assert en.due_version(rels, TODAY + 4 * DAY, 7) == "1.1"


def test_fourteen_good_days_put_an_entrance_on():
    body, v = compute([entrance(1)], served(1, 14))
    assert listed(body) == [key(1)] and v[key(1)].listed
    body, v = compute([entrance(1)], served(1, 13))
    assert listed(body) == [] and "13 of the last 14" in v[key(1)].why
    # a missed day in the middle is enough to wait
    body, v = compute([entrance(1)], served(1, 6) + served(1, 7, start=7))
    assert listed(body) == []


def test_another_replica_counts_on_a_day_one_missed():
    reports = served(1, 14, by=R1)[:7] + missed(1, 7, by=R1, start=7) + served(1, 7, by=R2, start=7)
    body, _ = compute([entrance(1)], reports)
    assert listed(body) == [key(1)]


def test_an_unsigned_or_changed_client_is_not_a_good_day():
    body, _ = compute([entrance(1)], served(1, 14, version=None))
    assert listed(body) == []
    body, _ = compute([entrance(1)], served(1, 14, version="9.9"))   # no such release
    assert listed(body) == []


def test_it_must_follow_the_publishers_new_release():
    rels = {PUB: en.releases([(release_post("1.0"), at(TODAY - 60 * DAY)),
                              (release_post("1.1"), at(TODAY - 10 * DAY))])}
    # 1.1 has been out 7 days by the end of the day 3 days ago; serving 1.0 fails from then
    body, _ = compute([entrance(1)], served(1, 14, "1.0"), releases=rels)
    assert listed(body) == []
    reports = served(1, 3, "1.1") + served(1, 11, "1.0", start=3)
    body, _ = compute([entrance(1)], reports, releases=rels)
    assert listed(body) == []
    reports = served(1, 4, "1.1") + served(1, 10, "1.0", start=4)
    body, _ = compute([entrance(1)], reports, releases=rels)
    assert listed(body) == [key(1)]


def test_a_listed_entrance_has_grace():
    reports = missed(1, 9) + served(1, 1, start=9)
    body, _ = compute([entrance(1)], reports, previous=[key(1)])
    assert listed(body) == [key(1)]
    body, v = compute([entrance(1)], missed(1, 10), previous=[key(1)])
    assert listed(body) == [] and "10 days" in v[key(1)].why


def test_publisher_without_releases_and_unnamed_publishers():
    body, v = compute([entrance(1, publisher=OTHER_PUB)], served(1, 14))
    assert listed(body) == [] and "no signed release" in v[key(1)].why
    named = ls.ListCouncil(COUNCIL.lists, COUNCIL.claims, COUNCIL.reports, publishers=(PUB,))
    rels = {**RELS, OTHER_PUB: RELS[PUB]}
    body, v = compute([entrance(1, publisher=OTHER_PUB)], served(1, 14), releases=rels,
                      council=named)
    assert listed(body) == [] and "not one the council names" in v[key(1)].why
    body, v = compute([entrance(1, publisher=OTHER_PUB)], served(1, 14), releases=rels)
    assert listed(body) == [key(1)]                      # any publisher, when none are named
    assert json.loads(body)["entrances"][0]["publisher"] == OTHER_PUB


def test_decisions_remove_and_limit_per_operator():
    dec = ls.decisions_until([ls.Decision(TODAY - DAY, "p1",
                                          {"remove": {"list": "entrances", "entry": key(1)}})],
                             TODAY)
    body, v = compute([entrance(1)], served(1, 14), decisions=dec)
    assert listed(body) == [] and "decision" in v[key(1)].why
    dec = ls.decisions_until([ls.Decision(TODAY - DAY, "p2", {"set": {"max_per_operator": 1}})],
                             TODAY)
    anns = [entrance(1, operator="@x"), entrance(2, operator="@x")]
    body, v = compute(anns, served(1, 14) + served(2, 14, by=R2), previous=[key(2)],
                      decisions=dec)
    assert listed(body) == [key(2)] and "operator" in v[key(1)].why


def test_stale_and_later_announcements():
    body, _ = compute([entrance(1, d=TODAY - 40 * DAY)], served(1, 14))
    assert listed(body) == []
    body, _ = compute([entrance(1, d=TODAY + DAY)], served(1, 14))
    assert listed(body) == []


def test_imported_entries_stay_for_a_while():
    imp = {"url": "https://old.example/", "name": "old"}
    dup = {"onion": onion(1), "name": "same as e1"}
    body, _ = compute([], [], imported=[imp, dup], genesis=TODAY - 10 * DAY)
    assert sorted(listed(body)) == sorted(["https://old.example/", onion(1)])
    body, _ = compute([entrance(1)], served(1, 14), imported=[imp, dup], genesis=TODAY - 10 * DAY)
    assert sorted(listed(body)) == sorted(["https://old.example/", key(1)])
    body, _ = compute([], [], imported=[imp], genesis=TODAY - 200 * DAY)
    assert listed(body) == []
    dec = ls.decisions_until([ls.Decision(TODAY - DAY, "p3", {
        "remove": {"list": "entrances", "entry": "https://old.example/"}})], TODAY)
    body, _ = compute([], [], imported=[imp], genesis=TODAY - 10 * DAY, decisions=dec)
    assert listed(body) == []
    import_body = ls.import_body({"entrances": {"v": 1, "updated": "x",
                                                "entrances": [imp, {"url": "ftp://x"}]}})
    assert en.imported_entrances(import_body) == [imp]


def test_a_council_with_entrances_names_where_they_announce():
    base = {"claims": "c@abcdefghijklmnop", "reports": "r@abcdefghijklmnop",
            "lists": {"entrances": "e@abcdefghijklmnop"}}
    with pytest.raises(ls.ListProblem):
        ls.list_council(base)
    lc = ls.list_council({**base, "announce": {"entrances": "a@abcdefghijklmnop"}})
    assert lc.announce == {"entrances": "a@abcdefghijklmnop"}
    with pytest.raises(ls.ListProblem):
        ls.list_council({**base, "announce": {"nodes": "a@abcdefghijklmnop"}})


def test_report_served_must_be_reached():
    body = ls.canonical_json({"v": 1, "date": TODAY.isoformat(), "reached": [],
                              "missed": [key(1)], "served": {key(1): "1.0"}}) + "\n"
    with pytest.raises(ls.ListProblem):
        ls.parse_report(body, key=R1, date=at(TODAY + DAY, 1))


def test_the_list_parses_as_clients_read_it():
    from unseenet.known_nodes import parse_entrance_list
    body, _ = compute([entrance(1, url="https://web.example/")], served(1, 14))
    _, got = parse_entrance_list(body)
    assert got and got[0]["url"] == "https://web.example/"
