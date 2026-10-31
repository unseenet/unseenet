"""Council proposals, hearings and objections (UN-RFC 0061, #820): the rules, pure."""

from datetime import datetime, timedelta, timezone

import pytest

from unseenet.core import council as cn
from unseenet.core import crypto
from unseenet.core import proposals as pr

DAY = timedelta(days=1)
G = datetime(2026, 1, 1, tzinfo=timezone.utc)


def council(n=3, **kw):
    ids = [crypto.Identity.generate() for _ in range(n)]
    body = cn.council_body("unseenet.names", "channel", seq=1, date=G,
                           members=[cn.Member(i.public_key, G, True) for i in ids], **kw)
    gid = cn.make_council_group_id("unseenet.names", body)
    chain = cn.count_chain(gid, [(i.public_key, body) for i in ids])
    return ids, gid, chain


def item(n, subject, who, when, body="{}"):
    return pr.Item(f"<{n}@x>", subject, who if isinstance(who, str) else who.key_text, when, body)


def talk(ids, when):
    return [item(f"t{k}", "hello", i, when) for k, i in enumerate(ids)]


def test_a_proposal_and_its_id():
    pid, body = pr.make_proposal("unseenet.names@abcdefghijklmnop", 1,
                                 {"manifest": {"council": {"min_level": 3}}}, "cheaper keys")
    p = pr.parse_proposal(body)
    assert p.id == pid == pr.proposal_id(body) and p.days == 14 and p.kind == "manifest"
    with pytest.raises(pr.ProposalProblem):
        pr.make_proposal("g@abcdefghijklmnop", 1, {"manifest": {"fields": {"council": {}}}}, "x")
    with pytest.raises(pr.ProposalProblem):
        pr.make_proposal("g@abcdefghijklmnop", 1, {"manifest": {"council": {"members": []}}}, "x")
    with pytest.raises(pr.ProposalProblem):
        pr.make_proposal("g@abcdefghijklmnop", 1, {"list": {}}, "x", days=7)
    with pytest.raises(pr.ProposalProblem):
        pr.make_proposal("g@abcdefghijklmnop", 1, {"list": {}}, "")


def test_it_counts_with_a_quorum_of_active_members():
    ids, gid, chain = council(4)
    pid, body = pr.make_proposal(gid, 1, {"manifest": {"council": {"min_level": 3}}}, "why")
    t0 = G + 10 * DAY
    # three of four spoke in the last 90 days: active, quorum 2
    active_talk = talk(ids[:3], t0 - DAY)
    copies = [item("p1", f"proposal {pid}", ids[0], t0, body),
              item("p2", f"proposal {pid}", ids[3], t0 + DAY, body)]       # not active
    assert pr.hearings(chain, copies, active_talk) == []
    copies.append(item("p3", f"proposal {pid}", ids[1], t0 + 2 * DAY, body))
    (h,) = pr.hearings(chain, copies, active_talk)
    assert h.counted == t0 + 2 * DAY and h.ends == t0 + 16 * DAY
    # F, when the hearing began: the fourth became active by posting its copy
    assert h.active == 4
    # too late: the second copy after 7 days
    late = [copies[0], item("p4", f"proposal {pid}", ids[1], t0 + 8 * DAY, body)]
    assert pr.hearings(chain, late, active_talk) == []
    # nobody active: nothing can count
    assert pr.hearings(chain, copies, []) == []


def test_objections_and_the_outcome():
    ids, gid, chain = council(3)
    pid, body = pr.make_proposal(gid, 1, {"manifest": {"fields": {"title": "Navne"}}}, "a name")
    t0 = G + 10 * DAY
    act = talk(ids, t0 - DAY)
    copies = [item(f"p{k}", f"proposal {pid}", i, t0 + k * timedelta(hours=1), body)
              for k, i in enumerate(ids[:2])]
    (h,) = pr.hearings(chain, copies, act)
    assert h.active == 3

    def objection(n, who, when, **kw):
        return item(n, f"objection {pid}", who, when, pr.objection_body(pid, **kw))

    keys = [f"ed25519:k{i}" for i in range(8)]
    level = {k: 4 for k in keys} | {"ed25519:unripe": 2}
    ends = h.ends
    obj = [objection("o1", keys[0], h.counted + DAY, reason="nej"),
           objection("o2", keys[1], h.counted + DAY),
           objection("o3", "ed25519:unripe", h.counted + DAY),            # not ripe enough
           objection("o4", keys[2], h.counted - DAY),                     # before the hearing
           objection("o5", keys[0], h.counted + 2 * DAY, withdrawn=True)]  # taken back
    out = pr.outcome(h, obj, level, 4, ends + 2 * DAY)
    # O = 1 (k1): not more than F/2 = 1.5 -> passes, the day after it ended
    assert out.state == "passed" and out.objections == 1 and out.active == 3
    assert out.applies == ends.replace(hour=0, minute=0, second=0, microsecond=0) + DAY
    assert pr.outcome(h, obj, level, 4, ends + timedelta(hours=1)).state == "open"
    # two objections: extended once by 14 days, then decided
    obj2 = obj + [objection("o6", keys[3], h.counted + DAY)]
    assert pr.outcome(h, obj2, level, 4, ends + 2 * DAY).state == "extended"
    assert pr.outcome(h, obj2, level, 4, ends + 16 * DAY).state == "passed"
    obj3 = obj2 + [objection(f"o{7 + i}", keys[4 + i], ends + 3 * DAY) for i in range(2)]
    assert pr.outcome(h, obj3, level, 4, ends + 16 * DAY).state == "failed"
    # four in the first hearing: more than F, it fails at once
    obj4 = obj2 + [objection("o9", keys[4], h.counted + DAY), objection("o10", keys[5], ends)]
    assert pr.outcome(h, obj4, level, 4, ends + 2 * DAY).state == "failed"


def test_urgent_needs_two_thirds_and_lasts_three_days():
    ids, gid, chain = council(3)
    pid, body = pr.make_proposal(gid, 1, {"list": {"remove": "x"}}, "harm now", urgent=True)
    t0 = G + 10 * DAY
    act = talk(ids, t0 - DAY)
    two = [item(f"p{k}", f"proposal {pid}", i, t0, body) for k, i in enumerate(ids[:2])]
    (h,) = pr.hearings(chain, two, act)                    # 2 of 3 is two thirds
    assert h.ends == t0 + 3 * DAY


def test_a_passed_manifest_proposal_makes_the_next_manifest():
    f = cn.Founding(crypto.Identity.generate().public_key, G + 365 * DAY, 9)
    ids, gid, chain = council(2, founding=f)
    cur = chain.current
    _, body = pr.make_proposal(gid, 1, {"manifest": {
        "fields": {"title": "Navne"}, "council": {"min_level": 3}}}, "why")
    nxt = cn.CouncilManifest.from_body(gid, pr.applied_body(cur, pr.parse_proposal(body), G + 20 * DAY))
    assert nxt.seq == 2 and nxt.min_level == 3 and nxt.data["title"] == "Navne"
    assert nxt.members == cur.members
    assert cn.change_ok(cur, nxt, G) is None
    # an extension of the founding period, once it is over
    _, body = pr.make_proposal(gid, 1, {"manifest": {"council": {"until": "2027-06-01T00:00:00Z"}}},
                               "more time")
    when = G + 400 * DAY
    nxt = cn.CouncilManifest.from_body(gid, pr.applied_body(cur, pr.parse_proposal(body), when))
    assert cn.change_ok(cur, nxt, G) is None and nxt.founding.until.year == 2027
