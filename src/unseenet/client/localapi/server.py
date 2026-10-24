"""The local client API over HTTP and a WebSocket (UN-RFC 0046).

Needs aiohttp: ``pip install unseenet[api]``.

Security (UN-RFC 0046 section 3):

- it listens on 127.0.0.1 only, on a random port;
- every request carries a random token, made at each start, that only the
  front end knows (header ``X-Unseenet-Token``, or for the WebSocket the
  subprotocol ``unseenet-token.<token>``), compared in constant time;
- ``Host`` must be our own address (stops DNS rebinding) and ``Origin``, when
  sent, our own origin; no CORS header is ever sent;
- pages are served with a strict Content-Security-Policy;
- keys, group keys and the passphrase never go out. Nothing is logged.

A front end that serves its own page passes ``page`` (a folder with
``index.html`` and what it loads, served under ``/static/``) and its own
routes as ``extensions`` (under ``/x/<name>/``).
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Callable

from aiohttp import WSMsgType, web

from ..session import SessionError
from .api import NETWORK_ERRORS, LocalAPI, Locked, NotFound, Status

TOKEN_HEADER = "X-Unseenet-Token"
MAX_REQUEST = 12 * 1024 * 1024     # a post with up to 8 MiB of files, as base64 (section 4.10)
TOKEN_PROTOCOL = "unseenet-token."
ANNOUNCE = "UNSEENET-API 1"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
STATIC_TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
                ".png": "image/png", ".woff2": "font/woff2", ".json": "application/json"}
API_KEY = web.AppKey("api", LocalAPI)
CONF = web.AppKey("conf", dict)


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status,
                             dumps=lambda o: json.dumps(o, ensure_ascii=False))


def _error(text: str, status: int = 400) -> web.Response:
    return _json({"error": text}, status)


def _harden(response: web.StreamResponse) -> None:
    h = response.headers
    h["Content-Security-Policy"] = CSP
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "no-referrer"
    h["Cache-Control"] = "no-store"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"


def _token_of(request: web.Request) -> str:
    if request.path == "/api/events":
        offered = request.headers.get("Sec-WebSocket-Protocol", "")
        return next((p.strip()[len(TOKEN_PROTOCOL):] for p in offered.split(",")
                     if p.strip().startswith(TOKEN_PROTOCOL)), "")
    return request.headers.get(TOKEN_HEADER, "")


@web.middleware
async def guard(request: web.Request, handler):
    conf = request.app[CONF]
    port = conf["port"]
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    if request.host not in hosts:
        return _error("wrong host", 403)
    origin = request.headers.get("Origin")
    if origin is not None and origin not in {f"http://{h}" for h in hosts}:
        return _error("wrong origin", 403)
    protected = request.path.startswith(("/api/", "/x/"))
    if protected and not hmac.compare_digest(_token_of(request).encode(), conf["token"].encode()):
        return _error("no token", 401)
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = _error(exc.text or exc.reason, exc.status)
    except Locked as exc:
        response = _error(str(exc), 409)
    except NotFound as exc:
        response = _error(str(exc), 404)
    except Status as exc:
        response = _json({"error": str(exc), **exc.fields}, status=exc.status)
    except SessionError as exc:
        response = _error(str(exc))
    except NETWORK_ERRORS as exc:                    # includes ValueError: a bad key or name
        response = _error(str(exc) or "not valid", 502 if isinstance(exc, OSError) else 400)
    except (KeyError, TypeError) as exc:
        response = _error(str(exc) or "not valid")
    _harden(response)
    return response


def _api(request: web.Request) -> LocalAPI:
    return request.app[API_KEY]


async def _body(request: web.Request) -> dict:
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="expected JSON")
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="expected an object")
    return data


def _gid(request: web.Request) -> str:
    return request.match_info["gid"]


# --- handlers, in the order of UN-RFC 0046 section 4 -------------------------------
async def state(request):
    return _json(_api(request).state())


async def about(request):
    return _json(_api(request).about())


async def emoji(request):
    return _json(_api(request).emoji())


async def unlock(request):
    data = await _body(request)
    return _json(await _api(request).unlock(str(data.get("passphrase", ""))))


async def setup(request):
    data = await _body(request)
    return _json(await _api(request).setup(str(data.get("display", "")), str(data.get("node", ""))))


async def groups(request):
    return _json(_api(request).groups())


async def group(request):
    return _json(_api(request).group(_gid(request)))


async def read(request):
    data = await _body(request)
    return _json(_api(request).mark_read(_gid(request), list(data.get("ids", []))))


async def view(request):
    data = await _body(request)
    return _json(_api(request).set_view(_gid(request), data.get("view")))


async def subscribe(request):
    data = await _body(request)
    return _json(_api(request).subscribe(str(data.get("id", "")), bool(data.get("on", True))))


async def browse(request):
    return _json(await _api(request).browse(request.query.get("pattern", "*")))


async def refresh(request):
    return _json(_api(request).refresh())


async def ripening(request):
    data = await _body(request)
    paused = data.get("paused")
    if not isinstance(paused, bool):
        raise web.HTTPBadRequest(text='expected {"paused": true or false}')
    return _json(await _api(request).set_ripening_paused(paused))


async def known_nodes(request):
    return _json(_api(request).known_nodes())


async def group_ref(request):
    return _json(await _api(request).group_ref(request.query.get("ref", "")))


async def post(request):
    return _json(_api(request).post(_gid(request), await _body(request)))


async def private(request):
    return _json(_api(request).private(await _body(request)))


async def files(request):
    q = request.query
    return _json(await _api(request).file(_gid(request), request.match_info["blob"],
                                          save=q.get("save") in ("1", "true"),
                                          asked=q.get("asked") in ("1", "true")))


async def edit(request):
    return _json(_api(request).edit(_gid(request), await _body(request)))


async def pin(request):
    return _json(await _api(request).pin(_gid(request), await _body(request)))


async def withdraw(request):
    data = await _body(request)
    return _json(await _api(request).withdraw(_gid(request), str(data.get("id", ""))))


async def mentioned(request):
    data = await _body(request)
    return _json(_api(request).mentioned(_gid(request), str(data.get("subject", "")),
                                         str(data.get("body", ""))))


async def contacts(request):
    return _json(_api(request).contact(await _body(request)))


async def ignore(request):
    if request.method == "POST":
        return _json(_api(request).ignore(await _body(request)))
    return _json(_api(request).ignored())


async def report(request):
    if request.method == "GET":
        return _json(await _api(request).report_targets(_gid(request), request.query.get("id", "")))
    return _json(await _api(request).report(_gid(request), await _body(request)))


async def block(request):
    return _json(await _api(request).block(_gid(request), await _body(request)))


async def create(request):
    return _json(await _api(request).create_group(await _body(request)))


async def group_settings(request):
    return _json(await _api(request).group_settings(_gid(request), await _body(request)))


async def remove_group(request):
    return _json(await _api(request).remove_group(_gid(request), await _body(request)))


async def invite(request):
    return _json(await _api(request).invite(_gid(request), await _body(request)))


async def remove_member(request):
    return _json(await _api(request).remove_member(_gid(request), await _body(request)))


async def role(request):
    return _json(await _api(request).role(_gid(request), await _body(request)))


async def ban(request):
    return _json(await _api(request).ban(_gid(request), await _body(request)))


async def moderation(request):
    if request.method == "POST":
        return _json(await _api(request).moderate(await _body(request)))
    return _json(await _api(request).moderation())


async def profile(request):
    if request.method == "POST":
        try:
            data = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise web.HTTPBadRequest(text="expected JSON")
        return _json(await _api(request).publish_profile(data))
    return _json(await _api(request).profile(request.query.get("key")))


async def pictures(request):
    keys = [k for k in request.query.get("keys", "").split(",") if k.strip()]
    return _json(await _api(request).pictures(keys))


async def profile_picture(request):
    return _json(await _api(request).publish_picture(await _body(request)))


async def profile_hide(request):
    data = await _body(request)
    return _json(_api(request).hide_profile(str(data.get("key", "")), bool(data.get("hidden", True))))


async def passphrase(request):
    data = await _body(request)
    try:
        return _json(await _api(request).change_passphrase(str(data.get("old", "")),
                                                           str(data.get("new", ""))))
    except OSError as exc:                     # the old passphrase still works: the core keeps it
        return _json({"error": f"Could not save the vault: {exc}"}, status=500)


async def names(request):
    if request.method == "POST":
        return _json(await _api(request).name_action(await _body(request)))
    return _json(await _api(request).names())


async def settings(request):
    if request.method == "POST":
        return _json(_api(request).set_settings(await _body(request)))
    return _json(_api(request).settings())


async def articles(request):
    return _json(_api(request).article(await _body(request)))


async def manifest(request):
    return _json(await _api(request).manifest(_gid(request), await _body(request)))


async def events(request):
    api = _api(request)
    offered = [p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",")]
    ws = web.WebSocketResponse(protocols=[p for p in offered if p == "unseenet"], heartbeat=30)
    _harden(ws)
    await ws.prepare(request)
    q = api.listen()

    async def pump():
        while True:
            await ws.send_str(json.dumps(await q.get(), ensure_ascii=False))

    sender = asyncio.create_task(pump())
    try:
        async for msg in ws:
            if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        sender.cancel()
        api.unlisten(q)
    return ws


ROUTES = [
    ("GET", "/api/state", state), ("GET", "/api/about", about),
    ("GET", "/api/emoji", emoji),
    ("POST", "/api/unlock", unlock), ("POST", "/api/setup", setup),
    ("GET", "/api/groups", groups), ("POST", "/api/groups", create),
    ("GET", "/api/groups/{gid}", group),
    ("POST", "/api/groups/{gid}/read", read), ("POST", "/api/groups/{gid}/view", view),
    ("POST", "/api/subscribe", subscribe), ("GET", "/api/browse", browse),
    ("POST", "/api/refresh", refresh), ("POST", "/api/ripening", ripening),
    ("GET", "/api/known-nodes", known_nodes),
    ("GET", "/api/group-ref", group_ref),
    ("POST", "/api/groups/{gid}/post", post), ("POST", "/api/private", private),
    ("GET", "/api/groups/{gid}/files/{blob}", files),
    ("POST", "/api/groups/{gid}/edit", edit), ("POST", "/api/groups/{gid}/withdraw", withdraw),
    ("POST", "/api/groups/{gid}/pin", pin),
    ("POST", "/api/groups/{gid}/mentioned", mentioned),
    ("POST", "/api/contacts", contacts),
    ("GET", "/api/ignore", ignore), ("POST", "/api/ignore", ignore),
    ("GET", "/api/groups/{gid}/report", report), ("POST", "/api/groups/{gid}/report", report),
    ("POST", "/api/groups/{gid}/block", block),
    ("POST", "/api/groups/{gid}/settings", group_settings),
    ("POST", "/api/groups/{gid}/remove", remove_group),
    ("POST", "/api/groups/{gid}/invite", invite),
    ("POST", "/api/groups/{gid}/members/remove", remove_member),
    ("POST", "/api/groups/{gid}/role", role), ("POST", "/api/groups/{gid}/ban", ban),
    ("GET", "/api/moderation", moderation), ("POST", "/api/moderation", moderation),
    ("GET", "/api/profile", profile), ("POST", "/api/profile", profile),
    ("POST", "/api/profile/hide", profile_hide), ("POST", "/api/passphrase", passphrase),
    ("GET", "/api/pictures", pictures), ("POST", "/api/profile/picture", profile_picture),
    ("GET", "/api/names", names), ("POST", "/api/names", names),
    ("GET", "/api/settings", settings), ("POST", "/api/settings", settings),
    ("POST", "/api/articles", articles), ("POST", "/api/groups/{gid}/manifest", manifest),
    ("GET", "/api/events", events),
]


def make_app(api: LocalAPI, token: str, *, page: Path | None = None,
             extensions: dict[str, Callable[[web.Application, LocalAPI], None]] | None = None,
             ) -> web.Application:
    """The API as an aiohttp application. ``page``: a folder whose ``index.html``
    is served at ``/`` and its other files under ``/static/``. ``extensions``:
    ``{name: setup}``, each ``setup(subapp, api)`` adding its own routes to a
    sub-application mounted at ``/x/<name>/`` (UN-RFC 0046 section 6)."""
    if len(token) < 32:
        raise ValueError("the token must be at least 32 characters")
    app = web.Application(middlewares=[guard], client_max_size=MAX_REQUEST)
    app[API_KEY] = api
    app[CONF] = {"port": 0, "token": token}           # port: once bound
    for method, path, handler in ROUTES:
        app.router.add_route(method, path, handler)
    if page is not None:
        _serve_page(app, Path(page))
    for name, setup_ext in (extensions or {}).items():
        sub = web.Application()
        sub[API_KEY] = api
        setup_ext(sub, api)
        app.add_subapp(f"/x/{name}/", sub)

    async def closing(app):
        await api.close()
    app.on_shutdown.append(closing)
    return app


def _serve_page(app: web.Application, folder: Path) -> None:
    async def index(request):
        return web.Response(body=(folder / "index.html").read_bytes(),
                            content_type="text/html", charset="utf-8")

    async def static(request):
        name = request.match_info["name"]
        ext = Path(name).suffix
        if "/" in name or "\\" in name or name.startswith(".") or ext not in STATIC_TYPES:
            raise web.HTTPNotFound()
        f = folder / name
        if not f.is_file():
            raise web.HTTPNotFound()
        return web.Response(body=f.read_bytes(), content_type=STATIC_TYPES[ext],
                            charset="utf-8" if ext in (".js", ".css", ".json", ".svg") else None)
    app.router.add_get("/", index)
    app.router.add_get("/static/{name}", static)


def announce_line(port: int, token: str) -> str:
    """The line that hands the address to the front end (UN-RFC 0046 section 3.1)."""
    return f"{ANNOUNCE} http://127.0.0.1:{port}/ {token}"


def write_api_file(path: Path, line: str) -> None:
    """``<vault>.api``, readable by its owner only (section 3.1)."""
    path = Path(path)
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(line + "\n")


async def serve(api: LocalAPI, *, port: int = 0, page: Path | None = None,
                extensions: dict | None = None, on_ready=None, api_file: Path | None = None,
                started: asyncio.Event | None = None, stop: asyncio.Event | None = None) -> None:
    """Run the API until ``stop`` is set (or forever). ``on_ready(port, token)``
    is called once it listens; ``api_file`` is written then and removed at the end."""
    token = secrets.token_urlsafe(32)
    app = make_app(api, token, page=page, extensions=extensions)
    runner = web.AppRunner(app, access_log=None)        # nothing about what you read is logged
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    bound = site._server.sockets[0].getsockname()[1]
    app[CONF]["port"] = bound
    if api_file is not None:
        write_api_file(api_file, announce_line(bound, token))
    if on_ready is not None:
        on_ready(bound, token)
    if started is not None:
        started.set()
    try:
        await (stop or asyncio.Event()).wait()
    finally:
        with contextlib.suppress(Exception):
            await runner.cleanup()
        if api_file is not None:
            Path(api_file).unlink(missing_ok=True)
