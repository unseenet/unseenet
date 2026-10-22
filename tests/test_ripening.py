"""Key ripening in segments (UN-RFC 0025 as amended in #277)."""
import pytest

from unseenet.core import crypto
from unseenet.core import ripening as rp

chiavdf = pytest.importorskip("chiavdf")


def test_levels_surcharges_and_postage(real_ripening):
    assert rp.level(0) is None and rp.level(2**26 - 1) is None
    assert [rp.level(2**e) for e in (26, 29, 32, 35, 37, 40)] == [0, 1, 2, 3, 4, 4]
    assert rp.required_pow(18, 20, 0) == 26           # section 5: brand-new key, open group
    assert rp.required_pow(18, 0, 4) == 16 and rp.required_pow(0, 0, 4) == rp.FLOOR_POW
    assert rp.required_pow(18, 20, None) is None      # level "-": not accepted
    assert rp.required_pow(18, 20, None, allow_unripe=True) == 26
    assert rp.meets(None, None) and not rp.meets(None, 0) and rp.meets(3, 2)
    assert rp.parse_min("-") is None and rp.parse_min(None) == 0 and rp.parse_min("2") == 2
    with pytest.raises(rp.RipeningError):
        rp.parse_min(9)


def test_the_recommended_segments_reach_level_4_within_the_limit(real_ripening):
    t, lengths = 0, []
    while (n := rp.next_segment_length(t)):
        lengths.append(n)
        t += n
    assert t == rp.TOP and len(lengths) == 48 <= rp.MAX_SEGMENTS
    assert lengths[0] == 2**24 and max(lengths) == 2**32
    thresholds = {th for _, th, _ in rp.LEVELS}
    ends, t = set(), 0
    for n in lengths:
        t += n
        ends.add(t)
    assert thresholds <= ends                         # every level boundary is a segment end


def _small_chain(pk, *ts):
    chain = rp.Chain()
    for t in ts:
        chain.segments.append(rp.prove_segment(pk, chain.end, t))
    return chain


def test_a_chain_verifies_and_resumes_from_where_it_stopped():
    pk = crypto.Identity.generate().public_key
    chain = _small_chain(pk, 2**12, 2**13)
    assert rp.verify(pk, chain) == 2
    chain.segments.append(rp.prove_segment(pk, chain.end, 2**12))   # after a "restart"
    assert rp.verify(pk, chain, already=2) == 3                      # only the new one
    assert chain.t == 2**12 + 2**13 + 2**12
    assert list(chain.points()) == [2**12, 2**12 + 2**13, chain.t]


def test_a_chain_belongs_to_one_key():
    pk, other = (crypto.Identity.generate().public_key for _ in range(2))
    chain = _small_chain(pk, 2**12)
    with pytest.raises(rp.RipeningError):
        rp.verify(other, chain)


def test_a_tampered_segment_is_found():
    pk = crypto.Identity.generate().public_key
    chain = _small_chain(pk, 2**12, 2**12)
    bad = rp.Segment(chain.segments[1].t + 1, chain.segments[1].y, chain.segments[1].pi)
    with pytest.raises(rp.RipeningError, match="segment 2"):
        rp.verify(pk, rp.Chain([chain.segments[0], bad]))


def test_manifest_and_header_round_trip():
    pk = crypto.Identity.generate().public_key
    chain = _small_chain(pk, 2**12, 2**12)
    again = rp.Chain.from_manifest(chain.to_manifest())
    assert again == chain and again.extends(rp.Chain(chain.segments[:1]))
    assert not rp.Chain(chain.segments[:1]).extends(chain)
    t, y = rp.parse_header(chain.header())
    assert chain.points()[t] == y
    assert len("Key-Ripening: " + chain.header()) < 180
    for bad in ({"alg": "x"}, {"alg": rp.ALG, "segments": []},
                {"alg": rp.ALG, "segments": [chain.segments[0].to_dict()] * 65}):
        with pytest.raises(rp.RipeningError):
            rp.Chain.from_manifest(bad)
    with pytest.raises(rp.RipeningError):
        rp.parse_header("vdf-cg1; t=5; y=AAAA")


def test_a_segment_stops_when_its_run_file_goes(tmp_path):
    import threading
    import time
    pk = crypto.Identity.generate().public_key
    run = tmp_path / "ripening.run"
    run.touch()
    got = {}
    th = threading.Thread(target=lambda: got.update(seg=rp.prove_segment(pk, rp.GENERATOR, 2**30, run)))
    th.start()
    time.sleep(0.5)
    run.unlink()
    th.join(5)
    assert not th.is_alive() and got["seg"] is None
    run.touch()                                        # present all along: it finishes
    assert rp.prove_segment(pk, rp.GENERATOR, 2**12, run).t == 2**12


def test_self_check_proves_and_checks_a_short_segment():
    """What the portable builds' self-tests run: None when ripening works here."""
    assert rp.self_check() is None
