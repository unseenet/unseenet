"""#577: exporting your data (UN-RFC 0049 section 7) - your articles as signed, their
files, your sites, profile and state; never keys; private messages only when chosen,
and then the whole file encrypted with a passphrase."""
import io
import json
import zipfile
from datetime import timedelta

import pytest

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI
from unseenet.client.session import Session, SessionError
from unseenet.core.article import Article
from unseenet.core.blobs import BlobStore
from unseenet.core.store import Store
from unseenet.core.vault import Vault, unseal
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def two(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), sites="accept"))
    node.config.blobs = {"max_size": 1048576}
    node.blobs = BlobStore()
    server = await node.serve("127.0.0.1", 0)
    addr = "127.0.0.1:%d" % server.sockets[0].getsockname()[1]
    made = []

    def person(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        made.append(s)
        return s
    yield person
    for s in made:
        await s.close()
    server.close()


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 40)).save(buf, "JPEG")
    return buf.getvalue()


async def _content(me, sonia, tmp_path):
    await me.ensure_inbox()
    await sonia.ensure_inbox()
    gid = await me.create_group("dk.snak", "channel",
                                extra={"attachments": {"max_size": 1048576, "types": ["image/*"]}})
    pic = tmp_path / "rose.jpg"
    pic.write_bytes(_jpeg())
    await me.post(gid, "Roser", "Se min rose\n", files=me.prepare_files([pic]))
    await me.fetch_group(gid)
    site = await me.create_group("dk.side", "channel", view="pages")
    await me.fetch_group(site)
    await me.put_page(site, "index", "# Velkommen\n", "Velkommen")
    await me.fetch_group(site)
    await sonia.send_chat("contact:" + me.identity().key_text, "Hemmelig hilsen")
    await me.fetch_group(me.my_inbox)
    return gid, site


async def test_an_export_without_private_messages(two, tmp_path):
    me, sonia = two("me"), two("sonia")
    gid, site = await _content(me, sonia, tmp_path)
    out = await me.export(tmp_path / "out.zip")
    assert not out["encrypted"] and out["articles"] >= 2 and out["files"] == 1 and out["sites"] == 1
    z = zipfile.ZipFile(tmp_path / "out.zip")
    names = z.namelist()
    info = json.loads(z.read("export.json"))
    assert info["version"] == 1 and info["fingerprint"] == me.identity().fingerprint
    assert "retention" in info["note"] and "private.json" not in names
    # articles exactly as signed: they check against the key
    post = next(n for n in names if n.startswith("articles/") and b"Roser" in z.read(n))
    art = Article.from_bytes(z.read(post))
    art.verify_signature()                       # raises if it is not as signed
    assert art.author_key == me.identity().public_key
    assert any(n.startswith("files/blob1_") for n in names)
    assert any(n.startswith("sites/") and n.endswith("index.eml") for n in names)
    assert "index.html" in names and "state.json" in names and "profile.json" in names
    # never keys, never the private chat
    blob = b"".join(z.read(n) for n in names)
    import base64
    seed = me.identity().seed
    for form in (seed, seed.hex().encode(), base64.b64encode(seed), base64.urlsafe_b64encode(seed).rstrip(b"=")):
        assert form not in blob
    assert b"Hemmelig hilsen" not in blob and b"secret" not in json.dumps(info).encode()


async def test_with_private_messages_it_is_encrypted(two, tmp_path):
    me, sonia = two("me"), two("sonia")
    await _content(me, sonia, tmp_path)
    with pytest.raises(SessionError, match="passphrase"):
        await me.export(tmp_path / "p.zip", private=True)
    out = await me.export(tmp_path / "p.zip", private=True, passphrase="lang hemmelig sætning")
    assert out["encrypted"] and out["path"].endswith(".zip.sealed") and out["private"] >= 1
    raw = (tmp_path / "p.zip.sealed").read_bytes()
    assert b"Hemmelig hilsen" not in raw and not raw.startswith(b"PK")
    z = zipfile.ZipFile(io.BytesIO(unseal(raw, "lang hemmelig sætning")))
    chats = json.loads(z.read("private.json"))
    assert any(c["body"].startswith("Hemmelig hilsen") for c in chats)


async def test_the_local_api(two, tmp_path):
    me = two("me")
    await me.ensure_inbox()
    api = LocalAPI(session=me)
    out = await api.export({"path": str(tmp_path / "a.zip")})
    assert out["path"].endswith("a.zip") and "retention" in out["note"]
    import os
    if os.name == "posix":                                   # Windows has no such modes
        assert (tmp_path / "a.zip").stat().st_mode & 0o777 == 0o600


async def test_the_cli(tmp_path, monkeypatch, capsys):
    from argparse import Namespace
    from unseenet import cli
    from unseenet.node.server import Node, NodeConfig
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setenv("UNSEENET_EXPORT_PASSPHRASE", "sætning")
    monkeypatch.setattr(cli, "DEFAULT_POW", 8)
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    a = cli.App(Vault.open(tmp_path / "me.vault", "pw", **KDF))
    a.data["nodes"].append(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    await cli.c_id_new(a, Namespace(name="me", display=None))
    try:
        await cli.c_export(a, Namespace(identity=None, json=True, file=str(tmp_path / "e.zip"), private=True))
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert out["encrypted"] and (tmp_path / "e.zip.sealed").exists()
    finally:
        if a._session is not None:
            await a._session.close()
        server.close()
