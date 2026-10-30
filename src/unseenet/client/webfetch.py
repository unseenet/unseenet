"""Fetching a web page or picture over Tor, for a link card (UN-RFC 0059 section 7.2).

The only place the client reaches the web, and only on the poster's side, for a link
they are about to share. Always through Tor (names resolved by Tor, never locally),
``.onion`` addresses included; a plain HTTP/1.1 GET with no cookies, no referrer, no
JavaScript and no stored state; at most ``REDIRECTS`` redirects, each checked against
``cards.forbidden_host``; the answer cut at a limit; the whole fetch bounded in time by
the caller. Nothing here keeps anything.

``fetch`` raises ``FetchError`` with a short sentence for the user.
"""

from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from python_socks import ProxyError, ProxyTimeoutError
from python_socks.async_.asyncio import Proxy

from ..core import cards
from ..core.tor import Socks, _proxy_url

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"
PAGE_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"
PICTURE_ACCEPT = "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8"


class FetchError(Exception):
    """A page or picture that could not be fetched; the text is for the user."""


@dataclass
class Fetched:
    url: str                 # after redirects
    status: int
    content_type: str
    octets: bytes
    cut: bool = False        # longer than the limit, cut there


async def fetch(url: str, socks: int | Socks, *, limit: int, accept: str = PAGE_ACCEPT,
                language: str = "en") -> Fetched:
    """GET ``url`` over Tor, following at most ``cards.REDIRECTS`` redirects, reading at
    most ``limit`` octets of the answer. ``FetchError`` for anything but a 200."""
    for _ in range(cards.REDIRECTS + 1):
        parts = urlsplit(url)
        scheme, host = parts.scheme.lower(), parts.hostname or ""
        if scheme not in ("http", "https") or not host:
            raise FetchError("only http and https links get a card")
        if cards.forbidden_host(host):
            raise FetchError("that address is on a local network - no card")
        got = await _get(scheme, host, parts.port or (443 if scheme == "https" else 80),
                         (parts.path or "/") + (f"?{parts.query}" if parts.query else ""),
                         socks, limit, accept, language)
        if got.status in (301, 302, 303, 307, 308):
            where = got.content_type                 # _get puts Location there for redirects
            if not where:
                raise FetchError("the page sent a redirect to nowhere")
            url = urljoin(url, where)
            continue
        if got.status != 200:
            raise FetchError(f"the page answered {got.status}")
        got.url = url
        return got
    raise FetchError("too many redirects")


async def _get(scheme, host, port, target, socks, limit, accept, language) -> Fetched:
    proxy = Proxy.from_url(_proxy_url(socks, host), rdns=True)
    try:
        sock = await proxy.connect(dest_host=host, dest_port=int(port))
    except (ProxyError, ProxyTimeoutError, OSError) as exc:
        raise FetchError(f"Tor could not reach {host}") from exc
    kw = {}
    if scheme == "https":
        kw = {"ssl": ssl.create_default_context(), "server_hostname": host}
    try:
        reader, writer = await asyncio.open_connection(sock=sock, **kw)
    except (ssl.SSLError, OSError) as exc:
        sock.close()
        raise FetchError(f"no secure connection to {host}") from exc
    hostline = host if port in (80, 443) else f"{host}:{port}"
    request = (f"GET {target} HTTP/1.1\r\nHost: {hostline}\r\nUser-Agent: {USER_AGENT}\r\n"
               f"Accept: {accept}\r\nAccept-Language: {language},en;q=0.5\r\n"
               "Accept-Encoding: identity\r\nConnection: close\r\n\r\n")
    try:
        writer.write(request.encode("latin-1", "replace"))
        await writer.drain()
        status, headers = await _head(reader)
        if status in (301, 302, 303, 307, 308):
            return Fetched("", status, headers.get("location", ""), b"")
        body, cut = await _body(reader, headers, limit)
        return Fetched("", status, headers.get("content-type", ""), body, cut)
    except (OSError, asyncio.IncompleteReadError, ValueError) as exc:
        raise FetchError(f"{host} broke off the answer") from exc
    finally:
        writer.close()


async def _head(reader) -> tuple[int, dict]:
    line = await reader.readline()
    parts = line.decode("latin-1").split()
    if len(parts) < 2 or not parts[0].startswith("HTTP/") or not parts[1].isdigit():
        raise ValueError("not an HTTP answer")
    status, headers = int(parts[1]), {}
    for _ in range(200):
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        name, _, value = line.decode("latin-1").partition(":")
        headers.setdefault(name.strip().lower(), value.strip())
    return status, headers


async def _body(reader, headers: dict, limit: int) -> tuple[bytes, bool]:
    out = bytearray()
    if "chunked" in headers.get("transfer-encoding", "").lower():
        while len(out) < limit:
            size_line = await reader.readline()
            try:
                size = int(size_line.split(b";")[0].strip() or b"0", 16)
            except ValueError:
                break
            if size == 0:
                break
            chunk = await reader.readexactly(min(size, limit - len(out) + 1))
            out += chunk
            if len(chunk) < size:
                break
            await reader.readline()                    # the CRLF after the chunk
        return bytes(out[:limit]), len(out) > limit
    length = headers.get("content-length", "")
    want = min(int(length), limit + 1) if length.isdigit() else limit + 1
    while len(out) < want:
        chunk = await reader.read(min(65536, want - len(out)))
        if not chunk:
            break
        out += chunk
    return bytes(out[:limit]), len(out) > limit
