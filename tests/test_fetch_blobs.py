"""#442: files on posts you read (UN-RFC 0027 sections 6.4, 9.2): BLOB for readers,
checking a blob, alternative text, and pictures decoded in a separate process."""
import io
import struct
import zlib

import pytest
from PIL import Image

import unseenet.client.session as sess
from unseenet.client import decode, media
from unseenet.client.session import Session, SessionError
from unseenet.core import blobs as bl
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig


def png(w=40, h=30, colour=(200, 30, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(out, "PNG")
    return out.getvalue()


def gif(frames=3) -> bytes:
    out = io.BytesIO()
    imgs = [Image.new("RGB", (10, 10), (i * 60, 0, 0)) for i in range(frames)]
    imgs[0].save(out, "GIF", save_all=True, append_images=imgs[1:], duration=50, loop=0)
    return out.getvalue()


@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    made, servers = [], []

    async def node(**blobs):
        n = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), blobs=blobs or None))
        server = await n.serve("127.0.0.1", 0)
        servers.append(server)
        return f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name, addr):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", ops=1, mem=8192 * 1024),
                    status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        made.append(s)
        return s
    yield node, session
    for s in made:
        await s.close()
    for server in servers:
        server.close()


async def _group_with_a_picture(me, octets, alt="En rød firkant"):
    gid = await me.create_group("dk.billeder", "open", min_pow=10,
                                extra={"attachments": {"max_size": 1048576}})
    f = media.prepare("foto.png", octets)
    f = media.Prepared(f.name, f.media_type, f.octets, f.note, alt, f.dim)
    await me.post(gid, "Se her", "Et billede\n", files=[f])
    return gid, f


async def test_a_picture_with_its_alt_text_and_size(net):
    node, session = net
    addr = await node(max_size=1048576)
    me, reader = session("me", addr), session("reader", addr)
    gid, sent = await _group_with_a_picture(me, png())
    reader.subscribe(gid)
    [msg] = reader.visible(await reader.fetch_group(gid))
    [att] = msg.attachments
    assert att == {"blob": bl.blob_id(sent.octets), "type": "image/png", "size": len(sent.octets),
                   "name": "foto.png", "alt": "En rød firkant", "dim": [40, 30]}
    assert msg.to_dict()["attachments"] == [att]
    assert await reader.node_files(gid) is True
    assert reader.node_files_known(gid) is True
    assert await reader.fetch_blob(gid, att["blob"]) == sent.octets
    pic = await reader.picture(gid, att["blob"])
    assert (pic.media_type, pic.width, pic.height, pic.frames) == ("image/png", 40, 30, 1)
    assert Image.open(io.BytesIO(pic.octets)).size == (40, 30)          # saved again, readable
    with pytest.raises(SessionError, match="no post here"):
        await reader.fetch_blob(gid, bl.blob_id(b"something else"))


async def test_an_ignored_author_is_not_decoded_unless_asked(net):
    node, session = net
    addr = await node(max_size=1048576)
    me, reader = session("me", addr), session("reader", addr)
    gid, sent = await _group_with_a_picture(me, png())
    reader.subscribe(gid)
    [msg] = reader.visible(await reader.fetch_group(gid))
    blob = msg.attachments[0]["blob"]
    reader.ignore(me.identity().key_text, "me")
    with pytest.raises(SessionError, match="ignore"):
        await reader.picture(gid, blob)
    assert (await reader.picture(gid, blob, asked=True)).width == 40


async def test_a_node_without_files_says_so(net):
    node, session = net
    with_files, without = await node(max_size=1048576), await node()
    me = session("me", with_files)
    gid, sent = await _group_with_a_picture(me, png())
    await me.fetch_group(gid)
    other = session("other", without)
    other.cache[gid] = me.cache[gid]                 # it read the post elsewhere
    assert await other.node_files(gid) is False
    with pytest.raises(sess.FileUnavailable, match="carries no files") as no:
        await other.fetch_blob(gid, bl.blob_id(sent.octets))
    assert no.value.why == "none"


async def test_a_wrong_blob_is_refused(net, monkeypatch):
    node, session = net
    addr = await node(max_size=1048576)
    me = session("me", addr)
    gid, sent = await _group_with_a_picture(me, png())
    await me.fetch_group(gid)

    async def wrong(self, blob_id):
        return png(colour=(0, 0, 255))
    monkeypatch.setattr(sess.Client, "blob", wrong)
    with pytest.raises(SessionError, match="another file"):
        await me.fetch_blob(gid, bl.blob_id(sent.octets))


def test_the_decoder_saves_pictures_again():
    still = decode.picture(png(w=12, h=7), "image/png")
    assert (still.width, still.height, still.frames) == (12, 7, 1)
    moving = decode.picture(gif(4), "image/gif")
    assert moving.media_type == "image/gif" and moving.frames == 4
    assert getattr(Image.open(io.BytesIO(moving.octets)), "n_frames", 1) == 4


def test_the_decoder_refuses():
    with pytest.raises(decode.DecodeError, match="says it is"):
        decode.picture(png(), "image/jpeg")                      # not what it claims
    with pytest.raises(decode.DecodeError, match="PDF"):
        decode.picture(b"%PDF-1.7\n...", "application/pdf")
    with pytest.raises(decode.DecodeError, match="not a picture"):
        decode.picture(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")
    with pytest.raises(decode.DecodeError, match="could not be read"):
        decode.picture(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")


def test_the_decoder_refuses_huge_pictures():
    # a PNG that claims 10 000 x 10 000 pixels: refused before its pixels are read
    ihdr = b"IHDR" + struct.pack(">IIBBBBB", 10000, 10000, 8, 2, 0, 0, 0)
    bomb = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + ihdr
            + struct.pack(">I", zlib.crc32(ihdr)) + b"\x00\x00\x00\x00IEND\xaeB`\x82")
    with pytest.raises(decode.DecodeError, match="too large"):
        decode.picture(bomb, "image/png")


async def test_the_async_decoder():
    pic = await decode.picture_async(png(w=5, h=5))
    assert (pic.width, pic.height) == (5, 5)


def test_alt_and_dim_in_the_headers():
    data = png()
    [_, (name, value)] = bl.attachment_headers([("a.png", "image/png", data, "Et hus", (40, 30))])
    assert name == "Attachment-1" and "; alt=" in value and value.endswith("; dim=40x30")
    [shown] = bl.shown_attachments([(name, value)])
    assert shown["alt"] == "Et hus" and shown["dim"] == [40, 30] and shown["name"] == "a.png"
    [_, (_, plain)] = bl.attachment_headers([("a.png", "image/png", data)])
    assert "alt=" not in plain and "dim=" not in plain                  # as before
    [_, (_, cut)] = bl.attachment_headers([("a.png", "image/png", data, "æ" * 400, None)])
    assert bl.shown_attachments([("Attachment-1", cut)])[0]["alt"] == "æ" * 256   # 512 octets


async def test_a_file_the_group_s_node_lacks_comes_from_your_other_nodes(net):
    """Found on the project's nodes: node1 and node2 carried files for dk.test.* only, so
    a picture in alt.space.nasa was on node3 and node4 but not on the node it was read
    from. The client asks your other nodes before saying it cannot be had."""
    node, session = net
    with_files, without = await node(max_size=1048576), await node()
    me = session("me", with_files)
    gid, sent = await _group_with_a_picture(me, png())
    await me.fetch_group(gid)
    other = session("other", without)                 # the group is read from this one
    other.add_node(with_files)                         # one of your other nodes has it
    other.cache[gid] = me.cache[gid]
    assert other.node_for(gid) == without
    assert await other.fetch_blob(gid, bl.blob_id(sent.octets)) == sent.octets
    assert (await other.picture(gid, bl.blob_id(sent.octets))).width == 40
