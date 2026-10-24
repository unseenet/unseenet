"""#442: pictures of people in the local client API (UN-RFC 0046 section 4.11): your own
picture shown before it is published, others' pictures checked and decoded by the
runtime, identicons, and the switch to show identicons only."""
import base64
import io

import pytest

aiohttp = pytest.importorskip("aiohttp")

from PIL import Image                                       # noqa: E402

import unseenet.client.session as sess                      # noqa: E402
from unseenet.client.localapi import LocalAPI               # noqa: E402
from unseenet.client.session import Session                 # noqa: E402
from unseenet.core import profiles as prof                  # noqa: E402
from unseenet.core import crypto                          # noqa: E402
from unseenet.core.store import Store                       # noqa: E402
from unseenet.core.vault import Vault                       # noqa: E402
from unseenet.node.server import Node, NodeConfig           # noqa: E402

from test_localapi import Running, _until                   # noqa: E402
from test_localapi_files import jpeg_with_gps               # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)


def photo(w=300, h=200, colour=(200, 60, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(out, "PNG")
    return out.getvalue()


async def _node():
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), profiles="accept",
                                    avatars="accept"))
    server = await node.serve("127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def test_your_picture_and_others(tmp_path):
    server, addr = await _node()
    other = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    other.new_identity("sonia", "Sonia")
    other.add_node(addr)
    await other.publish_picture_file(_file(tmp_path, jpeg_with_gps()), "En tegning")
    sonia = other.identity().key_text
    quiet = Session(Vault.open(tmp_path / "q.vault", "pw", **KDF), status=lambda *_: None)
    quiet.new_identity("tove", "Tove")
    tove = quiet.identity().key_text                     # no picture: the identicon

    api = LocalAPI(tmp_path / "me.vault", refresh_seconds=3600)
    async with Running(api) as r:
        await r.post("/api/unlock", {"passphrase": "pw"})
        ws = await r.events()
        await r.post("/api/setup", {"display": "Andreas", "node": addr})
        await _until(ws, lambda e: e["event"] == "refreshed")

        _, mine = await r.get("/api/profile")
        assert mine["picture"] is None and "reverse image search" in mine["picture_warning"]
        upload = {"data": base64.b64encode(photo()).decode(), "alt": "Rød", "preview": True}
        status, shown = await r.post("/api/profile/picture", upload)
        assert status == 200 and shown["published"] is False
        pic = shown["picture"]
        assert pic["px"] == 128 and pic["alt"] == "Rød" and pic["data"].startswith("data:image/")
        assert api.session.my_picture() is None                     # only shown, not published
        status, done = await r.post("/api/profile/picture", {**upload, "preview": False})
        assert status == 200 and done["published"] and api.session.my_picture()["px"] == 128
        _, mine = await r.get("/api/profile")
        assert mine["picture"]["data"] == done["picture"]["data"]

        status, got = await r.get(f"/api/pictures?keys={sonia},{tove}")
        assert status == 200
        s, t = got["pictures"][sonia], got["pictures"][tove]
        assert s["picture"]["alt"] == "En tegning" and s["picture"]["px"] in (32, 48, 64, 96, 128)
        shown = Image.open(io.BytesIO(base64.b64decode(s["picture"]["data"].split(",", 1)[1])))
        assert shown.size == (s["picture"]["px"],) * 2 and not shown.getexif().get(0x8825)
        assert t["picture"] is None and len(t["identicon"]["cells"]) == 5
        assert t["identicon"] == _icon(tove)

        api.session.hide_profile(sonia)                              # hidden: not decoded
        assert (await r.get(f"/api/pictures?keys={sonia}"))[1]["pictures"][sonia]["picture"] is None
        api.session.hide_profile(sonia, False)
        api.session.__dict__.pop("_picture_cache", None)
        _, st = await r.post("/api/settings", {"pictures": False})   # identicons only
        assert st["pictures"] is False
        assert (await r.get(f"/api/pictures?keys={sonia}"))[1]["pictures"][sonia]["picture"] is None
        assert (await r.post("/api/profile/picture", {"remove": True}))[1]["published"] is False
        assert (await r.get("/api/pictures?keys=nonsense"))[0] == 400
    await other.close()
    server.close()


async def test_a_picture_that_is_not_what_it_says_is_not_shown(tmp_path, monkeypatch):
    server, addr = await _node()
    other = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    other.new_identity("sonia", "Sonia")
    other.add_node(addr)
    out = io.BytesIO()
    Image.new("RGB", (40, 32), (1, 2, 3)).save(out, "PNG")          # not square
    monkeypatch.setattr(prof, "check_picture", lambda obj: base64.b64decode(obj["data"]))
    await other.publish_picture({"v": 1, "type": "image/png", "px": 40,
                                 "data": base64.b64encode(out.getvalue()).decode()})
    me = Session(Vault.open(tmp_path / "m.vault", "pw", **KDF), status=lambda *_: None)
    me.new_identity("me", "Me")
    me.add_node(addr)
    key = other.identity().key_text
    assert (await me.pictures([key]))[key] is None
    await other.close()
    await me.close()
    server.close()


def _file(tmp_path, octets):
    path = tmp_path / "picture.jpg"
    path.write_bytes(octets)
    return path


def _icon(key):
    from unseenet.core import crypto
    icon = prof.identicon(crypto.key_from_text(key))
    return {"hue": icon.hue, "cells": [list(r) for r in icon.cells], "colour": icon.hex()}


@pytest.mark.parametrize("n", [1, 2, 4, 5])
def test_a_stored_picture_is_shown_from_its_base64url(n):
    """A picture object keeps its octets as unpadded base64url (UN-RFC 0022 section 8.1);
    the page gets them back whole whatever their length."""
    from unseenet.client.localapi.api.pictures import _shown
    from unseenet.core.encoding import b64
    octets = (b"\xfb\xff\xbf" * 2)[:n]                   # needs padding, and "-" "_"
    shown = _shown({"type": "image/png", "px": 64, "data": b64(octets), "alt": "a"})
    assert base64.b64decode(shown["data"].split(",", 1)[1]) == octets


async def test_identicons_when_the_node_is_away(tmp_path):
    """No node to ask: every key still gets its identicon, and no picture is
    remembered for it, so it is asked for again later."""
    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.data["nodes"] = ["127.0.0.1:1"]
    other = crypto.Identity.generate().key_text
    assert await s.pictures([other]) == {other: None}
    assert other not in s.__dict__.get("_picture_cache", {})
