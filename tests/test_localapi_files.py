"""#442: files on posts in the local client API (UN-RFC 0046 section 4.10): what a group
takes, posting files, a picture made safe to show, and the file itself to save."""
import base64
import io

import pytest

aiohttp = pytest.importorskip("aiohttp")

from PIL import Image                                       # noqa: E402

import unseenet.client.session as sess                      # noqa: E402
from unseenet.client.localapi import LocalAPI               # noqa: E402
from unseenet.core.store import Store                       # noqa: E402
from unseenet.node.server import Node, NodeConfig           # noqa: E402

from test_localapi import Running, _gid, _until             # noqa: E402


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)


def jpeg_with_gps() -> bytes:
    img = Image.new("RGB", (64, 48), (20, 120, 200))
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (55.0, 52.0, 0.0)}           # GPS: where it was taken
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


async def _set_up(r, addr):
    assert (await r.post("/api/unlock", {"passphrase": "pw"}))[0] == 200
    ws = await r.events()
    assert (await r.post("/api/setup", {"display": "Andreas", "node": addr}))[0] == 200
    await _until(ws, lambda e: e["event"] == "refreshed")
    return ws


async def test_post_show_and_save_a_picture(tmp_path):
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), blobs={"max_size": 1048576}))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    api = LocalAPI(tmp_path / "me.vault", refresh_seconds=3600)
    async with Running(api) as r:
        ws = await _set_up(r, addr)
        status, made = await r.post("/api/groups", {"name": "dk.billeder", "type": "open"})
        assert status == 200
        gid = made["id"]
        _, view = await r.get(f"/api/groups/{_gid(gid)}")
        assert view["group"]["files"] is None                       # takes no files yet
        photo = {"name": "ferie.jpg", "data": base64.b64encode(jpeg_with_gps()).decode(),
                 "alt": "Stranden ved Askø"}
        status, body = await r.post(f"/api/groups/{_gid(gid)}/post",
                                    {"subject": "Ferie", "body": "Se", "files": [photo]})
        assert status == 400 and "takes no files" in body["error"]

        await api.session.update_group(gid, attachments={"max_size": 1048576})
        _, view = await r.get(f"/api/groups/{_gid(gid)}")
        assert view["group"]["files"] == {"max_size": 1048576, "types": []}
        assert view["group"]["node_files"] is True
        status, job = await r.post(f"/api/groups/{_gid(gid)}/post",
                                   {"subject": "Ferie", "body": "", "files": [photo]})
        assert status == 200
        done = await _until(ws, lambda e: e["event"] == "job" and e["job"] == job["job"]
                            and e["state"] in ("reached", "failed"))
        assert done["state"] == "reached", done.get("error")

        _, view = await r.get(f"/api/groups/{_gid(gid)}")
        [row] = view["rows"]
        [att] = row["message"]["attachments"]
        assert (att["name"], att["type"], att["alt"], att["dim"]) == \
            ("ferie.jpg", "image/jpeg", "Stranden ved Askø", [64, 48])
        url = f"/api/groups/{_gid(gid)}/files/{att['blob']}"
        status, pic = await r.get(url)
        assert status == 200 and (pic["type"], pic["width"], pic["height"]) == ("image/jpeg", 64, 48)
        assert pic["data"].startswith("data:image/jpeg;base64,")
        shown = Image.open(io.BytesIO(base64.b64decode(pic["data"].split(",", 1)[1])))
        assert shown.size == (64, 48) and not shown.getexif().get(0x8825)      # no GPS
        status, saved = await r.get(url + "?save=1")
        assert status == 200 and saved["name"] == "ferie.jpg" and saved["size"] == att["size"]
        assert not Image.open(io.BytesIO(base64.b64decode(saved["data"]))).getexif().get(0x8825)

        status, body = await r.get(f"/api/groups/{_gid(gid)}/files/blob1:{'a' * 52}")
        assert status == 404
    server.close()


async def test_a_node_without_files(tmp_path):
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    api = LocalAPI(tmp_path / "me.vault", refresh_seconds=3600)
    async with Running(api) as r:
        await _set_up(r, addr)
        _, made = await r.post("/api/groups", {"name": "dk.billeder", "type": "open"})
        _, view = await r.get(f"/api/groups/{_gid(made['id'])}")
        assert view["group"]["node_files"] is False
    server.close()
