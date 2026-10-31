"""Council groups: IDs, council manifests and counting the chain (UN-RFC 0054 Part I)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError
from unseenet.core.council import (
    CouncilManifest, Member, council_article, council_body, council_fingerprint,
    copies_to_keep, count_chain, is_council_manifest, make_council_group_id, next_body,
    quorum)

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def keys(n):
    return [crypto.Identity.generate() for _ in range(n)]


def genesis(ids, name="unseenet.lists", gtype="channel", **kw):
    members = [Member(i.public_key, T0, True) for i in ids]
    body = council_body(name, gtype, seq=1, date=T0, members=members, **kw)
    return make_council_group_id(name, body), body


def signed(ids, body):
    """Every one of ``ids`` posts exactly ``body``."""
    return [(i.public_key, body) for i in ids]


def test_fingerprint_is_of_the_genesis_body_and_never_a_keys():
    ids = keys(3)
    gid, body = genesis(ids)
    assert gid.endswith("@" + council_fingerprint(body))
    assert council_fingerprint(body) != crypto.fingerprint(ids[0].public_key)
    assert council_fingerprint(body + "\r\n") == council_fingerprint(body)


def test_genesis_counts_when_every_member_posted_it():
    ids = keys(3)
    gid, body = genesis(ids)
    chain = count_chain(gid, signed(ids, body))
    assert chain.current is not None and chain.current.seq == 1
    assert len(count_chain(gid, signed(ids[:2], body)).counted) == 0


def test_genesis_needs_two_members_and_the_right_group():
    one = keys(1)
    gid, body = genesis(one)
    assert count_chain(gid, signed(one, body)).current is None
    ids = keys(2)
    _, body = genesis(ids)
    other, _ = genesis(keys(2))
    assert count_chain(other, signed(ids, body)).current is None


def test_a_council_manifest_is_not_an_owners():
    ids = keys(2)
    gid, body = genesis(ids)
    art = council_article(ids[0], gid, body, pow_bits=0)
    assert is_council_manifest(art)
    m = CouncilManifest.from_article(art)
    assert m.seq == 1 and m.full == [i.public_key for i in ids]
    bad = body.replace('"type":"channel"', '"type":"closed"')
    with pytest.raises(ArticleError):
        CouncilManifest.from_body(gid, bad)


def chain_of(n_members, **kw):
    ids = keys(n_members)
    gid, body = genesis(ids, **kw)
    copies = signed(ids, body)
    return ids, gid, copies, count_chain(gid, copies).current


def test_admission_promotion_and_removal():
    ids, gid, copies, g = chain_of(3)
    new = crypto.Identity.generate()
    d1 = T0 + timedelta(days=30)
    b2 = next_body(g, date=d1, members=g.members + [Member(new.public_key, d1, False)])
    copies += signed(ids[:2], b2)                       # 2 of 3 is a majority
    chain = count_chain(gid, copies)
    assert chain.current.seq == 2 and chain.current.on_probation == [new.public_key]

    d2 = d1 + timedelta(days=180)
    promoted = [m if m.key != new.public_key else Member(m.key, d1, True)
                for m in chain.current.members]
    b3 = next_body(chain.current, date=d2, members=promoted)
    copies += signed(ids[:2], b3)
    chain = count_chain(gid, copies)
    assert chain.current.seq == 3 and len(chain.current.full) == 4

    b4 = next_body(chain.current, date=d2, members=[m for m in promoted if m.key != ids[2].public_key])
    copies += signed(ids[:2], b4)                       # 4 full, 3 remain: needs 2 of 3
    assert count_chain(gid, copies).current.seq == 4


def test_admission_too_early_or_too_many_on_probation():
    ids, gid, copies, g = chain_of(3)
    a, b = keys(2)
    early = T0 + timedelta(days=29)
    b2 = next_body(g, date=early, members=g.members + [Member(a.public_key, early, False)])
    assert count_chain(gid, copies + signed(ids, b2)).current.seq == 1
    d1 = T0 + timedelta(days=30)
    b2 = next_body(g, date=d1, members=g.members + [Member(a.public_key, d1, False)])
    copies += signed(ids, b2)
    m2 = count_chain(gid, copies).current
    d2 = d1 + timedelta(days=30)
    b3 = next_body(m2, date=d2, members=m2.members + [Member(b.public_key, d2, False)])
    assert count_chain(gid, copies + signed(ids, b3)).current.seq == 2     # max_probation 1


def test_one_change_at_a_time_and_two_full_left():
    ids, gid, copies, g = chain_of(3)
    d = T0 + timedelta(days=1)
    two_out = next_body(g, date=d, members=g.members[:1])
    assert count_chain(gid, copies + signed(ids, two_out)).current.seq == 1
    ids, gid, copies, g = chain_of(2)
    one_left = next_body(g, date=d, members=g.members[:1])
    assert count_chain(gid, copies + signed(ids, one_left)).current.seq == 1


def test_quorum_and_the_removed_does_not_count():
    assert [quorum(n) for n in (1, 2, 3, 4, 5)] == [2, 2, 2, 3, 3]
    ids, gid, copies, g = chain_of(4)
    d = T0 + timedelta(days=1)
    out = next_body(g, date=d, members=g.members[:3])     # remove ids[3]
    # ids[3] posting it does not help: 3 remain, so 2 of them are needed
    assert count_chain(gid, copies + signed([ids[0], ids[3]], out)).current.seq == 1
    assert count_chain(gid, copies + signed(ids[:2], out)).current.seq == 2
    # one member alone is never a quorum
    change = next_body(g, date=d, title="x")
    assert count_chain(gid, copies + signed([ids[0]], change)).current.seq == 1


def test_wrong_prev_does_not_count():
    ids, gid, copies, g = chain_of(3)
    body = next_body(g, date=T0 + timedelta(days=1), title="t")
    wrong = body.replace(g.hash, "x" * len(g.hash))
    assert count_chain(gid, copies + signed(ids, wrong)).current.seq == 1


def test_a_fork_freezes_the_chain_before_it():
    ids, gid, copies, g = chain_of(3)
    d = T0 + timedelta(days=1)
    a = next_body(g, date=d, title="a")
    b = next_body(g, date=d, title="b")
    chain = count_chain(gid, copies + signed(ids, a) + signed(ids, b))
    assert chain.disputed and chain.fork_seq == 2 and chain.current.seq == 1


def test_catching_up_in_any_order_and_keeping_the_copies():
    ids, gid, copies, g = chain_of(3)
    b2 = next_body(g, date=T0 + timedelta(days=1), title="two")
    copies += signed(ids, b2)
    chain = count_chain(gid, list(reversed(copies)))
    assert chain.current.seq == 2
    with_ids = [(a, b, f"<{n}@x>") for n, (a, b) in enumerate(copies)]
    keep = copies_to_keep(chain, with_ids)
    assert len(keep) == len(with_ids)


def test_other_fields_change_through_the_council():
    ids, gid, copies, g = chain_of(2, fields={"title": "Lists", "min_pow": 20})
    b2 = next_body(g, date=T0 + timedelta(days=1), min_pow=22, min_level=5)
    m = count_chain(gid, copies + signed(ids, b2)).current
    assert m.data["min_pow"] == 22 and m.min_level == 5 and m.data["title"] == "Lists"


# --- the founding period (section 19) ---------------------------------------

from unseenet.core.council import FOUNDER, Founding  # noqa: E402


def founded(n=2, size=9, years=3, **kw):
    ids = keys(n)
    founder = ids[0]
    f = Founding(founder.public_key, T0 + timedelta(days=365 * years), size, **kw)
    gid, body = genesis(ids, founding=f)
    copies = signed(ids, body)
    return ids, gid, copies, count_chain(gid, copies).current


def admit(prev, key, date, by=FOUNDER):
    return next_body(prev, date=date, members=prev.members + [Member(key, date, False, by)])


def test_a_founder_admission_after_7_days_and_30_days_on_probation():
    ids, gid, copies, g = founded()
    new = crypto.Identity.generate()
    early = T0 + timedelta(days=6)
    assert count_chain(gid, copies + signed(ids, admit(g, new.public_key, early))).current.seq == 1
    d = T0 + timedelta(days=7)
    copies += signed(ids, admit(g, new.public_key, d))
    m2 = count_chain(gid, copies).current
    assert m2.seq == 2 and m2.member(new.public_key).by == FOUNDER
    promoted = [x if x.key != new.public_key else Member(x.key, d, True, FOUNDER) for x in m2.members]
    too_soon = next_body(m2, date=d + timedelta(days=29), members=promoted)
    assert count_chain(gid, copies + signed(ids, too_soon)).current.seq == 2
    copies += signed(ids, next_body(m2, date=d + timedelta(days=30), members=promoted))
    assert len(count_chain(gid, copies).current.full) == 3


def test_two_founder_admissions_on_probation_at_once_not_three():
    ids, gid, copies, g = founded()
    a, b, c = keys(3)
    copies += signed(ids, admit(g, a.public_key, T0 + timedelta(days=7)))
    m = count_chain(gid, copies).current
    copies += signed(ids, admit(m, b.public_key, T0 + timedelta(days=14)))
    m = count_chain(gid, copies).current
    assert m.seq == 3 and len(m.on_probation) == 2
    assert count_chain(gid, copies + signed(ids, admit(m, c.public_key, T0 + timedelta(days=21)))).current.seq == 3


def test_no_founder_admission_after_the_period_or_at_size():
    ids, gid, copies, g = founded(years=1)
    late = T0 + timedelta(days=366)
    assert count_chain(gid, copies + signed(ids, admit(g, keys(1)[0].public_key, late))).current.seq == 1
    ids, gid, copies, g = founded(size=2)                        # 2 full already
    d = T0 + timedelta(days=7)
    assert count_chain(gid, copies + signed(ids, admit(g, keys(1)[0].public_key, d))).current.seq == 1


def test_no_founding_period_no_founder_admission():
    ids, gid, copies, g = chain_of(3)
    d = T0 + timedelta(days=30)
    assert count_chain(gid, copies + signed(ids, admit(g, keys(1)[0].public_key, d))).current.seq == 1


def test_the_genesis_founding_period_is_at_most_3_years():
    ids = keys(2)
    f = Founding(ids[0].public_key, T0 + timedelta(days=365 * 4), 9)
    gid, body = genesis(ids, founding=f)
    assert count_chain(gid, signed(ids, body)).current is None


def test_renouncing_and_extending():
    from dataclasses import replace
    ids, gid, copies, g = founded(years=1)
    d = T0 + timedelta(days=10)
    renounced = next_body(g, date=d, founding=replace(g.founding, renounced=True))
    m = count_chain(gid, copies + signed(ids, renounced)).current
    assert m.seq == 2 and m.founding.renounced and not m.founding_lasts(d)
    back = next_body(m, date=d, founding=replace(m.founding, renounced=False))
    assert count_chain(gid, copies + signed(ids, renounced) + signed(ids, back)).current.seq == 2

    # extending: only once over, at most a year ahead
    while_on = next_body(g, date=d, founding=replace(g.founding, until=g.founding.until + timedelta(days=30)))
    assert count_chain(gid, copies + signed(ids, while_on)).current.seq == 1
    over = g.founding.until + timedelta(days=1)
    ext = next_body(g, date=over, founding=replace(g.founding, until=over + timedelta(days=365)))
    assert count_chain(gid, copies + signed(ids, ext)).current.seq == 2
    too_far = next_body(g, date=over, founding=replace(g.founding, until=over + timedelta(days=400)))
    assert count_chain(gid, copies + signed(ids, too_far)).current.seq == 1
