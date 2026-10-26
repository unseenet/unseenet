"""#543: a node whose policy changed forgets the refusals the old one made, reconciles
and pulls again, and fetches the files of stored articles it now carries."""
import os
import time

from unseenet.core import blobs as bl
from unseenet.core import crypto
from unseenet.core.article import new_article
from unseenet.core.groups import Manifest, canonical_json, make_manifest
from unseenet.core.store import Store
from unseenet.node.blobfetch import BlobFollower
from unseenet.node.pulling import Puller
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8
PNG = b"\x89PNG\r\n\x1a\n" + os.urandom(3000)
ON = {"max_size": 1048576, "groups": "*"}


def make_node(name, **kw) -> Node:
    return Node(Store(), NodeConfig(name=name, min_pow=BITS, forward_delay=(0, 0), **kw))


async def serve(node):
    server = await node.serve("127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def test_first_run_notes_it_and_the_same_policy_changes_nothing():
    n = make_node("n")
    assert n.store.policy_seen() is None
    assert n.policy_changed() is None and n.store.policy_seen() == n.policy_fingerprint()
    n.store.refuse("<a@x>", "p", "group")
    assert n.policy_changed() is None and n.store.refused_from("<a@x>", "p")
    n.config.pull_interval = 5              # not part of what is taken: still the same
    n.config.min_pow = BITS + 2
    assert n.policy_changed() is None


def test_a_change_forgets_policy_refusals_only():
    n = make_node("n", peers=[PeerConfig(name="p", address="unused:1")])
    n.policy_changed()
    n.store.refuse("<a@x>", "p", "group")          # e.g. "this node carries no sites"
    n.store.refuse("<b@x>", "p", "permission")     # the article itself: stays refused
    n.store.set_pulled("p", int(time.time()))
    n.store.set_reconciled("p", time.time() + 86400)
    n.config.sites = "accept"
    done = n.policy_changed()
    assert done == {"refusals_forgotten": 1, "blob_articles": 0}
    assert not n.store.refused_from("<a@x>", "p") and n.store.refused_from("<b@x>", "p")
    assert n.store.pulled_since("p") is None and n.store.reconcile_due("p")
    assert n.policy_changed() is None              # noted: the next start is quiet


def test_what_counts_as_a_change():
    n = make_node("n", peers=[PeerConfig(name="p", address="unused:1")])
    base = n.policy_fingerprint()
    for change in (lambda c: setattr(c, "avatars", "accept"),
                   lambda c: setattr(c, "profiles", "refuse"),
                   lambda c: setattr(c, "new_groups", "manual"),
                   lambda c: setattr(c, "excludes", "alt.*"),
                   lambda c: setattr(c, "trusted_owners", ["ed25519:x"]),
                   lambda c: setattr(c, "blobs", dict(ON)),
                   lambda c: setattr(c.peers[0], "accept", "dk.*")):
        m = make_node("n", peers=[PeerConfig(name="p", address="unused:1")])
        change(m.config)
        assert m.policy_fingerprint() != base
    n.config.blobs = dict(ON)
    on = n.policy_fingerprint()
    n.config.blobs = ON | {"encrypted": True}
    assert n.policy_fingerprint() != on


async def test_new_groups_accepted_later_are_pulled_after_all():
    a = make_node("a")
    owner = crypto.Identity.generate()
    m = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    a.accept(m.to_bytes())
    post = new_article(m.group, "Hej", "hej\n", from_name="A").finalize(owner, BITS)
    a.accept(post.to_bytes())
    server, addr = await serve(a)
    b = make_node("b", new_groups="manual", peers=[PeerConfig(name="a", address=addr)])
    b.policy_changed()
    res = await Puller(b, b.config.peers[0]).run_once()
    assert res["accepted"] == 0 and res["rejected"]["group"] >= 1
    assert b.store.refused_from(m.message_id, "a")                       # #132: not again

    b.config.new_groups = "accept"                 # the operator changes node.toml, restarts
    assert b.policy_changed()["refusals_forgotten"] >= 1
    await Puller(b, b.config.peers[0]).run_once()
    assert b.store.manifest(m.group) is not None and b.store.get(post.message_id) is not None
    server.close()


def _manifest(owner):
    mf = make_manifest(owner, "dk.billeder", "open", pow_bits=BITS)
    data = Manifest.from_article(mf).raw | {"attachments": {"max_size": 1048576}}
    return new_article(mf.group, None, canonical_json(data),
                       extra=[("Control", "manifest"), ("Content-Type", "application/json")]
                       ).finalize(owner, BITS)


def _post(owner, gid):
    bid = bl.blob_id(PNG)
    hdrs = [("Blobs", f"{bid}={len(PNG)}"),
            ("Attachment-1", f"{bid}; type=image/png; size={len(PNG)}")]
    art = new_article(gid, "Et billede", "Se her\n", from_name="X", extra=hdrs)
    return art.finalize(owner, BITS + bl.extra_bits(art))


async def test_turning_blobs_on_fetches_the_files_of_stored_articles():
    a = make_node("a", blobs=dict(ON))
    owner = crypto.Identity.generate()
    m = _manifest(owner)
    post = _post(owner, m.group)
    bid = bl.blob_id(PNG)
    a.accept(m.to_bytes())
    a.accept(post.to_bytes(), staged={bid: (PNG, time.monotonic())})
    server, addr = await serve(a)
    b = make_node("b", peers=[PeerConfig(name="a", address=addr)])     # no blobs yet
    b.policy_changed()
    await Puller(b, b.config.peers[0]).run_once()
    assert b.store.get(post.message_id) is not None and not b.blobs.has(bid)
    assert b.blob_wait == {}

    b.config.blobs = dict(ON)
    assert b.policy_changed()["blob_articles"] == 1
    assert b.blob_wait[post.message_id]["source"] is None
    assert await BlobFollower(b, tick=0).run_once() == 1
    assert b.blobs.has(bid) and b.blob_wait == {}
    assert b.backfill_blobs() == 0                 # nothing left to fetch
    server.close()


def test_backfill_only_what_is_carried_and_at_most_the_limit():
    n = make_node("n")                             # no blobs: the article comes without its file
    owner = crypto.Identity.generate()
    m = _manifest(owner)
    n.accept(m.to_bytes())
    post = _post(owner, m.group)
    n.accept(post.to_bytes(), source="p", from_peer=True)
    assert n.store.get(post.message_id) is not None and n.backfill_blobs() == 0
    n.config.blobs = ON | {"groups": "alt.*"}      # its group is not carried
    assert n.backfill_blobs() == 0
    n.config.blobs = ON | {"groups": "dk.*", "max_size": 100}    # its file is too big
    assert n.backfill_blobs() == 0
    n.config.blobs = ON | {"groups": "dk.*"}
    assert n.backfill_blobs(limit=0) == 0
    n.store.refuse_blob(bl.blob_id(PNG), "not here")
    assert n.backfill_blobs() == 0                 # refused by the operator (7.3)
