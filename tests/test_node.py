"""Node tests: acceptance pipeline and two nodes peering over local TCP (no Tor)."""

import asyncio

import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.nntp import Client
from unseenet.node.peering import Feeder
from unseenet.node.server import Node, NodeConfig, PeerConfig, wildmat

BITS = 8


def make_node(**kw) -> Node:
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), **kw))


def test_wildmat():
    assert wildmat("dk.*,!dk.test*", "dk.snak@x")
    assert not wildmat("dk.*,!dk.test*", "dk.test@x")


def test_accept_pipeline():
    node = make_node()
    owner, user = crypto.Identity.generate(), crypto.Identity.generate()
    manifest = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    gid = manifest.group

    # unknown group
    art = new_article(gid, "før", "x", from_name="u").finalize(user, BITS)
    with pytest.raises(ArticleError) as e:
        node.accept(art.to_bytes())
    assert e.value.reason == "group"

    node.accept(manifest.to_bytes())
    node.accept(art.to_bytes())
    with pytest.raises(ArticleError) as e:
        node.accept(art.to_bytes())
    assert e.value.reason == "duplicate"

    cheap = new_article(gid, "billig", "x", from_name="u").finalize(user, 0)
    if cheap.proven_pow() < BITS:
        with pytest.raises(ArticleError) as e:
            node.accept(cheap.to_bytes())
        assert e.value.reason == "postage"


def test_cancel_only_by_author_or_owner():
    node = make_node()
    owner, user, other = (crypto.Identity.generate() for _ in range(3))
    manifest = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    node.accept(manifest.to_bytes())
    art = new_article(manifest.group, "hej", "x", from_name="u").finalize(user, BITS)
    node.accept(art.to_bytes())

    bad = new_article(manifest.group, None, "", extra=[("Control", f"cancel {art.message_id}")])
    with pytest.raises(ArticleError):
        node.accept(bad.finalize(other, BITS).to_bytes())
    good = new_article(manifest.group, None, "", extra=[("Control", f"cancel {art.message_id}")])
    node.accept(good.finalize(user, BITS).to_bytes())
    assert node.store.get(art.message_id) is None


def test_control_articles_cannot_be_cancelled():
    """UN-RFC 0004 section 7.1: not a manifest, and not a cancel."""
    node = make_node()
    owner, user = crypto.Identity.generate(), crypto.Identity.generate()
    manifest = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    node.accept(manifest.to_bytes())
    art = new_article(manifest.group, "hej", "x", from_name="u").finalize(user, BITS)
    node.accept(art.to_bytes())
    cancel = new_article(manifest.group, None, "", extra=[("Control", f"cancel {art.message_id}")])
    cancel = cancel.finalize(user, BITS)
    node.accept(cancel.to_bytes())
    for target in (manifest.message_id, cancel.message_id):
        again = new_article(manifest.group, None, "", extra=[("Control", f"cancel {target}")])
        with pytest.raises(ArticleError) as e:
            node.accept(again.finalize(owner, BITS).to_bytes())
        assert e.value.reason == "permission"
    assert node.store.get(manifest.message_id) is not None


async def test_two_nodes_replicate_over_onntp():
    b = make_node(name="b")
    server_b = await b.serve("127.0.0.1", 0)
    port_b = server_b.sockets[0].getsockname()[1]

    a = make_node(name="a", peers=[PeerConfig(name="b", address=f"127.0.0.1:{port_b}")])
    server_a = await a.serve("127.0.0.1", 0)
    port_a = server_a.sockets[0].getsockname()[1]

    owner = crypto.Identity.generate()
    manifest = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    art = new_article(manifest.group, "Hej fra A", "Replikeret!\n",
                      from_name="Andreas").finalize(owner, BITS)

    # A client posts to node A over ONNTP
    client = await Client.connect(f"127.0.0.1:{port_a}")
    caps = await client.fetch_capabilities()
    assert "UNSEENET 1" in caps
    assert (await client.post(manifest.to_bytes()))[0] == 240
    assert (await client.post(art.to_bytes()))[0] == 240
    assert (await client.post(art.to_bytes()))[1].startswith("duplicate")
    await client.quit()

    # A feeds B
    handled = await Feeder(a, a.config.peers[0]).run_once()
    assert handled == 2
    assert b.store.get(art.message_id) == a.store.get(art.message_id)

    # A reader on B sees it, with synthesized Path for newsreaders
    reader = await Client.connect(f"127.0.0.1:{port_b}")
    count, low, high = await reader.group(manifest.group)
    assert count == 2
    raw = await reader.article(art.message_id)
    assert b"Replikeret!" in raw and b"Path: not-for-mail" in raw
    await reader.quit()

    server_a.close()
    server_b.close()
    await asyncio.gather(server_a.wait_closed(), server_b.wait_closed())
