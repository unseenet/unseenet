"""#148 step 3b: blobs follow their article between peers (UN-RFC 0027 section 6.3)."""
import asyncio
import os
import time

from unseenet.core import blobs as bl
from unseenet.core import crypto
from unseenet.core.article import new_article
from unseenet.core.groups import Manifest, canonical_json, make_manifest
from unseenet.core.store import Store
from unseenet.node.blobfetch import BlobFollower
from unseenet.node.peering import Feeder
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8
PNG = b"\x89PNG\r\n\x1a\n" + os.urandom(5000)
ON = {"max_size": 1048576, "groups": "*"}


def _manifest(owner):
    m = make_manifest(owner, "dk.billeder", "open", pow_bits=BITS)
    data = Manifest.from_article(m).raw | {"attachments": {"max_size": 1048576}}
    return new_article(m.group, None, canonical_json(data),
                       extra=[("Control", "manifest"), ("Content-Type", "application/json")]
                       ).finalize(owner, BITS)


def _post(owner, gid, files):
    hdrs = [("Blobs", " ".join(f"{bl.blob_id(f)}={len(f)}" for f in files))]
    hdrs += [(f"Attachment-{i}", f"{bl.blob_id(f)}; type=image/png; size={len(f)}")
             for i, f in enumerate(files, 1)]
    art = new_article(gid, "Et billede", "Se her\n", from_name="X", extra=hdrs)
    return art.finalize(owner, BITS + bl.extra_bits(art))


async def _chain(a_blobs=ON):
    """A -> B -> C, each pushing to the next with node keys (UN-RFC 0016)."""
    keys = {n: crypto.Identity.generate() for n in "abc"}
    nodes, servers, addrs = {}, {}, {}
    for n in "abc":
        nodes[n] = Node(Store(), NodeConfig(name=n, min_pow=BITS, forward_delay=(0, 0),
                                            blobs=a_blobs if n == "a" else ON), key=keys[n])
        servers[n] = await nodes[n].serve("127.0.0.1", 0)
        addrs[n] = f"127.0.0.1:{servers[n].sockets[0].getsockname()[1]}"

    def peer(n):
        return PeerConfig(name=n, address=addrs[n], key=keys[n].key_text)
    nodes["a"].config.peers = [peer("b")]
    nodes["b"].config.peers = [peer("a"), peer("c")]
    nodes["c"].config.peers = [peer("b")]
    for n in "abc":
        nodes[n].config.require_peer_auth = True
    return nodes, servers


async def test_a_blob_follows_its_article_and_holds_it_back_until_then():
    nodes, servers = await _chain()
    a, b, c = nodes["a"], nodes["b"], nodes["c"]
    owner = crypto.Identity.generate()
    m = _manifest(owner)
    for node in nodes.values():
        node.accept(m.to_bytes())
    post = _post(owner, m.group, [PNG])
    bid = bl.blob_id(PNG)
    a.accept(post.to_bytes(), staged={bid: (PNG, time.monotonic())})      # a client posted it on A
    assert a.blobs.has(bid)

    assert await Feeder(a, a.config.peers[0]).run_once() == 1
    assert b.store.get(post.message_id) and not b.blobs.has(bid)
    assert post.message_id in b.blob_wait
    assert post.message_id not in b.store.due("c")     # held back while the blob is fetched

    assert await BlobFollower(b, tick=0).run_once() == 1
    assert b.blobs.has(bid) and b.blob_wait == {}
    assert post.message_id in b.store.due("c")         # now on its way, with the usual delay

    assert await Feeder(b, b.config.peers[1]).run_once() == 1
    assert c.store.get(post.message_id)
    assert await BlobFollower(c, tick=0).run_once() == 1 and c.blobs.has(bid)   # from B
    for s in servers.values():
        s.close()


async def test_without_the_blob_the_article_goes_on_after_the_wait():
    nodes, servers = await _chain(a_blobs=None)          # A carries no blobs
    a, b = nodes["a"], nodes["b"]
    owner = crypto.Identity.generate()
    m = _manifest(owner)
    for node in nodes.values():
        node.accept(m.to_bytes())
    post = _post(owner, m.group, [PNG])
    a.accept(post.to_bytes())                            # passed on without its file
    assert await Feeder(a, a.config.peers[0]).run_once() == 1
    follower = BlobFollower(b, tick=0)
    assert await follower.run_once() == 0                # nobody has it
    assert post.message_id in b.blob_wait and post.message_id not in b.store.due("c")
    b.blob_wait[post.message_id]["until"] = time.time() - 1
    await follower.run_once()
    assert b.blob_wait == {} and post.message_id in b.store.due("c")
    assert not b.blobs.has(bl.blob_id(PNG))
    for s in servers.values():
        s.close()


async def test_a_reader_is_told_to_try_later_while_it_is_fetched():
    nodes, servers = await _chain(a_blobs=None)
    a, b = nodes["a"], nodes["b"]
    owner = crypto.Identity.generate()
    m = _manifest(owner)
    for node in nodes.values():
        node.accept(m.to_bytes())
    a.accept(_post(owner, m.group, [PNG]).to_bytes())
    await Feeder(a, a.config.peers[0]).run_once()
    port = servers["b"].sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", port)
    await r.readline()
    w.write(f"BLOB {bl.blob_id(PNG)}\r\n".encode())
    await w.drain()
    assert (await r.readline()).decode().strip() == "436 try later"
    w.write(f"BLOB {bl.blob_id(b'other')}\r\n".encode())
    await w.drain()
    assert (await r.readline()).decode().strip() == "430 no such blob"
    w.close()
    for s in servers.values():
        s.close()
