"""The local client API (UN-RFC 0046) against a local node, over real HTTP."""
import asyncio
import json
import stat
import sys

import pytest

aiohttp = pytest.importorskip("aiohttp")

import unseenet.client.session as sess                      # noqa: E402
from unseenet.client.localapi import LocalAPI               # noqa: E402
from unseenet.client.localapi import server as srv          # noqa: E402
from unseenet.client.session import Session                 # noqa: E402
from unseenet.core import crypto                            # noqa: E402
from unseenet.core.store import Store                       # noqa: E402
from unseenet.core.vault import Vault                       # noqa: E402
from unseenet.node.server import Node, NodeConfig           # noqa: E402

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)


async def _node():
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    return node, server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


class Running:
    """``serve()`` in the background, and a client that talks to it."""

    def __init__(self, api, **kw):
        self.api, self.kw = api, kw
        self.stop, self.started = asyncio.Event(), asyncio.Event()

    async def __aenter__(self):
        def ready(port, token):
            self.port, self.token = port, token
        self.task = asyncio.create_task(srv.serve(self.api, on_ready=ready, started=self.started,
                                                  stop=self.stop, **self.kw))
        await asyncio.wait_for(self.started.wait(), 10)
        self.base = f"http://127.0.0.1:{self.port}"
        self.http = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *exc):
        await self.http.close()
        self.stop.set()
        await self.task
        await self.api.close()

    async def call(self, method, path, body=None, *, token=True, headers=None):
        h = {srv.TOKEN_HEADER: self.token} if token else {}
        h.update(headers or {})
        async with self.http.request(method, self.base + path, json=body, headers=h) as r:
            return r.status, await r.json()

    async def get(self, path, **kw):
        return await self.call("GET", path, **kw)

    async def post(self, path, body=None, **kw):
        return await self.call("POST", path, {} if body is None else body, **kw)

    async def events(self):
        return await self.http.ws_connect(
            self.base + "/api/events",
            protocols=("unseenet", srv.TOKEN_PROTOCOL + self.token))


async def _until(ws, pred, timeout=30):
    async def wait():
        async for msg in ws:
            data = json.loads(msg.data)
            if pred(data):
                return data
    return await asyncio.wait_for(wait(), timeout)


def _gid(path_id: str) -> str:
    from urllib.parse import quote
    return quote(path_id, safe="")


async def test_security_rules(tmp_path):
    api = LocalAPI(tmp_path / "me.vault")
    async with Running(api) as r:
        assert (await r.get("/api/state", token=False))[0] == 401
        status, _ = await r.call("GET", "/api/state", headers={srv.TOKEN_HEADER: "x" * 43})
        assert status == 401
        status, body = await r.get("/api/state", headers={"Host": f"evil.example:{r.port}"})
        assert status == 403 and body["error"] == "wrong host"       # DNS rebinding
        status, _ = await r.get("/api/state", headers={"Origin": "https://evil.example"})
        assert status == 403
        status, state = await r.get("/api/state", headers={"Origin": r.base})
        assert status == 200 and state["api"] == 1 and not state["unlocked"]
        async with r.http.get(r.base + "/api/state", headers={srv.TOKEN_HEADER: r.token}) as resp:
            assert "Access-Control-Allow-Origin" not in resp.headers
            assert resp.headers["Content-Security-Policy"].startswith("default-src 'none'")
        assert (await r.get("/api/groups"))[0] == 409                 # locked
        with pytest.raises(aiohttp.WSServerHandshakeError):           # no token, no events
            await r.http.ws_connect(r.base + "/api/events", protocols=("unseenet",))


async def test_api_file_is_private_and_goes_away(tmp_path):
    api = LocalAPI(tmp_path / "me.vault")
    f = tmp_path / "me.vault.api"
    async with Running(api, api_file=f) as r:
        line = f.read_text().strip()
        assert line == f"UNSEENET-API 1 http://127.0.0.1:{r.port}/ {r.token}"
        if sys.platform != "win32":          # no POSIX modes: the user's own folder protects it
            assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert not f.exists()


async def test_a_person_sets_up_follows_and_posts(tmp_path):
    node, server, addr = await _node()
    other = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    other.new_identity("sonia", "Sonia")
    other.add_node(addr)
    await other.ensure_inbox()
    g = await other.create_group("dk.snak", "open", min_pow=10)
    await other.post(g, "Hej", "Første **fed** <script>alert(1)</script>\n")

    api = LocalAPI(tmp_path / "me.vault", refresh_seconds=3600)
    async with Running(api) as r:
        assert (await r.post("/api/unlock", {"passphrase": "pw"}))[1]["setup"] is True
        status, body = await r.post("/api/setup", {"display": "Andreas"})
        assert status == 400 and "node" in body["error"]
        ws = await r.events()
        status, state = await r.post("/api/setup", {"display": "Andreas", "node": addr})
        assert status == 200 and not state["setup"] and state["identity"]["display"] == "Andreas"
        await _until(ws, lambda e: e["event"] == "refreshed")
        said = await _until(ws, lambda e: e["event"] == "status")
        assert said["text"] == f"Connected to {addr}"

        assert (await r.post("/api/subscribe", {"id": g, "on": True}))[0] == 200
        await _until(ws, lambda e: e["event"] == "group-updated" and e["group_id"] == g)
        _, listing = await r.get("/api/groups")
        assert [x["id"] for x in listing["groups"] if x["id"] == g] == [g]
        assert all(x["v"] == 1 for x in listing["groups"])
        _, view = await r.get(f"/api/groups/{_gid(g)}")
        assert view["group"]["label"] == "dk.snak" and view["group"]["shown"].startswith("dk.snak")
        assert listing["name_requests"] == 0
        [row] = view["rows"]
        assert row["message"]["subject"] == "Hej" and row["who"] and row["depth"] == 0
        # Markdown as a tree; HTML in a post stays text, never markup (UN-RFC 0031)
        [para] = row["tree"]
        assert [n["t"] for n in para["c"]] == ["text", "strong", "text"]
        assert para["c"][2]["v"] == " <script>alert(1)</script>"
        [dk] = [h for h in listing["hierarchies"] if h["name"] == "dk"]
        assert g in json.dumps(dk["tree"])

        status, body = await r.post(f"/api/groups/{_gid(g)}/post", {"kind": "post", "body": "x"})
        assert status == 400 and "subject" in body["error"]
        status, job = await r.post(f"/api/groups/{_gid(g)}/post",
                                   {"kind": "post", "subject": "Svar", "body": "Hej selv",
                                    "references": [row["message"]["id"]]})
        assert status == 200
        done = await _until(ws, lambda e: e["event"] == "job" and e["job"] == job["job"]
                            and e["state"] in ("reached", "failed"))
        assert done["state"] == "reached", done.get("error")
        _, view = await r.get(f"/api/groups/{_gid(g)}")
        reply = [x for x in view["rows"] if x["message"]["subject"] == "Svar"][0]
        assert reply["depth"] == 1 and reply["may_edit"] and reply["may_withdraw"] and reply["mine"]
        assert not [x for x in view["rows"] if x["message"]["subject"] == "Hej"][0]["mine"]

        # edit it, then withdraw it
        status, job = await r.post(f"/api/groups/{_gid(g)}/edit",
                                   {"id": reply["message"]["id"], "body": "Hej selv!"})
        done = await _until(ws, lambda e: e["event"] == "job" and e["job"] == job["job"]
                            and e["state"] in ("reached", "failed"))
        assert done["state"] == "reached", done.get("error")
        _, view = await r.get(f"/api/groups/{_gid(g)}")
        newest = [x for x in view["rows"] if x["message"]["subject"] == "Svar"][0]
        assert newest["message"]["text"].startswith("Hej selv!")
        status, _ = await r.post(f"/api/groups/{_gid(g)}/withdraw", {"id": newest["message"]["id"]})
        assert status == 200

        # read marks, settings, contacts, ignore
        await r.post(f"/api/groups/{_gid(g)}/read", {"ids": [row["message"]["id"]]})
        _, view = await r.get(f"/api/groups/{_gid(g)}")
        assert [x["read"] for x in view["rows"] if x["message"]["subject"] == "Hej"] == [True]
        _, st = await r.post("/api/settings", {"markdown": False, "private_min_ripe": 1})
        assert st["markdown"] is False and st["private_min_ripe"] == 1
        assert (await r.post("/api/settings", {"private_min_ripe": 9}))[0] == 400
        assert (await r.post("/api/settings", {"colour": "red"}))[0] == 400
        sonia = other.identity().key_text
        assert (await r.post("/api/contacts", {"key": sonia, "name": "Sonia"}))[0] == 200
        _, listing = await r.get("/api/groups")
        assert any(p["key"] == sonia and p["contact"] for p in listing["people"])
        assert (await r.post("/api/contacts", {"key": "nonsense"}))[0] == 400
        await r.post("/api/ignore", {"key": sonia, "on": True})
        assert [x["key"] for x in (await r.get("/api/ignore"))[1]["ignored"]] == [sonia]
        _, view = await r.get(f"/api/groups/{_gid(g)}")
        assert not [x for x in view["rows"] if x["message"]["subject"] == "Hej"]

        # the pseudo groups: For you, and a chat with one person (UN-RFC 0046 section 4.3)
        _, fy = await r.get("/api/groups/" + _gid("for-you:"))
        assert fy["group"]["id"] == "for-you:" and fy["group"]["label"] == "For you"
        _, chat = await r.get("/api/groups/" + _gid("contact:" + sonia))
        assert chat["group"]["type"] == "contact" and chat["group"]["view"] == "chat"
        status, job = await r.post("/api/groups/" + _gid("contact:" + sonia) + "/post",
                                   {"kind": "chat", "body": "Hej Sonia"})
        assert status == 200
        done = await _until(ws, lambda e: e["event"] == "job" and e["job"] == job["job"]
                            and e["state"] in ("reached", "failed"))
        assert done["state"] == "reached", done.get("error")
        _, chat = await r.get("/api/groups/" + _gid("contact:" + sonia))
        assert [x["message"]["text"] for x in chat["rows"]] == ["Hej Sonia"] and chat["rows"][0]["mine"]
        _, listing = await r.get("/api/groups")
        assert [p["key"] for p in listing["people"]] == [sonia]
        await r.post("/api/contacts", {"key": sonia, "remove": True})
        _, listing = await r.get("/api/groups")            # not a contact: the name in her posts
        assert [(p["contact"], p["name"].split("~")[0]) for p in listing["people"]] == [(False, "Sonia")]
        await r.post("/api/ignore", {"key": sonia, "on": False})

        # a group of your own
        status, made = await r.post("/api/groups", {"name": "dk.mit", "type": "moderated",
                                                    "kinds": "post", "title": "Mit"})
        assert status == 200
        assert (await r.post(f"/api/groups/{_gid(made['id'])}/settings",
                             {"description": "Om mig"}))[0] == 200
        assert (await r.post(f"/api/groups/{_gid(made['id'])}/settings",
                             {"owner": "someone"}))[0] == 400
        _, view = await r.get(f"/api/groups/{_gid(made['id'])}")
        assert view["group"]["owner"] and view["group"]["kinds"] == ["post"]
        assert view["group"]["roles"]["maintainer"] is False
        assert (await r.get("/api/groups/nonsense@0000"))[0] == 404

        # may you write, before you write (#320): posts only here, no chat lines
        w = view["group"]["write"]
        assert w["post"]["allowed"] and not w["chat"]["allowed"] and w["chat"]["code"] == "kind"
        assert w["chat"]["reason"]
        _, view = await r.get(f"/api/groups/{_gid(g)}")
        assert view["rows"] and all(x["reply"]["allowed"] for x in view["rows"])
        _, fy = await r.get("/api/groups/" + _gid("for-you:"))
        assert "write" not in fy["group"]

        # profiles (#320): the warning, a form's fields, hiding someone's
        _, mine = await r.get("/api/profile")
        assert mine["mine"] and mine["published"] is False and "Anybody" in mine["warning"]
        assert "mastodon" in mine["link_kinds"]
        status, mine = await r.post("/api/profile", {"edit": {
            "about": "Hej *med* dig", "markdown": True, "lang": "da, en",
            "links": [{"kind": "Web", "value": "https://unseenet.org"}, {"kind": "x", "value": " "}]}})
        assert status == 200 and mine["published"] is True
        assert mine["profile"]["lang"] == ["da", "en"] and mine["profile"]["links"] == [
            {"kind": "web", "value": "https://unseenet.org"}]
        assert (await r.post("/api/profile", {"edit": {"lang": "not a language!"}}))[0] == 400
        _, theirs = await r.get("/api/profile?key=" + sonia)
        assert not theirs["mine"] and theirs["hidden"] is False and theirs["label"]
        assert (await r.post("/api/profile/hide", {"key": sonia, "hidden": True}))[1]["hidden"]
        _, theirs = await r.get("/api/profile?key=" + sonia)
        assert theirs["hidden"] is True and theirs["profile"] is None
        await r.post("/api/profile/hide", {"key": sonia, "hidden": False})
        me = (await r.get("/api/state"))[1]["identity"]["key"]
        assert (await r.post("/api/profile/hide", {"key": me}))[0] == 400

        # a new passphrase (#320)
        status, body = await r.post("/api/passphrase", {"old": "wrong", "new": "newpass"})
        assert status == 400 and "not right" in body["error"]
        assert (await r.post("/api/passphrase", {"old": "pw", "new": "x"}))[0] == 400
        assert (await r.post("/api/passphrase", {"old": "pw", "new": "newpass"}))[1] == {"ok": True}
        assert (await r.post("/api/passphrase", {"old": "newpass", "new": "again"}))[0] == 200
        await ws.close()
    await other.close()
    server.close()


async def test_a_service_posts_articles_with_its_own_headers(tmp_path):
    node, server, addr = await _node()
    owner = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    owner.new_identity("andreas", "Andreas")
    owner.add_node(addr)
    g = await owner.create_group("dk.bot", "open", min_pow=10)

    bot = Session.from_key(crypto.Identity.generate(), tmp_path / "bot.state.json",
                           display="Botten", status=lambda *_: None)
    bot.add_node(addr)
    bot.subscribe(g)
    api = LocalAPI(session=bot, service=True, refresh_seconds=3600)
    await api.start()
    async with Running(api) as r:
        _, state = await r.get("/api/state")
        assert state["service"] and state["unlocked"] and not state["setup"]
        assert (await r.post("/api/unlock", {"passphrase": "x"}))[0] == 400
        ws = await r.events()
        status, body = await r.post("/api/articles", {"group": g, "subject": "Vejret",
                                                      "body": "Sol\n", "headers": [["Path", "x"]]})
        assert status == 400 and "Path" in body["error"]
        status, job = await r.post("/api/articles", {
            "group": g, "subject": "Vejret", "body": "Sol\n", "from": "Vejrbotten",
            "headers": [["X-Source", "dmi"], ["Gateway-Origin", "test"]]})
        assert status == 200, job
        done = await _until(ws, lambda e: e["event"] == "job" and e["job"] == job["job"]
                            and e["state"] in ("reached", "failed"))
        assert done["state"] == "reached", done.get("error")
        await ws.close()
    await owner.fetch_group(g)
    [m] = [m for m in owner.cache[g].values() if m.subject == "Vejret"]
    raw = node.store.get(m.message_id)
    assert b"\r\nX-Source: dmi\r\n" in raw and b"\r\nGateway-Origin: test\r\n" in raw
    assert m.from_name == "Vejrbotten" and m.author_key == bot.identity().key_text
    await owner.close()
    server.close()


async def test_pausing_ripening_over_the_api(tmp_path):
    """#337: POST /api/ripening, the state's "paused", and an event for every window."""
    assert (await _locked_ripening(tmp_path)) == 409
    node, server, addr = await _node()
    bot = Session.from_key(crypto.Identity.generate(), tmp_path / "bot.state.json",
                           status=lambda *_: None)
    bot.add_node(addr)
    api = LocalAPI(session=bot, service=True, refresh_seconds=3600)
    await api.start()
    async with Running(api) as r:
        _, state = await r.get("/api/state")
        assert state["ripening"]["paused"] is False
        assert (await r.post("/api/ripening", {"paused": "yes"}))[0] == 400
        ws = await r.events()
        status, rip = await r.post("/api/ripening", {"paused": True})
        assert status == 200 and rip["paused"] is True and "level" in rip
        assert (await _until(ws, lambda e: e["event"] == "ripening-paused"))["paused"] is True
        assert (await r.get("/api/state"))[1]["ripening"]["paused"] is True
        status, rip = await r.post("/api/ripening", {"paused": False})
        assert status == 200 and rip["paused"] is False
        assert (await _until(ws, lambda e: e["event"] == "ripening-paused"))["paused"] is False
        await ws.close()
    server.close()


async def _locked_ripening(tmp_path) -> int:
    async with Running(LocalAPI(tmp_path / "locked.vault")) as r:
        return (await r.post("/api/ripening", {"paused": True}))[0]


async def test_unseenet_serve_announces_itself(tmp_path):
    key = tmp_path / "bot.key"
    key.write_text(crypto.Identity.generate().seed.hex() + "\n")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "from unseenet.cli import client_main; client_main()",
        "serve", "--key-file", str(key), "--node", "127.0.0.1:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        line = (await asyncio.wait_for(proc.stdout.readline(), 30)).decode().split()
        assert line[:2] == ["UNSEENET-API", "1"] and line[2].startswith("http://127.0.0.1:")
        async with aiohttp.ClientSession() as http:
            async with http.get(line[2] + "api/state",
                                headers={srv.TOKEN_HEADER: line[3]}) as r:
                state = await r.json()
        assert state["service"] and state["unlocked"]
    finally:
        proc.terminate()
        await proc.wait()
