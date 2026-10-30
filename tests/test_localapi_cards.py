"""#792: link cards in the local client API (UN-RFC 0046 section 4.25, UN-RFC 0059): a
card made for a link, sent with a post, shown on the message, kept by an edit, taken off,
and the setting."""
import pytest

aiohttp = pytest.importorskip("aiohttp")

import unseenet.client.session as sess                      # noqa: E402
from unseenet.client import webfetch                        # noqa: E402
from unseenet.client.localapi import LocalAPI               # noqa: E402
from unseenet.core.store import Store                       # noqa: E402
from unseenet.node.server import Node, NodeConfig           # noqa: E402

from test_localapi import Running, _gid, _until             # noqa: E402
from test_link_cards import AV, BT, BT_HEAD, _png           # noqa: E402


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    pages = {BT: ("text/html", BT_HEAD.encode()),
             "https://www.bt.dk/brands/bt/share.jpg": ("image/png", _png((1200, 630))),
             "https://www.bt.dk/brands/bt/icon-192x192.png": ("image/png", _png((192, 192)))}

    async def fetch(url, socks, *, limit, accept=webfetch.PAGE_ACCEPT, language="en"):
        if url not in pages:
            raise webfetch.FetchError("the page answered 404")
        ctype, octets = pages[url]
        return webfetch.Fetched(url, 200, ctype, octets, False)
    monkeypatch.setattr(webfetch, "fetch", fetch)

    async def tor(self, status):
        return 9050
    monkeypatch.setattr(sess.Session, "_ensure_tor", tor)


async def _job(r, ws, path, data):
    status, job = await r.post(path, data)
    assert status == 200, job
    done = await _until(ws, lambda e: e["event"] == "job" and e["job"] == job["job"]
                        and e["state"] in ("reached", "failed"))
    assert done["state"] == "reached", done.get("error")


async def test_make_send_show_keep_and_take_off_a_card(tmp_path):
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), blobs={"max_size": 1048576}))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    api = LocalAPI(tmp_path / "me.vault", refresh_seconds=3600)
    async with Running(api) as r:
        assert (await r.post("/api/unlock", {"passphrase": "pw"}))[0] == 200
        ws = await r.events()
        assert (await r.post("/api/setup", {"display": "Andreas", "node": addr}))[0] == 200
        await _until(ws, lambda e: e["event"] == "refreshed")
        _, made = await r.post("/api/groups", {"name": "dk.nyheder", "type": "open"})
        gid = made["id"]
        await api.session.update_group(gid, attachments={"max_size": 1048576})

        status, got = await r.post("/api/card", {"text": "intet link her"})
        assert status == 200 and got == {"card": None}
        body = f"Så blev han dømt. {BT}\n> citat {AV}"
        status, got = await r.post("/api/card", {"text": body})
        card = got["card"]
        assert card["url"] == BT and card["domain"] == "bt.dk" and card["site"] == "B.T."
        assert card["icon"] and card["picture"]["type"] == "image/jpeg"

        card["title"] = "Min egen overskrift"                       # the user changed it
        path = f"/api/groups/{_gid(gid)}/post"
        status, bad = await r.post(path, {"subject": "Dømt", "body": "uden link", "card": card})
        assert status == 400 and "not in the text" in bad["error"]
        await _job(r, ws, path, {"subject": "Dømt", "body": body, "card": card})
        _, view = await r.get(f"/api/groups/{_gid(gid)}")
        [row] = view["rows"]
        msg = row["message"]
        assert msg["card"]["title"] == "Min egen overskrift" and msg["card"]["domain"] == "bt.dk"
        [att] = msg["attachments"]
        assert att["card"] is True and att["blob"] == msg["card"]["image"]

        await _job(r, ws, f"/api/groups/{_gid(gid)}/edit", {"id": msg["id"], "body": body + "\nmere"})
        _, view = await r.get(f"/api/groups/{_gid(gid)}")
        assert view["rows"][0]["message"]["card"]["title"] == "Min egen overskrift"   # kept
        await _job(r, ws, f"/api/groups/{_gid(gid)}/edit",
                   {"id": view["rows"][0]["message"]["id"], "body": body, "card": None})
        _, view = await r.get(f"/api/groups/{_gid(gid)}")
        assert view["rows"][0]["message"]["card"] is None                            # off

        _, settings = await r.get("/api/settings")
        assert settings["link_cards"] is True
        _, settings = await r.post("/api/settings", {"link_cards": False})
        assert settings["link_cards"] is False
        status, _ = await r.post("/api/card", {"url": BT})
        assert status == 400
    server.close()
