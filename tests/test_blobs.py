"""#370: blobs, part 1 (UN-RFC 0027): IDs, headers, policy, BLOBPOST and BLOB."""
import asyncio
import os

import pytest

from unseenet.core import blobs as bl
from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.encoding import DS, H, b32
from unseenet.core.groups import Manifest, canonical_json, make_manifest
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig

BITS = 8
PNG = b"\x89PNG\r\n\x1a\n" + os.urandom(3000)


def _manifest(owner, attachments=None, gtype="open"):
    m = make_manifest(owner, "dk.billeder", gtype, pow_bits=BITS)
    if attachments is None:
        return m
    data = Manifest.from_article(m).raw | {"attachments": attachments}
    art = new_article(m.group, None, canonical_json(data),
                      extra=[("Control", "manifest"), ("Content-Type", "application/json")])
    return art.finalize(owner, BITS)


def _with_blobs(owner, gid, files, *, types=None, extra=(), bits=None):
    hdrs = [("Blobs", " ".join(f"{bl.blob_id(f)}={len(f)}" for f in files))]
    for i, f in enumerate(files, 1):
        hdrs.append((f"Attachment-{i}", f"{bl.blob_id(f)}; type={(types or {}).get(i, 'image/png')}; "
                                        f"size={len(f)}"))
    art = new_article(gid, "Et billede", "Se her\n", from_name="X", extra=hdrs + list(extra))
    return art.finalize(owner, BITS + bl.extra_bits(art) if bits is None else bits)


def test_blob_ids():
    bid = bl.blob_id(b"hej")
    assert bid == "blob1:" + b32(H(DS("UNSEENET-BLOB-1") + b"hej")) and len(bid) == 58
    assert bl.valid_id(bid) and not bl.valid_id("blob2:" + bid[6:]) and not bl.valid_id(bid[:-1])


def test_the_blobs_header():
    owner = crypto.Identity.generate()
    a, b = bl.blob_id(b"a"), bl.blob_id(b"b")
    art = new_article("dk.x@abcdabcdabcdabcd", "s", "b\n", from_name="X",
                      extra=[("Blobs", f"{a}=10 {b}=20")])
    assert bl.parse_blobs(art) == [(a, 10), (b, 20)]
    for value in (f"{a}=10 {a}=20", f"{a}=0", f"{a}={bl.MAX_BLOB + 1}", "blob1:x=10",
                  " ".join(f"{bl.blob_id(bytes([i]))}=1" for i in range(5)),
                  " ".join(f"{bl.blob_id(bytes([i]))}={bl.MAX_BLOB}" for i in range(3))):
        bad = new_article("dk.x@abcdabcdabcdabcd", "s", "b\n", from_name="X", extra=[("Blobs", value)])
        with pytest.raises(ArticleError):
            bl.parse_blobs(bad)
    assert owner


def test_postage_extra():
    def total(n):
        return new_article("dk.x@abcdabcdabcdabcd", "s", "b\n", from_name="X",
                           extra=[("Blobs", f"{bl.blob_id(b'x')}={n}")])
    assert [bl.extra_bits(total(n)) for n in (65536, 200 * 1024, 1024 * 1024, 4 * 1024 * 1024)] == [0, 2, 4, 6]


def test_the_attachments_field():
    owner = crypto.Identity.generate()
    assert Manifest.from_article(_manifest(owner, {"max_size": 1048576, "types": ["image/*"]}))
    for att in ({"max_size": 0}, {"max_size": bl.MAX_BLOB + 1}, {"types": ["image/*"]},
                {"max_size": 1000, "types": "image/*"}, []):
        with pytest.raises(ArticleError, match="attachments"):
            Manifest.from_article(_manifest(owner, att))


def test_what_every_node_checks():
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))     # carries no blobs
    owner = crypto.Identity.generate()
    plain = _manifest(owner)
    node.accept(plain.to_bytes())
    with pytest.raises(ArticleError, match="no attachments"):
        node.accept(_with_blobs(owner, plain.group, [PNG]).to_bytes())
    node.accept(_serial2(owner, {"max_size": 2000, "types": ["image/*"]}).to_bytes())
    with pytest.raises(ArticleError, match="larger"):
        node.accept(_with_blobs(owner, plain.group, [PNG]).to_bytes())
    small = PNG[:1500]
    with pytest.raises(ArticleError, match="type"):
        node.accept(_with_blobs(owner, plain.group, [small], types={1: "application/pdf"}).to_bytes())
    with pytest.raises(ArticleError, match="postage"):
        node.accept(_with_blobs(owner, plain.group, [small], bits=BITS - 1).to_bytes())
    lone = new_article(plain.group, "s", "b\n", from_name="X",
                       extra=[("Attachment-1", f"{bl.blob_id(small)}; type=image/png; size=1500")])
    with pytest.raises(ArticleError, match="without Blobs"):
        node.accept(lone.finalize(owner, BITS).to_bytes())
    # a node that carries no blobs passes the article on without its files
    node.accept(_with_blobs(owner, plain.group, [small]).to_bytes())


def _serial2(owner, attachments):
    m = make_manifest(owner, "dk.billeder", "open", serial=2, pow_bits=BITS)
    data = Manifest.from_article(m).raw | {"attachments": attachments}
    art = new_article(m.group, None, canonical_json(data),
                      extra=[("Control", "manifest"), ("Content-Type", "application/json")])
    return art.finalize(owner, BITS)


class Client:
    def __init__(self, reader, writer):
        self.r, self.w = reader, writer

    async def line(self) -> str:
        return (await self.r.readline()).decode().rstrip("\r\n")

    async def cmd(self, text: str) -> str:
        self.w.write(text.encode() + b"\r\n")
        await self.w.drain()
        return await self.line()

    async def post(self, art) -> str:
        assert (await self.cmd("POST")).startswith("340")
        body = art.to_bytes().replace(b"\r\n.", b"\r\n..")
        self.w.write(body + (b"" if body.endswith(b"\r\n") else b"\r\n") + b".\r\n")
        await self.w.drain()
        return await self.line()


async def _connect(node):
    server = await node.serve("127.0.0.1", 0)
    r, w = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
    c = Client(r, w)
    await c.line()                               # greeting
    return server, c


async def test_a_node_without_blobs_says_so():
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    server, c = await _connect(node)
    assert (await c.cmd("CAPABILITIES")).startswith("101")
    caps = []
    while (line := await c.line()) != ".":
        caps.append(line)
    assert not any(x.startswith("UNSEENET-BLOB") for x in caps)
    bid = bl.blob_id(PNG)
    assert await c.cmd(f"BLOBPOST {bid} {len(PNG)}") == "445 unsupported"
    assert await c.cmd(f"BLOB {bid}") == "430 no such blob"
    server.close()


async def test_upload_post_and_fetch():
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0),
                                    blobs={"max_size": 1048576, "groups": "dk.*"}))
    owner = crypto.Identity.generate()
    node.accept(_manifest(owner, {"max_size": 1048576}).to_bytes())
    gid = _manifest(owner).group
    server, c = await _connect(node)
    assert (await c.cmd("CAPABILITIES")).startswith("101")
    caps = []
    while (line := await c.line()) != ".":
        caps.append(line)
    assert "UNSEENET-BLOB 1048576" in caps
    bid = bl.blob_id(PNG)
    # posting before the blob is there
    assert (await c.post(_with_blobs(owner, gid, [PNG]))).startswith("441 blobs")
    # a wrong blob is refused after the transfer, one too large before it
    assert await c.cmd(f"BLOBPOST {bl.blob_id(b'other')} {len(PNG)}") == "345 send blob"
    c.w.write(PNG)
    assert await c.line() == "445 hash"
    assert await c.cmd(f"BLOBPOST {bid} {bl.MAX_BLOB}") == "445 size"
    # upload, post, fetch
    assert await c.cmd(f"BLOBPOST {bid} {len(PNG)}") == "345 send blob"
    c.w.write(PNG)
    assert await c.line() == "245 blob staged"
    assert (await c.post(_with_blobs(owner, gid, [PNG]))).startswith("240")
    assert node.blobs.has(bid) and not c.w.transport.is_closing()
    assert await c.cmd(f"BLOB {bid}") == f"226 {len(PNG)} {bid}"
    assert await c.r.readexactly(len(PNG)) == PNG
    assert await c.cmd(f"BLOBPOST {bid} {len(PNG)}") == "245 blob staged"   # already stored: no transfer
    assert await c.cmd(f"BLOB {bl.blob_id(b'never')}") == "430 no such blob"
    assert await c.cmd("DATE")                    # the connection goes on after raw octets
    server.close()


async def test_staged_blobs_belong_to_their_connection():
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), blobs={"max_size": 1048576}))
    owner = crypto.Identity.generate()
    node.accept(_manifest(owner, {"max_size": 1048576}).to_bytes())
    gid = _manifest(owner).group
    server, one = await _connect(node)
    _, two = await _connect(node)
    bid = bl.blob_id(PNG)
    assert await one.cmd(f"BLOBPOST {bid} {len(PNG)}") == "345 send blob"
    one.w.write(PNG)
    assert await one.line() == "245 blob staged"
    assert (await two.post(_with_blobs(owner, gid, [PNG]))).startswith("441 blobs")
    assert not node.blobs.has(bid)                # staged is not stored
    server.close()


def test_a_blob_store_on_disk(tmp_path):
    store = bl.BlobStore(tmp_path / "blobs")
    bid = bl.blob_id(PNG)
    store.put(bid, PNG)
    assert store.has(bid) and store.get(bid) == PNG
    with pytest.raises(ValueError):
        store.put(bl.blob_id(b"x"), PNG)
    store.delete(bid)
    assert not store.has(bid) and store.get(bid) is None
