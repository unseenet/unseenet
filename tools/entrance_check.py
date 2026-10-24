"""Checks of a web entrance (UN-RFC 0043), for "Add my entrance" (entrance_request.py)
and the daily check of listed entrances (entrance_health.py).

An entrance is reached the way a visitor reaches it: over HTTPS at its open-web
address, and over Tor at its onion address. It must

1. answer ``/.well-known/unseenet-entrance`` (section 4.3), naming the operator
   given in the request - and, while asking, showing the request's challenge as
   ``claim`` (``ENTRANCE_CLAIM``), so whoever asked runs it;
2. serve the web client **unchanged**: every file of the version it says it
   serves (``version.json``) has the SHA-256 that a post in ``unseenet.releases``
   gives, signed by a key the project key lists (section 7.2 and 7.6); the posts
   are read from the entrance's own ``/.well-known/unseenet-releases.json`` and
   checked here, so it cannot make up a version;
3. tunnel to a known node: a WebSocket on ``/onntp`` brings the node's greeting.

Everything an entrance sends is untrusted: sizes are capped and nothing of it
is run or put on a command line.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import ssl
from dataclasses import dataclass, field
from urllib.parse import urlsplit

PROJECT_KEY = "ed25519:det5dxevwbk36eds2indrzlazyri3fq3bgdzw6kx4ems3o267sya"
RELEASES_GROUP = "unseenet.releases@ph5fc5hop5232qsz"
URL = re.compile(r"^https://[^/\s]+/?$")
ONION = re.compile(r"^[a-z2-7]{56}\.onion$")
MAX_JSON = 4 << 20
MAX_FILE = 48 << 20
TIMEOUT = 120
UA = "unseenet-entrance-check (+https://github.com/unseenet/unseenet)"


# --- a small HTTP and WebSocket client over asyncio streams --------------------------

async def _open(base: str, socks_port: int | None):
    """A stream to ``base`` (https://host[:port]/ or http://<onion>/), over Tor when
    ``socks_port`` is given (always for an onion)."""
    u = urlsplit(base)
    tls = u.scheme == "https"
    host, port = u.hostname or "", u.port or (443 if tls else 80)
    ctx = ssl.create_default_context() if tls else None
    if socks_port:
        from python_socks.async_.asyncio import Proxy
        cred = secrets.token_hex(8)                  # a circuit of its own
        proxy = Proxy.from_url(f"socks5://{cred}:{cred}@127.0.0.1:{socks_port}", rdns=True)
        sock = await asyncio.wait_for(proxy.connect(dest_host=host, dest_port=port), TIMEOUT)
        r, w = await asyncio.wait_for(asyncio.open_connection(
            sock=sock, ssl=ctx, server_hostname=host if tls else None), TIMEOUT)
    else:
        r, w = await asyncio.wait_for(asyncio.open_connection(host, port, ssl=ctx), TIMEOUT)
    return r, w, (u.netloc or host)


async def _head(reader) -> tuple[int, dict[str, str]]:
    line = (await asyncio.wait_for(reader.readline(), TIMEOUT)).decode("latin-1")
    m = re.match(r"^HTTP/1\.[01] (\d{3})", line)
    if not m:
        raise ValueError("not an HTTP answer")
    headers = {}
    while True:
        h = (await asyncio.wait_for(reader.readline(), TIMEOUT)).decode("latin-1").rstrip("\r\n")
        if not h:
            break
        k, _, v = h.partition(":")
        headers[k.strip().lower()] = v.strip()
        if len(headers) > 100:
            raise ValueError("too many headers")
    return int(m.group(1)), headers


async def http_get(base: str, path: str, socks_port: int | None = None,
                   limit: int = MAX_JSON) -> tuple[int, bytes]:
    """GET ``path`` at ``base``; (status, body), the body at most ``limit`` octets."""
    r, w, host = await _open(base, socks_port)
    try:
        w.write((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: {UA}\r\n"
                 "Accept-Encoding: identity\r\nConnection: close\r\n\r\n").encode())
        await w.drain()
        status, headers = await _head(r)
        if headers.get("transfer-encoding", "").lower() == "chunked":
            body = bytearray()
            while True:
                size = int((await r.readline()).split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    break
                body += await asyncio.wait_for(r.readexactly(size), TIMEOUT)
                await r.readline()
                if len(body) > limit:
                    raise ValueError(f"{path}: more than {limit} octets")
            return status, bytes(body)
        n = int(headers.get("content-length", "-1"))
        if n > limit:
            raise ValueError(f"{path}: more than {limit} octets")
        body = (await asyncio.wait_for(r.readexactly(n), TIMEOUT) if n >= 0
                else await asyncio.wait_for(r.read(limit + 1), TIMEOUT))
        if len(body) > limit:
            raise ValueError(f"{path}: more than {limit} octets")
        return status, body
    finally:
        w.close()


async def ws_first_message(base: str, path: str, socks_port: int | None = None) -> bytes:
    """Open a WebSocket at ``path`` and return the first message's payload."""
    r, w, host = await _open(base, socks_port)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        w.write((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: {UA}\r\n"
                 "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                 f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        await w.drain()
        status, headers = await _head(r)
        if status != 101:
            raise ValueError(f"the tunnel answered HTTP {status}, not a WebSocket")
        want = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != want:
            raise ValueError("the tunnel's WebSocket handshake is wrong")
        while True:
            b0, b1 = await asyncio.wait_for(r.readexactly(2), TIMEOUT)
            n = b1 & 0x7F
            if n == 126:
                n = int.from_bytes(await r.readexactly(2), "big")
            elif n == 127:
                n = int.from_bytes(await r.readexactly(8), "big")
            if n > 1 << 20:
                raise ValueError("a WebSocket message that large")
            mask = await r.readexactly(4) if b1 & 0x80 else None
            data = await asyncio.wait_for(r.readexactly(n), TIMEOUT)
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            op = b0 & 0x0F
            if op == 8:
                raise ValueError("the tunnel was closed: "
                                 + data[2:].decode("utf-8", "replace")[:200])
            if op in (1, 2):
                return data
    finally:
        w.close()


# --- the signed versions of the web client -------------------------------------------

def signed_releases(bundle: dict, owner: str = PROJECT_KEY,
                    group: str = RELEASES_GROUP) -> dict[str, dict[str, str]]:
    """{version: {path: sha256}} from a bundle of raw articles, as an entrance serves
    them: only posts signed by the group's owner - pinned - or a poster it lists."""
    from unseenet.core import crypto
    from unseenet.core.article import Article
    from unseenet.core.groups import Manifest
    from unseenet.nntp import strip_reader_headers
    raw = base64.b64decode(bundle.get("manifest") or "")
    art = Article.from_bytes(strip_reader_headers(raw))
    art.verify_signature()
    m = Manifest.from_article(art)
    if m.group_id != group or crypto.key_to_text(m.owner) != owner:
        raise ValueError("the list of versions is not the project's")
    out: dict[str, dict[str, str]] = {}
    for b in bundle.get("posts") or []:
        try:
            post = Article.from_bytes(strip_reader_headers(base64.b64decode(b)))
            post.verify_signature()
        except Exception:  # noqa: BLE001 - not a valid post
            continue
        if post.group != group or not m.can_post_directly(post.author_key):
            continue
        lines = post.body.splitlines()
        v = re.match(r"^Unseenet web client (\S+)\s*$", lines[0] if lines else "")
        if not v:
            continue
        files = {}
        for line in lines[1:]:
            h = re.match(r"^([0-9a-f]{64}) [ *]?(\S+)$", line)
            if h and not h.group(2).endswith(".zip") and ".." not in h.group(2) \
                    and not h.group(2).startswith("/"):
                files[h.group(2)] = h.group(1)
        if files:
            out.setdefault(v.group(1), files)
    return out


# --- the checks ----------------------------------------------------------------------

@dataclass
class Result:
    where: str
    problems: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)
    version: str = ""
    unchanged: bool | None = None     # False: files differ from the signed release

    @property
    def ok(self) -> bool:
        return not self.problems


async def check_at(base: str, *, socks_port: int | None, operator: str = "",
                   claim: str | None = None, node: str | None = None,
                   files: bool = True) -> Result:
    """Every check at one address; problems in plain sentences for the issue."""
    res = Result(base)
    try:
        st, body = await http_get(base, "/.well-known/unseenet-entrance", socks_port)
        if st != 200:
            res.problems.append(f"{base}: `/.well-known/unseenet-entrance` answered HTTP {st}.")
            return res
        res.info = json.loads(body)
        if not isinstance(res.info, dict):
            raise ValueError("not a JSON object")
    except (OSError, asyncio.TimeoutError, ValueError, ssl.SSLError) as exc:
        res.problems.append(f"Could not reach {base}: {exc}")
        return res
    if operator and res.info.get("operator") != operator:
        res.problems.append(f"{base}: it names operator `{res.info.get('operator') or '(none)'}`, "
                            "not the one in the request (`ENTRANCE_OPERATOR`).")
    if claim is not None and res.info.get("claim") != claim:
        res.problems.append(f"{base}: `/.well-known/unseenet-entrance` does not show the "
                            "challenge yet (set `ENTRANCE_CLAIM`, see below).")
    if files:
        await _check_files(base, socks_port, res)
    if node:
        try:
            greeting = await ws_first_message(base, f"/onntp?node={node}", socks_port)
            if not greeting.startswith((b"200", b"201")):
                res.problems.append(f"{base}: the tunnel to a known node gave "
                                    f"{greeting[:60]!r}, not a node's greeting.")
        except (OSError, asyncio.TimeoutError, ValueError, ssl.SSLError) as exc:
            res.problems.append(f"{base}: could not tunnel to a known node: {exc}")
    return res


async def _check_files(base: str, socks_port: int | None, res: Result) -> None:
    try:
        st, body = await http_get(base, "/version.json", socks_port)
        res.version = str(json.loads(body).get("version", "")) if st == 200 else ""
        if not res.version:
            res.problems.append(f"{base}: serves no `version.json`, so no signed version.")
            return
        st, body = await http_get(base, "/.well-known/unseenet-releases.json", socks_port)
        known = signed_releases(json.loads(body)) if st == 200 else {}
    except (OSError, asyncio.TimeoutError, ValueError, ssl.SSLError) as exc:
        res.problems.append(f"{base}: could not read its version and the signed versions: {exc}")
        return
    files = known.get(res.version)
    if files is None:
        res.problems.append(f"{base}: serves version {res.version}, which no signed post in "
                            "`unseenet.releases` names (a local build is fine for testing, "
                            "not for the list).")
        return
    for path, digest in sorted(files.items()):
        try:
            st, data = await http_get(base, "/" + path, socks_port, MAX_FILE)
        except (OSError, asyncio.TimeoutError, ValueError, ssl.SSLError) as exc:
            res.problems.append(f"{base}: could not read `{path}`: {exc}")
            return
        if st != 200 or hashlib.sha256(data).hexdigest() != digest:
            res.unchanged = False
            res.problems.append(f"{base}: `{path}` is not the file the signed version "
                                f"{res.version} names. An entrance must serve the signed "
                                "client unchanged (UN-RFC 0043 7.6).")
            return
    res.unchanged = True


def addresses(entry: dict) -> list[tuple[str, bool]]:
    """(base URL, over Tor) for an entrance's open-web and onion addresses."""
    out = []
    if entry.get("url"):
        out.append((entry["url"].rstrip("/") + "/", False))
    if entry.get("onion"):
        out.append((f"http://{entry['onion']}/", True))
    return out
