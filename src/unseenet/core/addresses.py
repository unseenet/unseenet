"""`unseenet:` addresses (UN-RFC 0031 section 3.4.1): one form for everything in the network.

    unseenet:<fingerprint>                  an identity
    unseenet:<group-id>                     a group (also a feed, a site, a personal group)
    unseenet:<group-id>?m=<message-id>      a post or chat line in that group
    unseenet:<group-id>?p=<path>            a page of a site (UN-RFC 0035)

``n=<onion address>`` may be added to any of them, a node that carries it, as a hint.
``parse`` also reads the older forms (``unseenet:join?g=...``, ``unseenet:<fp>/<path>``),
``web+unseenet:<...>`` (the scheme a browser may register) and the web form
``https://<any host>/a/<...>`` - the same address with the scheme moved into a path, on
any web entrance (section 3.4.1). The host is only a hint and is never trusted: the
address is opened in the network, over Tor. ``format_address`` writes only the current
form, ``web_address`` the web form. Every client reads and writes addresses here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, quote

from .groups import split_group_id
from .pages import valid_path

SCHEME = "unseenet:"
WEB_SCHEME = "web+unseenet:"          # read as unseenet:, never written (section 3.4.1)
WEB_PATH = "/a/"                      # the web form: https://<host>/a/<what follows unseenet:>
_WEB = re.compile(r"^https?://[^/\s?#]+/a/(?P<rest>[^\s#]+)$", re.IGNORECASE)
_HOST = re.compile(r"^[A-Za-z0-9.\-\[\]:]+$")
_FP = re.compile(r"^[a-z2-7]{16}$")
_ONION = re.compile(r"^[a-z2-7]{56}\.onion(:\d{1,5})?$")


class AddressError(ValueError):
    """Not an ``unseenet:`` address this client can read."""


@dataclass(frozen=True)
class Address:
    """What an address names. ``kind`` is ``identity``, ``group``, ``post`` or ``page``;
    ``fingerprint`` is set for an identity, ``group_id`` for the others, with
    ``message_id`` (with its angle brackets) for a post and ``path`` for a page.
    ``nodes`` are the ``n=`` hints, which a client asks about before using."""
    kind: str
    fingerprint: str | None = None
    group_id: str | None = None
    message_id: str | None = None
    path: str | None = None
    nodes: tuple[str, ...] = field(default=())

    def __str__(self) -> str:
        return format_address(self)


def _value(text: str) -> str:
    return quote(text, safe="@/")


def format_address(a: Address) -> str:
    """The address in the current form (UN-RFC 0031 section 3.4.1)."""
    if a.kind == "identity":
        head, params = a.fingerprint, []
    else:
        head, params = a.group_id, []
        if a.kind == "post":
            params.append(("m", a.message_id.strip("<>")))
        elif a.kind == "page":
            params.append(("p", a.path))
    params += [("n", n) for n in a.nodes]
    return SCHEME + head + ("?" + "&".join(f"{k}={_value(v)}" for k, v in params) if params else "")


def web_address(a: "Address | str", host: str | None = None) -> str:
    """The web form of an address, ``https://<host>/a/...``, on ``host`` - by default the
    first web entrance the client came with (UN-RFC 0043 section 8.1). ``n=`` hints are
    left out: they help nobody who reads the address on the web (section 3.4.1).
    ``AddressError`` when there is no host to write it on."""
    if isinstance(a, str):
        a = parse(a)
    host = (host or default_web_host() or "").strip()
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE).rstrip("/")
    if not host or not _HOST.match(host):
        raise AddressError("no web entrance to write the address on")
    plain = Address(a.kind, fingerprint=a.fingerprint, group_id=a.group_id,
                    message_id=a.message_id, path=a.path)
    return f"https://{host}{WEB_PATH}" + format_address(plain)[len(SCHEME):]


def default_web_host() -> str | None:
    """The host of the first listed web entrance with an open-web address, or None."""
    from ..known_nodes import builtin_entrances
    for e in builtin_entrances():
        if e["url"]:
            return re.sub(r"^https://", "", e["url"]).rstrip("/")
    return None


def is_web_form(text: str) -> bool:
    """Whether ``text`` is the web form of an address (on any host)."""
    return bool(_WEB.match(text.strip()))


def identity_address(fingerprint: str, nodes=()) -> str:
    return format_address(Address("identity", fingerprint=fingerprint, nodes=tuple(nodes)))


def group_address(group_id: str, nodes=()) -> str:
    return format_address(Address("group", group_id=group_id, nodes=tuple(nodes)))


def post_address(group_id: str, message_id: str, nodes=()) -> str:
    return format_address(Address("post", group_id=group_id, message_id=message_id,
                                  nodes=tuple(nodes)))


def page_address(group_id: str, path: str, nodes=()) -> str:
    return format_address(Address("page", group_id=group_id, path=path, nodes=tuple(nodes)))


def parse(text: str) -> Address:
    """An address read: the current form, or one of the older forms (read as their
    current meaning). Unknown parameters are ignored. ``AddressError`` otherwise."""
    text = text.strip()
    web = _WEB.match(text)
    if web:                                              # https://<any host>/a/<...>
        rest = web.group("rest")
    elif text.lower().startswith(WEB_SCHEME):            # web+unseenet: is unseenet:
        rest = text[len(WEB_SCHEME):]
    elif text.lower().startswith(SCHEME):
        rest = text[len(SCHEME):]
    else:
        raise AddressError("an address starts with unseenet:, or is its web form "
                           "https://<entrance>/a/...")
    head, _, query = rest.partition("?")
    params = dict(parse_qsl(query, keep_blank_values=True))
    nodes = tuple(v for k, v in parse_qsl(query) if k == "n" and _ONION.match(v.lower()))
    if head == "join":                                   # older: unseenet:join?g=...
        head = params.get("g", "")
        if not head:
            raise AddressError("an invitation without a group")
    elif "/" in head and "@" not in head:               # older: unseenet:<fp>/<path>
        fp, _, path = head.partition("/")
        head, params = f"site@{fp}", {**params, "p": path}
    if _FP.match(head):
        return Address("identity", fingerprint=head, nodes=nodes)
    try:
        split_group_id(head)
    except ValueError as exc:
        raise AddressError(f"{head!r} is neither a fingerprint nor a Group ID") from exc
    if params.get("m"):
        mid = params["m"].strip("<>")
        if not mid or " " in mid or "@" not in mid:
            raise AddressError("m is a Message-ID")
        return Address("post", group_id=head, message_id=f"<{mid}>", nodes=nodes)
    if params.get("p"):
        if not valid_path(params["p"]):
            raise AddressError("p is a page path")
        return Address("page", group_id=head, path=params["p"], nodes=nodes)
    return Address("group", group_id=head, nodes=nodes)
