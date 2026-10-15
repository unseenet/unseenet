"""Peer authentication with node keys (UN-RFC 0016)."""

import asyncio

import pytest

from unseenet.core import crypto
from unseenet.core.article import new_article
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.nntp import Client
from unseenet.node.peering import Feeder, PeerAuthError, authenticate_with_key
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8


def make_node(name, **kw) -> Node:
    return Node(Store(), NodeConfig(name=name, min_pow=BITS, forward_delay=(0, 0), **kw))


async def serve(node):
    server = await node.serve("127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def posts():
    owner = crypto.Identity.generate()
    manifest = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    art = new_article(manifest.group, "Hej", "Med nøgler\n", from_name="A").finalize(owner, BITS)
    return manifest, art


async def pair(b_lists_a_as=None, a_expects_b_as=None):
    """Node A feeds node B, which only takes posts from configured peers."""
    a_key, b_key = crypto.Identity.generate(), crypto.Identity.generate()
    b = Node(Store(), NodeConfig(name="b", min_pow=BITS, forward_delay=(0, 0), require_peer_auth=True,
                                 peers=[PeerConfig(name="alice-node", address="unused:1",
                                                   key=(b_lists_a_as or a_key).key_text)]), key=b_key)
    server_b, addr_b = await serve(b)
    a = Node(Store(), NodeConfig(name="a", min_pow=BITS, forward_delay=(0, 0),
                                 peers=[PeerConfig(name="bob-node", address=addr_b,
                                                   key=(a_expects_b_as or b_key).key_text)]), key=a_key)
    manifest, art = posts()
    a.accept(manifest.to_bytes())
    a.accept(art.to_bytes())
    return a, b, server_b, addr_b, art


async def test_feed_authenticated_by_key():
    a, b, server_b, _, art = await pair()
    assert await Feeder(a, a.config.peers[0]).run_once() == 2
    assert b.store.get(art.message_id) == a.store.get(art.message_id)
    server_b.close()


async def test_unknown_key_is_refused():
    a, b, server_b, _, art = await pair(b_lists_a_as=crypto.Identity.generate())
    with pytest.raises(PeerAuthError, match="did not accept"):
        await Feeder(a, a.config.peers[0]).run_once()
    assert b.store.get(art.message_id) is None
    server_b.close()


async def test_wrong_node_answering_is_refused():
    """A node that answers with another key than configured is not fed."""
    a, b, server_b, _, art = await pair(a_expects_b_as=crypto.Identity.generate())
    with pytest.raises(PeerAuthError, match="answered with key"):
        await Feeder(a, a.config.peers[0]).run_once()
    assert b.store.get(art.message_id) is None
    server_b.close()


async def test_unauthenticated_push_is_refused():
    _, b, server_b, addr_b, art = await pair()
    client = await Client.connect(addr_b)
    code, _ = await client.command("CHECK " + art.message_id)
    assert code == 480
    await client.quit()
    server_b.close()


async def test_proof_cannot_be_relayed_to_another_node():
    """A signature made for one node's challenge is worthless at another node."""
    a_key = crypto.Identity.generate()
    b = make_node("b", require_peer_auth=True,
                  peers=[PeerConfig(name="a", address="unused:1", key=a_key.key_text)])
    m = make_node("m", peers=[PeerConfig(name="a", address="unused:1", key=a_key.key_text)])
    (server_b, addr_b), (server_m, addr_m) = await serve(b), await serve(m)

    # the middleman M gets a challenge from B ...
    to_b = await Client.connect(addr_b)
    await to_b.fetch_capabilities()
    _, text = await to_b.command(f"XUN-PEER {a_key.key_text}", (383,))
    b_key_text, nonce_text = text.split()
    nonce = crypto.b64decode(nonce_text)
    # ... and A, believing it talks to M, signs it - bound to M's key, not B's
    sig = a_key.sign_text(crypto.PURPOSE_PEER_AUTH, nonce + m.key.public_key + a_key.public_key)
    code, _ = await to_b.command(f"XUN-PEER-PROOF {sig}")
    assert code == 481
    await to_b.quit()

    # while A talking to M for real works
    to_m = await Client.connect(addr_m)
    await to_m.fetch_capabilities()
    await authenticate_with_key(to_m, a_key, m.key.public_key)
    await to_m.quit()
    server_b.close()
    server_m.close()


async def test_repeated_failures_close_the_connection():
    b = make_node("b", require_peer_auth=True)
    server_b, addr_b = await serve(b)
    client = await Client.connect(addr_b)
    stranger = crypto.Identity.generate()
    for _ in range(3):
        await client.command(f"XUN-PEER {stranger.key_text}", (383,))
        code, _ = await client.command("XUN-PEER-PROOF ed25519:" + "A" * 86)
        assert code == 481
    with pytest.raises((ConnectionError, asyncio.IncompleteReadError, ValueError)):
        await client.command("DATE")
    server_b.close()


def test_node_key_is_kept_sealed(tmp_path, monkeypatch):
    from unseenet.cli import load_node_key
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    first = load_node_key(tmp_path, "pw")
    assert load_node_key(tmp_path, "pw").key_text == first.key_text
    assert first.seed not in (tmp_path / "node_key.vault").read_bytes()
