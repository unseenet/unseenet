"""#822, UN-RFC 0062 sections 3-4: a publisher's key list - the old keys vote the new
ones in, a fork stops updates - and releases that need a threshold of its signatures."""

import pytest

from unseenet import release_keys as rk
from unseenet import update
from unseenet.core.article import new_article
from unseenet.core.crypto import Identity
from unseenet.known_nodes import RELEASES_GROUP

SUMS = b"0" * 64 + b"  unseenet-0.9.0-server-requirements.txt\n"


@pytest.fixture
def keys():
    return [Identity.generate() for _ in range(3)]


def first(keys, threshold=2, channels=None):
    return rk.parse(rk.make_body(1, [k.key_text for k in keys], threshold, channels or {"dev": 1}))


def test_a_key_list_and_its_checks(keys):
    kl = first(keys)
    assert kl.seq == 1 and kl.threshold == 2 and kl.threshold_for("dev") == 1
    assert kl.threshold_for("stable") == 2 and len(kl.keys) == 3
    two = rk.parse(rk.make_body(2, [keys[0].key_text], 1, prev=kl))
    assert two.prev == kl.hash
    for bad in ('{"v":1,"seq":1,"keys":[],"threshold":1}',
                '{"v":1,"seq":1,"keys":["ed25519:x"],"threshold":1}',
                rk.make_body(1, [keys[0].key_text], 1).replace('"threshold":1', '"threshold":2'),
                rk.make_body(2, [keys[0].key_text], 1, prev=kl).replace('"seq":2', '"seq":1'),
                '{"v":2,"seq":1,"keys":["%s"],"threshold":1}' % keys[0].key_text):
        with pytest.raises(rk.KeyListProblem):
            rk.parse(bad)


def test_the_old_keys_vote_the_new_ones_in(keys):
    kl = first(keys)
    new = Identity.generate()
    two = rk.make_body(2, [keys[0].key_text, keys[1].key_text, new.key_text], 2, prev=kl)
    assert rk.count(kl, [(keys[0].key_text, two)]) == (kl, False)          # one of two
    assert rk.count(kl, [(new.key_text, two), (keys[0].key_text, two)]) == (kl, False)
    got, fork = rk.count(kl, [(keys[0].key_text, two), (keys[2].key_text, two)])
    assert got.seq == 2 and new.key_text in got.keys and not fork
    # and the next: by the keys of list 2, not of list 1
    three = rk.make_body(3, [new.key_text], 1, prev=rk.parse(two))
    votes = [(keys[0].key_text, two), (keys[2].key_text, two), (new.key_text, three),
             (keys[1].key_text, three)]
    assert rk.count(kl, votes)[0].seq == 3
    # a list that does not follow the one before it does not count
    stray = rk.make_body(2, [new.key_text], 1, prev=rk.parse(three))
    assert rk.count(kl, [(k.key_text, stray) for k in keys])[0].seq == 1


def test_two_lists_with_one_number_are_a_fork(keys):
    kl = first(keys)
    a = rk.make_body(2, [keys[0].key_text], 1, prev=kl)
    b = rk.make_body(2, [keys[1].key_text], 1, prev=kl)
    votes = [(keys[0].key_text, a), (keys[1].key_text, a), (keys[1].key_text, b),
             (keys[2].key_text, b)]
    assert rk.count(kl, votes) == (kl, True)


def test_nothing_pinned_is_as_before(keys, monkeypatch):
    monkeypatch.setattr(rk, "PROJECT_FIRST", None)
    assert rk.first().seq == 0 and rk.newest([]) == (rk.legacy(), False)
    body = rk.make_body(1, [keys[0].key_text], 1)
    assert rk.newest([(keys[0].key_text, body)])[0].seq == 0   # a list in the channel: not pinned


def test_a_kept_list_is_counted_on_from(keys, monkeypatch):
    kl = first(keys)
    monkeypatch.setattr(rk, "PROJECT_FIRST", kl.body)
    two = rk.make_body(2, [keys[0].key_text], 1, prev=kl)
    got, _ = rk.newest([(keys[0].key_text, two), (keys[1].key_text, two)])
    assert got.seq == 2
    assert rk.newest([], kept=got.body)[0].seq == 2               # without the votes, later
    assert rk.newest([], kept="nonsense")[0].seq == 1


def test_votes_are_checked_articles(keys):
    kl = first(keys)
    good = new_article(RELEASES_GROUP, "release-keys 1", kl.body).finalize(keys[0], 4)
    other = new_article(RELEASES_GROUP, "Unseenet 0.9.0", "x\n").finalize(keys[0], 4)
    forged = good.to_bytes().replace(b'"threshold":2', b'"threshold":1')
    votes = rk.votes_in([good.to_bytes(), other.to_bytes(), forged])
    assert votes == [rk.Vote(keys[0].key_text, kl.body)]


def test_a_release_needs_the_threshold_of_signatures(keys, monkeypatch):
    kl = first(keys)
    monkeypatch.setattr(rk, "PROJECT_FIRST", kl.body)
    one = update.add_signature(None, SUMS, keys[0])
    with pytest.raises(update.UpdateError, match="1 of the 2 signatures"):
        update.check_signature(SUMS, one, "stable")
    two = update.add_signature(one, SUMS, keys[2])
    assert update.add_signature(two, SUMS, keys[2]) == two          # once per key
    assert len(update.signature_blocks(two)) == 2
    assert update.check_signature(SUMS, two, "stable") == keys[0].key_text
    assert update.check_signature(SUMS, one, "dev") == keys[0].key_text   # dev: 1
    # the same key twice is one signature; a stranger's is none
    stranger = Identity.generate()
    with pytest.raises(update.UpdateError, match="signatures"):
        update.check_signature(SUMS, update.add_signature(one, SUMS, stranger), "stable")
    with pytest.raises(update.UpdateError, match="not trusted"):
        update.check_signature(SUMS, update.signature_text(SUMS, stranger), "stable")
    # a block changed after signing is refused
    bad = two.replace(two.split("signature: ")[2][:8], "AAAAAAAA", 1)
    with pytest.raises(update.UpdateError):
        update.check_signature(SUMS, bad, "stable")
    # a later list, given, is the one checked against
    later = rk.parse(rk.make_body(2, [stranger.key_text], 1, prev=kl))
    assert update.check_signature(SUMS, update.signature_text(SUMS, stranger), "stable",
                                  later) == stranger.key_text


def test_ci_builds_keep_their_own_key(keys, monkeypatch):
    kl = first(keys, channels={"dev": 2})
    monkeypatch.setattr(rk, "PROJECT_FIRST", kl.body)
    ci = Identity.generate()
    monkeypatch.setitem(update.TRUSTED, "dev", (*update.TRUSTED["stable"], ci.key_text))
    sig = update.signature_text(SUMS, ci)
    assert update.check_signature(SUMS, sig, "dev") == ci.key_text
    with pytest.raises(update.UpdateError):
        update.check_signature(SUMS, sig, "stable")


def test_a_single_block_as_before(monkeypatch):
    """A file with one block, as before key lists, is valid exactly when the threshold
    is 1 - the legacy list."""
    project = Identity.generate()
    monkeypatch.setattr(rk, "PROJECT_FIRST", None)
    monkeypatch.setitem(update.TRUSTED, "stable", (project.key_text,))
    assert update.check_signature(SUMS, update.signature_text(SUMS, project), "stable")


def test_servers_go_by_the_counted_list(keys, monkeypatch):
    """service_update: votes among the network's posts move the list on, it is kept,
    and a fork stops the update."""
    from unseenet import service_update as su
    kl = first(keys)
    monkeypatch.setattr(rk, "PROJECT_FIRST", kl.body)
    new = Identity.generate()
    two = rk.make_body(2, [new.key_text], 1, prev=kl)
    votes = [rk.Vote(keys[0].key_text, two), rk.Vote(keys[1].key_text, two)]
    kept: dict = {}
    with pytest.raises(su.Problem):        # no release anywhere: but the list moved on
        su.newest_release(lambda u: (_ for _ in ()).throw(su.Problem("offline")),
                          package="unseenet-gateway", network=lambda: votes, keys=kept)
    assert rk.parse(kept["body"]).seq == 2
    fork = votes + [rk.Vote(keys[1].key_text, rk.make_body(2, [keys[1].key_text], 1, prev=kl)),
                    rk.Vote(keys[2].key_text, rk.make_body(2, [keys[1].key_text], 1, prev=kl))]
    with pytest.raises(su.Problem, match="forked"):
        su.newest_release(lambda u: b"", package="unseenet-gateway", network=lambda: fork)


def test_the_project_key_list_is_pinned(monkeypatch):
    """The first list as made and posted on 3 Nov 2026: the project key and two reserve
    keys, two of three for stable releases, one for development builds."""
    from unseenet.known_nodes import PROJECT_KEY
    monkeypatch.undo()                     # the list as shipped, not the tests' patch
    assert rk.PROJECT_FIRST
    kl = rk.first()
    assert kl.seq == 1 and kl.threshold == 2 and kl.threshold_for("dev") == 1
    assert kl.keys[0] == PROJECT_KEY and len(kl.keys) == 3
    assert kl.body == rk.make_body(1, list(kl.keys), 2, {"dev": 1})


def test_votes_inside_the_body_count_whoever_posts_them(keys):
    """Section 3.1: a vote is a signature on the list, carried in the body; who posted
    the article does not matter, and a forged or misplaced signature is no vote."""
    kl = first(keys)
    new = Identity.generate()
    two = rk.make_body(2, [keys[0].key_text, new.key_text], 1, prev=kl)
    text = rk.add_vote(two, keys[0])
    assert rk.add_vote(text, keys[0]) == text                      # once per key
    text = rk.add_vote(text, keys[1])
    carrier = Identity.generate().key_text                         # not a signer at all
    votes = rk.votes_from(carrier, "release-keys 2", text)
    assert {v.author for v in votes} == {keys[0].key_text, keys[1].key_text}
    assert rk.count(kl, votes)[0].seq == 2
    # a signature from one list does not vote for another
    other = rk.make_body(2, [new.key_text], 1, prev=kl)
    moved = rk.signed_text(other, rk.split_signed(text)[1])
    assert rk.votes_from(carrier, "release-keys 2", moved) == []
    # a release signature is not a vote (its own purpose, UN-RFC 0062 section 9)
    rel = update.signature_blocks(update.signature_text(rk._signed(two), keys[0]))
    assert rk.votes_from(carrier, "release-keys 2", rk.signed_text(two, rel)) == []
    # a bare list still counts as its author's vote, and only its author's
    assert rk.votes_from(keys[2].key_text, "release-keys 2", two) == [
        rk.Vote(keys[2].key_text, rk.parse(two).body)]
    assert rk.votes_from(keys[2].key_text, "something else", text) == []


def test_the_chain_carries_every_later_list(keys, monkeypatch):
    """Section 3.2: the chain post holds every list from seq 2 with its votes, anybody
    can post it, and a client counts on from the pinned list with it alone."""
    kl = first(keys)
    monkeypatch.setattr(rk, "PROJECT_FIRST", kl.body)
    new = Identity.generate()
    two = rk.parse(rk.make_body(2, [keys[0].key_text, new.key_text], 1, prev=kl))
    three = rk.parse(rk.make_body(3, [new.key_text], 1, prev=two))
    votes = (rk.votes_from(None, "release-keys chain", "")
             + rk.votes_from("x", "release-keys 2", rk.add_vote(rk.add_vote(two.body, keys[0]),
                                                                 keys[2]))
             + rk.votes_from("x", "release-keys 3", rk.add_vote(three.body, new)))
    assert rk.chain_text([]) == ""
    chain = rk.chain_text(votes)
    assert chain.count("\n--\n") == 1
    got = rk.votes_from(Identity.generate().key_text, rk.CHAIN_SUBJECT, chain)
    assert rk.newest(got)[0] == three
    # and shipped with the client, it counts without the channel
    monkeypatch.setattr(rk, "PROJECT_CHAIN", chain)
    assert rk.newest([])[0] == three
    # not for another publisher, whose chain is its own
    assert rk.newest([], start=kl)[0] == kl
    # a list that did not count is left out
    stray = rk.make_body(4, [keys[1].key_text], 1, prev=three)
    assert rk.chain_text(votes + rk.votes_from("x", "release-keys 4",
                                                rk.add_vote(stray, keys[1]))) == chain
