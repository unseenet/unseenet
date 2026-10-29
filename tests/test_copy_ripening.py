"""UN-RFC 0050 3.6/3.7 as amended (#759): a copied key brings its ripening chain; the new
vault keeps it when it checks out and reaches further, drops it otherwise, and the
copy goes on either way."""
import secrets

import pytest

from unseenet.core import copying as cp
from unseenet.core import crypto
from unseenet.core import ripening as rp

pytest.importorskip("chiavdf")
pytestmark = pytest.mark.usefixtures("ripening_rules")


def _vault_with(seed: bytes, chain=None) -> dict:
    ident = crypto.Identity.from_seed(seed)
    data = {"identities": {"andreas": {"seed": seed.hex(), "display": "Andreas"}},
            "default_identity": "andreas", "groups": {}}
    if chain is not None:
        data["ripening"] = {ident.key_text: {"segments": [s.to_dict() for s in chain.segments],
                                             "published": 0}}
    return data


def _chain(pk, t_total):
    chain = rp.Chain()
    while chain.t < t_total:
        chain.segments.append(rp.prove_segment(pk, chain.end, rp.next_segment_length(chain.t)))
    return chain


def _t(data, seed):
    key = crypto.Identity.from_seed(seed).key_text
    return rp.Chain([rp.Segment.from_dict(s) for s in data.get("ripening", {}).get(key, {}).get("segments", [])]).t


def test_the_chain_travels_with_the_key():
    seed = secrets.token_bytes(32)
    chain = _chain(crypto.Identity.from_seed(seed).public_key, rp.LEVELS[1][1])
    old = _vault_with(seed, chain)
    p = cp.build_payload(old)
    assert p["identities"]["andreas"]["ripening"]
    new = {"identities": {}, "groups": {}}
    assert cp.merge_payload(new, cp.check_payload(p)) == ["andreas"]
    assert _t(new, seed) == chain.t and rp.level(_t(new, seed)) >= 1


def test_a_key_already_here_gets_the_longer_chain_only():
    seed = secrets.token_bytes(32)
    pk = crypto.Identity.from_seed(seed).public_key
    short, long_ = _chain(pk, rp.LEVELS[0][1]), _chain(pk, rp.LEVELS[1][1])
    here = _vault_with(seed, short)
    cp.merge_payload(here, cp.build_payload(_vault_with(seed, long_)))
    assert _t(here, seed) == long_.t                      # further: taken
    cp.merge_payload(here, cp.build_payload(_vault_with(seed, short)))
    assert _t(here, seed) == long_.t                      # not further: kept ours


def test_a_chain_that_does_not_check_out_is_dropped_and_the_copy_goes_on():
    seed, other = secrets.token_bytes(32), secrets.token_bytes(32)
    wrong = _chain(crypto.Identity.from_seed(other).public_key, rp.LEVELS[0][1])
    p = cp.build_payload(_vault_with(seed))
    p["identities"]["andreas"]["ripening"] = [s.to_dict() for s in wrong.segments]
    new = {"identities": {}, "groups": {}}
    assert cp.merge_payload(new, cp.check_payload(p)) == ["andreas"]   # still copied
    assert _t(new, seed) == 0
    p["identities"]["andreas"]["ripening"] = "nonsense"
    assert cp.merge_payload({"identities": {}, "groups": {}}, cp.check_payload(p)) == ["andreas"]


def test_a_copy_without_a_chain_is_still_a_copy():
    seed = secrets.token_bytes(32)
    p = cp.build_payload(_vault_with(seed))
    assert "ripening" not in p["identities"]["andreas"]
    new = {"identities": {}, "groups": {}}
    assert cp.merge_payload(new, cp.check_payload(p)) == ["andreas"]
