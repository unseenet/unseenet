"""#387 part 2: writing from the command line through Session - replies and comments,
chat lines, formats, edits, and files with their metadata taken out."""
import io
import json
from argparse import Namespace

import pytest
from PIL import Image

from unseenet import cli
from unseenet.core import blobs as bl
from unseenet.core.article import Article
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}
FILES = {"max_size": 1048576, "types": ["image/*"]}


async def _setup(tmp_path, monkeypatch, blobs=True):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(cli, "DEFAULT_POW", BITS)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0),
                                    blobs={"max_size": 1048576} if blobs else None))
    server = await node.serve("127.0.0.1", 0)
    address = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    apps = []

    async def app(name):
        a = cli.App(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF))
        a.data["nodes"].append(address)
        await cli.c_id_new(a, Namespace(name=name, display=None))
        apps.append(a)
        return a

    async def done():
        for a in apps:
            if a._session is not None:
                await a._session.close()
        server.close()
    return node, app, done


def _args(**kw):
    base = dict(identity=None, json=True, subject=None, body="Tekst\n", kind="post", reply_to=None,
                edit=None, format=None, attach=None, publish_outside_tor=False, local=False,
                moderator=None, poster=None, title=None, description=None, min_pow=BITS,
                retention_days=None, view=None, kinds=None, rules=None, comments=None,
                comment_days=None, attachments=None, types=None, max_pins=None, max_pages=None,
                home=None)
    return Namespace(**(base | kw))


def _json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _art(node, mid):
    return Article.from_bytes(node.store.get(mid))


def _photo(tmp_path, name="DSC_0001.jpg"):
    """A JPEG that says far too much: camera, serial number, owner, GPS, a comment."""
    img = Image.new("RGB", (64, 32), (10, 120, 200))
    ex = Image.Exif()
    ex[0x010F] = "SecretCam"
    ex[0xA431] = "SN123456"
    ex[0x013B] = "Andreas"
    gps = ex.get_ifd(0x8825)
    gps[2] = (55.0, 59.0, 0.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=ex, comment=b"secret comment")
    path = tmp_path / name
    path.write_bytes(buf.getvalue())
    return path


async def test_reply_comment_chat_format_and_edit(tmp_path, monkeypatch, capsys):
    node, app, done = await _setup(tmp_path, monkeypatch)
    me, other = await app("me"), await app("other")
    await cli.c_group_create(me, _args(name="dk.snak", type="open"))
    gid = _json(capsys)["group"]

    await cli.c_post(me, _args(group=gid, subject="Hej", body="# Overskrift\n", format="markdown"))
    first = _json(capsys)["message_id"]
    assert _art(node, first)["Content-Type"].startswith("text/markdown")

    await cli.c_post(other, _args(group=gid, reply_to=first, format="plain"))
    reply = _art(node, _json(capsys)["message_id"])
    assert reply["References"] == first and reply["Subject"] == "Re: Hej"
    assert reply["Content-Type"].startswith("text/plain")

    await cli.c_post(me, _args(group=gid, kind="chat", body="bare en linje\n"))
    line = _art(node, _json(capsys)["message_id"])
    assert line["Message-Kind"] == "chat" and not line.get("Subject")

    await cli.c_post(me, _args(group=gid, edit=first, body="Rettet\n"))
    out = _json(capsys)
    assert out["edited"] and _art(node, out["message_id"])["Supersedes"] == first
    with pytest.raises(SystemExit, match="your own"):
        await cli.c_post(other, _args(group=gid, edit=first, body="Nej\n"))
    with pytest.raises(SystemExit, match="subject"):
        await cli.c_post(me, _args(group=gid))
    await done()


async def test_a_comment_in_a_channel_only_where_comments_are_open(tmp_path, monkeypatch, capsys):
    node, app, done = await _setup(tmp_path, monkeypatch)
    me, reader = await app("me"), await app("reader")
    await cli.c_group_create(me, _args(name="dk.nyt", type="channel", view="feed", comments="open"))
    gid = _json(capsys)["group"]
    await cli.c_post(me, _args(group=gid, subject="Nyhed"))
    news = _json(capsys)["message_id"]
    await cli.c_post(reader, _args(group=gid, reply_to=news, body="God nyhed\n"))
    assert _art(node, _json(capsys)["message_id"])["References"] == news
    with pytest.raises(SystemExit, match="Not posted"):          # readers do not start threads
        await cli.c_post(reader, _args(group=gid, subject="Mit eget"))
    await done()


async def test_files_go_without_their_metadata(tmp_path, monkeypatch, capsys):
    node, app, done = await _setup(tmp_path, monkeypatch)
    me = await app("me")
    await cli.c_group_create(me, _args(name="dk.billeder", type="open", attachments=1048576,
                                       types="image/*"))
    gid = _json(capsys)["group"]
    photo = _photo(tmp_path)
    original = photo.read_bytes()
    await cli.c_post(me, _args(group=gid, subject="Et billede", attach=[str(photo)]))
    out = _json(capsys)
    art = _art(node, out["message_id"])
    (bid, size), = bl.parse_blobs(art)
    sent = node.blobs.get(bid)
    assert sent is not None and len(sent) == size == out["files"][0]["size"]
    for secret in (b"SecretCam", b"SN123456", b"Andreas", b"secret comment", b"Exif"):
        assert secret in original and secret not in sent
    att, = bl.parse_attachments(art.headers)
    assert att["type"] == "image/jpeg" and out["files"][0]["name"] == "DSC_0001.jpg"
    assert Image.open(io.BytesIO(sent)).size == (64, 32)
    await done()


async def test_files_that_cannot_go(tmp_path, monkeypatch, capsys):
    node, app, done = await _setup(tmp_path, monkeypatch)
    me = await app("me")
    await cli.c_group_create(me, _args(name="dk.tekst", type="open"))
    plain = _json(capsys)["group"]
    await cli.c_group_create(me, _args(name="dk.billeder", type="open", attachments=1048576,
                                       types="image/*"))
    pictures = _json(capsys)["group"]
    pdf = tmp_path / "noter.pdf"
    pdf.write_bytes(b"%PDF-1.7\n% nothing\n")
    with pytest.raises(SystemExit, match="takes no files"):
        await cli.c_post(me, _args(group=plain, subject="x", attach=[str(_photo(tmp_path))]))
    with pytest.raises(SystemExit, match="application/pdf"):
        await cli.c_post(me, _args(group=pictures, subject="x", attach=[str(pdf)]))
    assert "metadata" in capsys.readouterr().err                # the PDF's note was shown
    await done()


async def test_a_node_without_files_says_so(tmp_path, monkeypatch, capsys):
    node, app, done = await _setup(tmp_path, monkeypatch, blobs=False)
    me = await app("me")
    await cli.c_group_create(me, _args(name="dk.billeder", type="open", attachments=1048576))
    gid = _json(capsys)["group"]
    with pytest.raises(SystemExit, match="carries no files"):
        await cli.c_post(me, _args(group=gid, subject="x", attach=[str(_photo(tmp_path))]))
    await done()
