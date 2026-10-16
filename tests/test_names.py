"""Names for identities: syntax, certificates, claims, revocations (UN-RFC 0019)."""

from datetime import datetime, timedelta, timezone

import pytest

from unseenet import names as nm
from unseenet.core import crypto
from unseenet.core.groups import canonical_json

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("name", ["lorensen", "abc", "a-b-c", "x2y", "a" * 32])
def test_good_registered_names(name):
    assert nm.check_name(name) == "registered"


@pytest.mark.parametrize("name", ["ab", "a" * 33, "1abc", "abc-", "ab--cd", "Lorensen", "ab_c", "æøå"])
def test_bad_registered_names(name):
    with pytest.raises(nm.NameProblem):
        nm.check_name(name)


@pytest.mark.parametrize("name", ["lorensen.dk", "unseenet.org", "a.b.c.example", "xn--bcher-kva.example"])
def test_good_domain_names(name):
    assert nm.check_name(name) == "domain"


@pytest.mark.parametrize("name", ["lorensen.dk.", "-a.dk", "a..dk", "Lorensen.dk", "a." + "b" * 64 + ".dk"])
def test_bad_domain_names(name):
    with pytest.raises(nm.NameProblem):
        nm.check_name(name)


def test_certificate_round_trip_and_accept():
    reg, me, other = (crypto.Identity.generate() for _ in range(3))
    cert = nm.make_certificate(reg, "lorensen", me.key_text, 1, NOW)
    assert cert.kind == "registered" and cert.expires - cert.issued == timedelta(days=365)
    again = nm.certificate_from_header(cert.header_value())
    assert again == cert and again.raw == cert.raw
    regs = {reg.key_text}
    assert nm.accept(cert, author_key=me.key_text, registrars=regs, now=NOW + timedelta(days=1))
    assert not nm.accept(cert, author_key=other.key_text, registrars=regs, now=NOW)       # not theirs
    assert not nm.accept(cert, author_key=me.key_text, registrars=set(), now=NOW)          # untrusted
    assert not nm.accept(cert, author_key=me.key_text, registrars=regs, now=NOW + timedelta(days=400))
    assert not nm.accept(cert, author_key=me.key_text, registrars=regs, now=NOW,
                         revoked={("lorensen", 1)})


def test_domain_certificates_last_35_days():
    reg, me = crypto.Identity.generate(), crypto.Identity.generate()
    cert = nm.make_certificate(reg, "lorensen.dk", me.key_text, 1, NOW)
    assert cert.kind == "domain" and cert.expires - cert.issued == timedelta(days=35)


def test_tampered_certificates_are_rejected():
    reg, me, thief = (crypto.Identity.generate() for _ in range(3))
    raw = dict(nm.make_certificate(reg, "lorensen", me.key_text, 1, NOW).raw)
    raw["key"] = thief.key_text
    with pytest.raises(nm.NameProblem, match="signature"):
        nm.parse_certificate(canonical_json(raw))
    raw = dict(nm.make_certificate(reg, "lorensen", me.key_text, 1, NOW).raw)
    raw["kind"] = "domain"
    with pytest.raises(nm.NameProblem):
        nm.parse_certificate(canonical_json(raw))
    with pytest.raises(nm.NameProblem):
        nm.certificate_from_header("not base64 !!")


def test_overlong_lifetime_is_rejected():
    reg, me = crypto.Identity.generate(), crypto.Identity.generate()
    data = {"v": 1, "name": "lorensen.dk", "kind": "domain", "key": me.key_text,
            "issued": nm.rfc3339(NOW), "expires": nm.rfc3339(NOW + timedelta(days=365)),
            "serial": 1, "registrar": reg.key_text}
    data["sig"] = reg.sign_text(nm.PURPOSE_NAME_CERT, canonical_json(data).encode())
    with pytest.raises(nm.NameProblem, match="lifetime"):
        nm.parse_certificate(canonical_json(data))


def test_current_picks_highest_serial_and_spots_disputes():
    reg, a, b = (crypto.Identity.generate() for _ in range(3))
    c1 = nm.make_certificate(reg, "lorensen", a.key_text, 1, NOW)
    c2 = nm.make_certificate(reg, "lorensen", b.key_text, 2, NOW)
    assert nm.current([c1, c2]) == (c2, False)
    c2a = nm.make_certificate(reg, "lorensen", a.key_text, 2, NOW)
    assert nm.current([c1, c2, c2a]) == (None, True)
    assert nm.current([]) == (None, False)


def test_claims():
    other = crypto.Identity.generate()
    body = nm.make_claim("claim", "lorensen")
    assert nm.parse_claim(body) == {"v": 1, "action": "claim", "name": "lorensen"}
    assert nm.parse_claim(nm.make_claim("transfer", "lorensen", other.key_text))["to"] == other.key_text
    with pytest.raises(nm.NameProblem):
        nm.make_claim("transfer", "lorensen")
    with pytest.raises(nm.NameProblem):
        nm.parse_claim('{"action":"steal","name":"lorensen","v":1}\n')
    with pytest.raises(nm.NameProblem):
        nm.parse_claim('{"action":"claim","name":"No Way","v":1}\n')


def test_revocations_round_trip():
    revoked = {("lorensen", 1), ("abc", 3)}
    assert nm.parse_revocations(nm.make_revocations(revoked)) == revoked


def test_dns_record():
    me = crypto.Identity.generate()
    assert nm.dns_record_name("lorensen.dk") == "_unseenet.lorensen.dk"
    assert nm.dns_record_value(me.key_text) == f"unseenet-key={me.key_text}"


def test_replicas_make_identical_decisions_from_a_claim():
    r1, r2, me = (crypto.Identity.generate() for _ in range(3))
    when = NOW - timedelta(hours=2)
    a = nm.make_certificate(r1, "lorensen", me.key_text, 1, claim="<c1@unseenet>", claimed=when)
    b = nm.make_certificate(r2, "lorensen", me.key_text, 1, claim="<c1@unseenet>", claimed=when)
    assert a.issued == when and a.claim == "<c1@unseenet>"
    again = nm.make_certificate(r1, "lorensen", me.key_text, 1, NOW, claim="<c1@unseenet>", claimed=when)
    assert again.to_json() == a.to_json()                     # deterministic: same bytes
    assert nm.current([a, b]) == (a, False)                   # one decision, two keys
    assert nm.keys_for([a, b], a.decision) == {r1.key_text, r2.key_text}
    assert nm.parse_certificate(a.to_json()).claimed == when


def test_earlier_claim_wins_a_split_decision():
    r1, r2, alice, bob = (crypto.Identity.generate() for _ in range(4))
    early, late = NOW - timedelta(hours=3), NOW - timedelta(hours=2)
    alices = nm.make_certificate(r1, "lorensen", alice.key_text, 1, claim="<a@unseenet>", claimed=early)
    bobs = nm.make_certificate(r2, "lorensen", bob.key_text, 1, claim="<b@unseenet>", claimed=late)
    assert nm.current([bobs, alices]) == (alices, False)
    # the same claim given to two keys can only be a lie: disputed
    liar = nm.make_certificate(r2, "lorensen", bob.key_text, 1, claim="<a@unseenet>", claimed=early)
    assert nm.current([alices, liar]) == (None, True)
    # without claims the old rule holds
    plain = nm.make_certificate(r2, "lorensen", bob.key_text, 1, NOW)
    assert nm.current([alices, plain]) == (None, True)


def test_claim_and_claimed_go_together():
    reg, me = crypto.Identity.generate(), crypto.Identity.generate()
    with pytest.raises(nm.NameProblem):
        nm.make_certificate(reg, "lorensen", me.key_text, 1, claim="<x@unseenet>")
    raw = dict(nm.make_certificate(reg, "lorensen", me.key_text, 1, claim="<x@unseenet>",
                                   claimed=NOW).raw)
    del raw["claimed"], raw["sig"]
    raw["sig"] = reg.sign_text(nm.PURPOSE_NAME_CERT, canonical_json(raw).encode())
    with pytest.raises(nm.NameProblem, match="together"):
        nm.parse_certificate(canonical_json(raw))
