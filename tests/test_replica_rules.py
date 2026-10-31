"""The rules every replica computes alike (UN-RFC 0054 sections 9-13, 19, 20, #690):
reports, judging shadows, removals and the order of changes - pure functions, no node."""

from datetime import datetime, timedelta, timezone

from unseenet import names as nm
from unseenet.core import council as cn
from unseenet.core import crypto
from unseenet.replica import rules

DAY = timedelta(days=1)
G = datetime(2026, 1, 1, tzinfo=timezone.utc)          # the genesis


def keys(n):
    return [crypto.Identity.generate() for _ in range(n)]


def chain_of(*bodies, group):
    """Count a chain from bodies every member of the one before signed."""
    copies = []
    prev = None
    for b in bodies:
        m = cn.CouncilManifest.from_body(group, b)
        signers = (m if prev is None else prev).keys
        copies += [(k, b) for k in signers]
        prev = m
    return cn.count_chain(group, copies)


def genesis(members, founding=None, **kw):
    body = cn.council_body("unseenet.names", "channel", seq=1, date=G,
                           members=[cn.Member(k.public_key, G, True) for k in members],
                           founding=founding, **kw)
    return cn.make_council_group_id("unseenet.names", body), body


def decisions_for(days, per_day=2, dns=False):
    out = []
    for d in days:
        for i in range(per_day):
            out.append(rules.Decision(f"<{d:%m%d}-{i}@x>", d, f"h{i}", dns))
    return out


def report_post(author, day, decisions, late=0):
    body = rules.report_body(day, decisions)
    posted = day + (rules.REPORT_LAG + late) * DAY + timedelta(hours=3)
    return nm.Post(f"<r{day:%m%d}{author[-4:]}@x>", rules.report_subject(day), author, posted, body)


def test_a_report_counts_only_on_its_day_and_for_its_day():
    d = G + 10 * DAY
    dec = decisions_for([d])
    p = report_post("ed25519:shadow", d, dec)
    r = rules.parse_report(p)
    assert r.day == d and r.decisions == {x.commit: x.hash for x in dec}
    assert rules.parse_report(report_post("ed25519:shadow", d, dec, late=1)) is None
    assert rules.day_agrees(r, dec) is True
    wrong = [rules.Decision(dec[0].commit, d, "other", False)]
    assert rules.day_agrees(r, wrong) is False
    dns = [rules.Decision(dec[0].commit, d, "other", True)]
    assert rules.day_agrees(r, dns) is True                   # DNS decisions may differ
    missing = dec + [rules.Decision("<missing@x>", d, "h", False)]
    assert rules.day_agrees(r, missing) is False              # every claim handled that day


def test_a_shadow_is_eligible_after_55_of_60_days():
    shadow = "ed25519:shadow"
    days = [G + i * DAY for i in range(80)]
    dec = decisions_for(days)
    skipped = {G + 5 * DAY, G + 6 * DAY, G + 7 * DAY, G + 8 * DAY, G + 9 * DAY}
    posts = [report_post(shadow, d, dec) for d in days if d not in skipped]
    judge = rules.Judge(dec, rules.reports_by_key(posts), G)
    since = judge.eligible_since(shadow, G + 90 * DAY)
    assert since == G + 68 * DAY            # the first window that is all settled and known
    # six days missing in a window is one too many
    skipped.add(G + 10 * DAY)
    posts = [report_post(shadow, d, dec) for d in days if d not in skipped]
    judge = rules.Judge(dec, rules.reports_by_key(posts), G)
    assert judge.eligible_since(shadow, G + 70 * DAY) is None
    assert judge.eligible_since(shadow, G + 90 * DAY) == G + 74 * DAY   # one fell out
    # one disagreement keeps it out for the 60 days that see it
    bad = [rules.Decision(dec[0].commit, dec[0].day, "wrong", False)] + dec[1:]
    posts = [report_post(shadow, d, bad) for d in days]
    judge = rules.Judge(dec, rules.reports_by_key(posts), G)
    assert judge.eligible_since(shadow, G + 68 * DAY) is None
    assert judge.eligible_since(shadow, G + 90 * DAY) == G + 69 * DAY


def world(chain, judge=None, **kw):
    base = dict(chain=chain, judge=judge or rules.Judge([], {}, G), certs=[], decisions={},
                last_post={}, resigned={}, level={})
    base.update(kw)
    return rules.World(**base)


def active(members, when):
    return {k.key_text: when for k in members}


def test_the_oldest_eligible_shadow_is_admitted_after_30_days():
    a, b, c = keys(3)
    gid, body = genesis([a, b, c])
    chain = chain_of(body, group=gid)
    days = [G + i * DAY for i in range(80)]
    dec = decisions_for(days)
    s1, s2 = crypto.Identity.generate().key_text, crypto.Identity.generate().key_text
    posts = ([report_post(s2, d, dec) for d in days[1:]]
             + [report_post(s1, d, dec) for d in days])            # s1 reported first
    judge = rules.Judge(dec, rules.reports_by_key(posts), G)
    w = world(chain, judge, last_post=active([a, b, c], G + 75 * DAY), level={s1: 4, s2: 4})
    ch = rules.next_change(w, G + 75 * DAY)
    assert ch.kind == "admission" and ch.key == s1 and ch.date == G + 68 * DAY
    m = cn.CouncilManifest.from_body(gid, ch.body)
    assert m.member(crypto.key_from_text(s1)) == cn.Member(crypto.key_from_text(s1), ch.date, False)
    # an unripe key waits
    w = world(chain, judge, last_post=active([a, b, c], G + 75 * DAY), level={s1: 3, s2: 4})
    assert rules.next_change(w, G + 75 * DAY).key == s2
    # nothing before its day
    assert rules.next_change(w, G + 60 * DAY) is None


def test_removals_come_first_and_take_their_date_from_the_articles():
    a, b, c = keys(3)
    gid, body = genesis([a, b, c])
    chain = chain_of(body, group=gid)
    today = G + 200 * DAY
    # c fell silent: last article on day 10 -> removed on day 100
    w = world(chain, last_post={a.key_text: today, b.key_text: today, c.key_text: G + 10 * DAY})
    ch = rules.next_change(w, today)
    assert (ch.kind, ch.key, ch.date) == ("removal", c.key_text, G + 100 * DAY)
    # b stepped down earlier: that reason arose first
    w = world(chain, last_post={a.key_text: today, b.key_text: today, c.key_text: G + 10 * DAY},
              resigned={b.key_text: G + 50 * DAY + timedelta(hours=7)})
    ch = rules.next_change(w, today)
    assert (ch.kind, ch.key, ch.date, ch.why) == ("removal", b.key_text, G + 50 * DAY, "stepped down")


def test_a_certificate_no_claim_explains_removes_its_signer():
    a, b, c = keys(3)
    gid, body = genesis([a, b, c])
    chain = chain_of(body, group=gid)
    user = crypto.Identity.generate().key_text
    when = G + 20 * DAY
    good = nm.make_certificate(a, "lorensen", user, 1, claim="<c1@x>", claimed=when)
    forged = nm.make_certificate(c, "microsoft", user, 1, claim="<nothing@x>", claimed=when)
    issued = rules.outcome(("lorensen", user, 1, good.expires))
    from unseenet.core.groups import canonical_json
    decisions = {"<c1@x>": (canonical_json(issued), False)}
    certs = [rules.Cert(good, when + timedelta(hours=2)), rules.Cert(forged, when + 3 * DAY)]
    today = G + 30 * DAY
    w = world(chain, certs=certs, decisions=decisions, last_post=active([a, b, c], today))
    ch = rules.next_change(w, today)
    assert ch.kind == "removal" and ch.key == c.key_text and ch.date == G + 23 * DAY
    assert "no claim explains" in ch.why
    assert not rules.unexplained(certs[0], decisions, G)
    # a replica that has not reached the commit yet does not judge it
    assert not rules.unexplained(certs[1], decisions, G, now=when + 2 * DAY)
    assert rules.unexplained(certs[1], decisions, G, now=when + 9 * DAY)


def test_promotion_after_probation_and_founder_admissions():
    a, b = keys(2)
    founder = a
    f = cn.Founding(founder.public_key, G + 3 * 365 * DAY, 9)
    gid, body = genesis([a, b], founding=f)
    chain = chain_of(body, group=gid)
    newcomer = crypto.Identity.generate().key_text
    days = [G + i * DAY for i in range(30)]
    dec = decisions_for(days)
    posts = [report_post(newcomer, d, dec) for d in days]
    judge = rules.Judge(dec, rules.reports_by_key(posts), G)
    today = G + 25 * DAY
    w = world(chain, judge, last_post=active([a, b], today), level={newcomer: 4},
              admits=[(G + 3 * DAY, newcomer)])
    ch = rules.next_change(w, today)
    # 7 settled days reported and agreeing: from day 15 (days 0-6 settle by day 15)
    assert ch.kind == "admission" and ch.by_founder and ch.date == G + 15 * DAY
    m2 = cn.CouncilManifest.from_body(gid, ch.body)
    chain2 = chain_of(body, ch.body, group=gid)
    assert chain2.current.seq == 2 and chain2.current.member(m2.members[-1].key).by == cn.FOUNDER
    # 30 days later it is promoted
    today = G + 50 * DAY
    w = world(chain2, judge, last_post=active([a, b], today), level={newcomer: 4})
    ch = rules.next_change(w, today)
    assert (ch.kind, ch.key, ch.date) == ("promotion", newcomer, G + 45 * DAY)
    # a renunciation waits for the change of members, then follows
    w = world(chain2, judge, last_post=active([a, b], today), level={newcomer: 4},
              renounced=G + 47 * DAY)
    promo = rules.next_change(w, today)
    assert promo.kind == "promotion"
    chain3 = chain_of(body, ch_body(chain2), promo.body, group=gid)
    w = world(chain3, judge, last_post=active([a, b], today), renounced=G + 47 * DAY)
    ren = rules.next_change(w, today)
    assert ren.kind == "renunciation" and ren.date == G + 47 * DAY
    assert cn.CouncilManifest.from_body(gid, ren.body).founding.renounced


def ch_body(chain):
    return chain.current.body


def test_sponsors_one_per_member_in_180_days():
    a, b = "ed25519:a", "ed25519:b"
    t = G
    posts = [nm.Post("<1@x>", "sponsor ed25519:s1", a, t, "{}"),
             nm.Post("<2@x>", "sponsor ed25519:s2", b, t, "{}"),
             nm.Post("<3@x>", "sponsor ed25519:s3", b, t + DAY, "{}"),
             nm.Post("<4@x>", "unsponsor ed25519:s3", b, t + 2 * DAY, "{}")]
    got = rules.sponsorships(posts, members={a, b}, full={a, b})
    # b also sponsored s3 within 180 days - withdrawn or not, it was posted - so b's
    # sponsorship of s2 does not count either: one per member in 180 days
    assert got == {"ed25519:s1": {a}}
