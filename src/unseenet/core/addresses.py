"""`unseenet:` addresses (UN-RFC 0031 section 3.4.1): one form for everything in the network.

    unseenet:<fingerprint>                  an identity
    unseenet:<group-id>                     a group (also a feed, a site, a personal group)
    unseenet:<group-id>?m=<message-id>      a post or chat line in that group
    unseenet:<group-id>?p=<path>            a page of a site (UN-RFC 0035)

``n=<onion address>`` may be added to any of them, a node that carries it, as a hint.
``parse`` also reads the older forms (``unseenet:join?g=...``, ``unseenet:<fp>/<path>``);
``format`` writes only the current one. Every client reads and writes addresses here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, quote

from .groups import split_group_id
from .pages import valid_path

SCHEME = "unseenet:"
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
    if not text.lower().startswith(SCHEME):
        raise AddressError("an address starts with unseenet:")
    rest = text[len(SCHEME):]
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
