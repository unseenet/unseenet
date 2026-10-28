"""#715, UN-RFC 0022 section 10 and UN-RFC 0056 section 5: a node's refusal lists cover a
profile picture and each group emoji as they cover an attachment."""

import io

import pytest
from PIL import Image

import unseenet.client.session as sess
from unseenet.client.session import Session, SessionError
from unseenet.core import blobs as bl
from unseenet.core.encoding import b64decode
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


def _png(colour) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (200, 200), colour).save(out, "PNG")
    return out.getvalue()


async def _owner(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), avatars="accept", emoji="accept"))
    server = await node.serve("127.0.0.1", 0)
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    await s.ensure_inbox()
    return node, server, s


async def test_a_refused_profile_picture(tmp_path, monkeypatch):
    node, server, s = await _owner(tmp_path, monkeypatch)
    pic = s.make_picture(_png((10, 120, 200)))
    node.store.refuse_blob(bl.blob_id(b64decode(pic["data"])), "on a list")
    with pytest.raises(SessionError, match="^Your node refuses this picture"):
        await s.publish_picture(pic)
    await s.publish_picture(s.make_picture(_png((200, 30, 30))))      # another one is fine
    await s.close()
    server.close()


async def test_a_refused_group_emoji(tmp_path, monkeypatch):
    node, server, s = await _owner(tmp_path, monkeypatch)
    gid = await s.create_group("dk.test", "open")
    pic = s.make_group_emoji(_png((10, 120, 200)))
    node.store.refuse_blob(bl.blob_id(b64decode(pic["data"])), "on a list")
    with pytest.raises(SessionError, match="^Your node refuses this picture"):
        await s.set_group_emoji(gid, {"marsvin": pic})
    await s.close()
    server.close()
