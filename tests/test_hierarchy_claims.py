"""Hierarchy claims and the root list a list council keeps (UN-RFC 0020 5.2, 6.2): pure."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from unseenet import hierarchies as hz
from unseenet import names as nm
from unseenet.core import crypto
from unseenet.core import hierarchy_claims as hc

G = datetime(2026, 11, 2, tzinfo=timezone.utc)
H = timedelta(hours=1)
DAY = timedelta(days=1)
INBOX = "inbox@abcdefghijklmnop"
N = [0]


def ident():
    return crypto.Identity.generate()


def list_of(i, name):
    return f"{name}.list@{i.fingerprint}"


def posts_for(i, claim_body, when, nonce=None):
    """A commit at ``when`` and its reveal two hours later, as posts."""
    N[0] += 1
    body, nonce = hc.make_commit(claim_body, nonce)
    cid = f"<c{N[0]}@x>"
    return cid, [nm.Post(cid, nm.COMMIT_SUBJECT, i.key_text, when, body),
                 nm.Post(f"<r{N[0]}@x>", nm.reveal_subject(cid), i.key_text, when + 2 * H,
                         hc.make_reveal(claim_body, nonce, INBOX))]


def run(posts, *, until=None, imported=None, reserved=frozenset(), tlds=frozenset({"dk", "com"}),
        level=None, dns=None, dns_gone=frozenset(), removed=frozenset()):
    claims = hc.read_claims(posts)
    keys = {p.author for p in posts}
    return hc.apply_claims(claims, until=until or G + 30 * DAY, genesis=G,
                           imported=imported or {}, reserved=set(reserved), removed=set(removed),
                           tlds=set(tlds), level=level or {k: 3 for k in keys}, min_level=3,
                           dns=dns or {}, dns_gone=set(dns_gone))


def test_a_claim_body_and_its_checks():
    a = ident()
    b = hc.make_claim("claim", "games", list=list_of(a, "games"), title="Games")
    assert hc.parse_claim(b)["name"] == "games"
    for bad in (dict(action="claim", name="Games", list=list_of(a, "x"), title="t"),
                dict(action="claim", name="games", list=list_of(a, "x")),            # no title
                dict(action="claim", name="a.b", list=list_of(a, "x"), title="t"),
                dict(action="change", name="games", list=list_of(a, "x")),           # no maintainer
                dict(action="steal", name="games")):
        with pytest.raises(nm.NameProblem):
            hc.make_claim(**bad)
    # a hierarchy commit is not a name commit: other domain separation
    body, nonce = hc.make_commit(b)
    assert nm.parse_commit(body) != nm.commit_value(nonce, nm.make_claim("claim", "lorensen"))


def test_first_claim_wins_and_lasts_a_year():
    a, b = ident(), ident()
    ca, pa = posts_for(a, hc.make_claim("claim", "games", list=list_of(a, "games"), title="Games"), G)
    cb, pb = posts_for(b, hc.make_claim("claim", "games", list=list_of(b, "games"), title="Mine"), G + H)
    st = run(pa + pb)
    assert st.grants["games"].maintainer == a.key_text
    assert st.why[ca] == "claim games: granted" and "held by" in st.why[cb]
    # a year later it lapsed, unless renewed
    assert "games" not in run(pa, until=G + 366 * DAY).grants
    _, pr = posts_for(a, hc.make_claim("renew", "games"), G + 300 * DAY)
    assert "games" in run(pa + pr, until=G + 366 * DAY).grants
    # somebody else cannot renew it
    cx, px = posts_for(b, hc.make_claim("renew", "games"), G + 300 * DAY)
    st = run(pa + px, until=G + 366 * DAY)
    assert "games" not in st.grants and "only its maintainer" in st.why[cx]


def test_the_limits():
    a = ident()
    posts = []
    for k, name in enumerate(("aa", "bb", "cc", "dd")):
        posts += posts_for(a, hc.make_claim("claim", name, list=list_of(a, name), title=name),
                           G + k * H)[1]
    st = run(posts)
    assert sorted(st.grants) == ["aa", "bb", "cc"]              # three per key
    c, p = posts_for(a, hc.make_claim("claim", "usenet", list=list_of(a, "u"), title="u"), G)
    assert "reserved" in run(p, reserved={"usenet"}).why[c]
    c, p = posts_for(a, hc.make_claim("claim", "ee", list=list_of(a, "e"), title="e"), G)
    assert "ripened" in run(p, level={a.key_text: 2}).why[c]
    b = ident()
    c, p = posts_for(a, hc.make_claim("claim", "ff", list=list_of(b, "f"), title="f"), G)
    assert "not the claiming key's" in run(p).why[c]


def test_a_tld_name_needs_its_registry_in_dns():
    a = ident()
    c, p = posts_for(a, hc.make_claim("claim", "dk", list=list_of(a, "dk"), title="Danmark"), G)
    assert hc.needs_dns(hc.make_claim("claim", "dk", list=list_of(a, "dk"), title="Danmark"),
                        {"dk"})
    assert "nic.dk" in run(p).why[c]
    st = run(p, dns={c: True}, until=G + 800 * DAY)
    assert st.grants["dk"].expires is None and "dk" in st.grants   # held while DNS says so
    assert "dk" not in run(p, dns={c: True}, dns_gone={"dk"}).grants


def test_change_and_release():
    a, b = ident(), ident()
    _, p1 = posts_for(a, hc.make_claim("claim", "games", list=list_of(a, "g"), title="G"), G)
    _, p2 = posts_for(a, hc.make_claim("change", "games", list=list_of(b, "g"),
                                       maintainer=b.key_text), G + DAY)
    st = run(p1 + p2)
    assert st.grants["games"].maintainer == b.key_text
    _, p3 = posts_for(b, hc.make_claim("release", "games"), G + 2 * DAY)
    assert "games" not in run(p1 + p2 + p3).grants


def test_the_root_list_with_the_import():
    project = ident()
    text = json.dumps({"v": 1, "updated": "2026-10-31", "hierarchies": [
        {"name": "unseenet", "policy": "governed", "maintainer": project.key_text,
         "list": f"unseenet.checkgroups@{project.fingerprint}", "title": "The Unseenet project"},
        {"name": "alt", "policy": "free", "title": "Anything goes"},
        {"name": "usenet", "policy": "reserved", "title": "Usenet"}]})
    _, imported = hz.parse_root_list(text)
    a = ident()
    c, p = posts_for(a, hc.make_claim("claim", "games", list=list_of(a, "g"), title="Games"), G)
    reserved = {n for n, h in imported.items() if h.policy == "reserved"} | {"nic"}
    st = run(p, imported=imported, reserved=reserved)
    body = hc.root_list(date(2026, 11, 3), 1, st, imported, reserved)
    _, root = hz.parse_root_list(body)
    assert root["games"].maintainer == a.key_text and root["games"].policy == "governed"
    assert root["unseenet"].maintainer == project.key_text          # held as if claimed at genesis
    assert root["alt"].policy == "free" and root["usenet"].policy == "reserved"
    assert root["nic"].policy == "reserved"
    # the imported governed entry lapses a year after the genesis unless renewed
    assert "unseenet" not in run(p, imported=imported, until=G + 366 * DAY).grants
