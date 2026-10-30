"""Link cards (UN-RFC 0059): a preview of a linked page, carried in the post.

The poster's client fetches the page once, over Tor, and the card travels in the signed
article as a ``Link-Card`` header: the URL, a title, a description, the site's own name,
a small icon inline (section 5) and the blob ID of a picture that is an ordinary
attachment (section 6). Readers never fetch anything (UN-RFC 0031 section 3.1).

Belongs here, with no network and no Pillow: writing and reading the header
(``header_value``, ``parse``), the checks a reader makes (``check``: the URL is in the
text, the limits, the icon is a small PNG, section 4.2 and 5), reading a page's
``<head>`` in the order of section 7.3 (``read_head``), the domain as it is shown
(``domain``, section 2), which URLs a text links to (``urls_in``) and which hosts are
never fetched (``forbidden_host``, section 7.2).

Not here: fetching (``client.webfetch``), re-encoding pictures (``client.media``),
making and posting a card (``client.session.cards``).
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import format_datetime, parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from .encoding import b64, b64decode

HEADER = "Link-Card"

MAX_URL = 2048            # octets of the URL before encoding (section 4)
MAX_TITLE = 200           # characters
MAX_DESC = 300
MAX_SITE = 60
ICON_PX = 32              # the icon: a square PNG of at most 32 x 32 pixels (section 5)
ICON_OCTETS = 2048        # ... and at most 2048 octets
PICTURE_PX = 600          # the picture's long side (section 6)
PICTURE_OCTETS = 64 * 1024    # what a picture aims at, not a limit
HTML_OCTETS = 512 * 1024      # what is read of a page (section 7.2)
FILE_OCTETS = 5 * 1024 * 1024  # a picture or icon before re-encoding
REDIRECTS = 5
FETCH_SECONDS = 20.0

_PNG = b"\x89PNG\r\n\x1a\n"
_URL = re.compile(r"\bhttps?://[^\s<>\"'`]+", re.IGNORECASE)
_TRAILING = ".,;:!?)]}*_~'\""


@dataclass
class Card:
    """A link card as a reader shows it, or as the poster's client made it.

    ``icon`` is the PNG octets, ``image`` the blob ID of the picture (an attachment of
    the same article), ``made`` when the page was fetched."""
    url: str
    title: str
    desc: str = ""
    site: str = ""
    icon: bytes | None = field(default=None, repr=False)
    image: str | None = None
    made: datetime | None = None

    @property
    def domain(self) -> str:
        return domain(self.url)[0]

    def to_dict(self) -> dict:
        """As plain JSON-safe data (the icon in standard base64, ready for a ``data:``
        URL; the domain as shown)."""
        import base64
        shown, odd = domain(self.url)
        return {"url": self.url, "domain": shown, "domain_confusable": odd,
                "title": self.title, "desc": self.desc, "site": self.site,
                "icon": base64.b64encode(self.icon).decode() if self.icon else None,
                "image": self.image,
                "made": self.made.isoformat() if self.made else None}


# --- text --------------------------------------------------------------------------
def clean_text(text: str) -> str:
    """Plain text on one line: control characters and line breaks become spaces, runs of
    white space one space (section 4)."""
    out = "".join(" " if unicodedata.category(c)[0] == "C" or c in "  " else c
                  for c in text or "")
    return " ".join(out.split())


def cut(text: str, limit: int) -> str:
    """At most ``limit`` characters, cut on a word boundary with ``…`` when too long."""
    text = clean_text(text)
    if len(text) <= limit:
        return text
    head = text[:limit - 1]
    space = head.rfind(" ")
    if space > limit // 2:
        head = head[:space]
    return head.rstrip(" ,.;:-–—|") + "…"


# --- the header (section 4) -----------------------------------------------------------
def header_value(card: Card) -> str:
    """The ``Link-Card`` header's value for a card (on one line)."""
    parts = [f"url={b64(card.url.encode())}",
             f"title={b64(cut(card.title, MAX_TITLE).encode())}"]
    if card.desc:
        parts.append(f"desc={b64(cut(card.desc, MAX_DESC).encode())}")
    if card.site:
        parts.append(f"site={b64(cut(card.site, MAX_SITE).encode())}")
    if card.icon:
        parts.append(f"icon={b64(card.icon)}")
    if card.image:
        parts.append(f"image={card.image}")
    if card.made:
        parts.append(f"made={format_datetime(card.made)}")
    return "; ".join(parts)


def parse(value: str | None) -> Card | None:
    """The card a header value describes, decoded but not yet checked; None when it
    cannot be read (a missing or undecodable ``url`` or ``title``)."""
    if not value:
        return None
    params: dict[str, str] = {}
    for part in value.split(";"):
        key, eq, val = part.strip().partition("=")
        if eq and key and key not in params:
            params[key.strip().lower()] = val.strip()

    def text(name: str) -> str:
        try:
            return b64decode(params[name]).decode("utf-8", "replace") if params.get(name) else ""
        except ValueError:
            return ""
    try:
        url = b64decode(params.get("url", "")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    icon = None
    if params.get("icon"):
        try:
            icon = b64decode(params["icon"])
        except ValueError:
            icon = None
    made = None
    if params.get("made"):
        try:
            made = parsedate_to_datetime(params["made"])
        except (TypeError, ValueError, IndexError):
            made = None
    return Card(url=url, title=clean_text(text("title")), desc=clean_text(text("desc")),
                site=clean_text(text("site")), icon=icon,
                image=params.get("image") or None, made=made)


def check(value: str | None, body: str, blob_ids=()) -> Card | None:
    """The card of an article as a reader may show it, or None (section 4.2): the URL is
    ``http`` or ``https``, not an Unseenet address, at most 2048 octets, and is linked in
    ``body``; there is a title; ``image`` names one of the article's attachments
    (``blob_ids``, else it is dropped as absent). An icon that is not a square PNG of at
    most 32 pixels and 2048 octets is dropped (section 5). Texts are cut to the limits."""
    card = parse(value)
    if card is None or not card.title:
        return None
    if len(card.url.encode()) > MAX_URL or not _is_web(card.url):
        return None
    from .addresses import is_web_form
    if is_web_form(card.url):
        return None                                  # section 4.3: reader-made cards
    if not any(same_url(card.url, u) for u in urls_in(body, quoted=True)):
        return None
    if card.image and card.image not in set(blob_ids):
        return None
    if card.icon is not None and not icon_ok(card.icon):
        card.icon = None
    card.title = cut(card.title, MAX_TITLE)
    card.desc = cut(card.desc, MAX_DESC)
    card.site = cut(card.site, MAX_SITE)
    return card


def icon_ok(octets: bytes) -> bool:
    """A PNG whose header says square and at most 32 pixels, within 2048 octets. Readers
    decode it as any picture (UN-RFC 0027 section 9.2) before showing it."""
    if len(octets) > ICON_OCTETS or not octets.startswith(_PNG) or octets[12:16] != b"IHDR":
        return False
    w, h = int.from_bytes(octets[16:20], "big"), int.from_bytes(octets[20:24], "big")
    return 0 < w == h <= ICON_PX


# --- URLs -------------------------------------------------------------------------------
def _is_web(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)


def urls_in(text: str, *, quoted: bool = False) -> list[str]:
    """The ``http`` and ``https`` URLs in a text, in order, each once - trailing
    punctuation taken off. Lines quoted with ``>`` are left out unless ``quoted``
    (section 7.1: never fetch for a quote)."""
    out: list[str] = []
    for line in (text or "").splitlines():
        if not quoted and line.lstrip().startswith(">"):
            continue
        for m in _URL.finditer(line):
            url = m.group(0)
            while url and url[-1] in _TRAILING:
                if url[-1] == ")" and url.count("(") >= url.count(")"):
                    break
                url = url[:-1]
            if _is_web(url) and url not in out:
                out.append(url)
    return out


def same_url(a: str, b: str) -> bool:
    """The same link, a trailing ``/`` and the fragment aside (section 4.2)."""
    return _norm(a) == _norm(b)


def _norm(url: str) -> str:
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url
    path = p.path.rstrip("/")
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def first_url(text: str) -> str | None:
    """The URL a card is made for by default (section 7.1): the first web link in the
    text that is not quoted and not an Unseenet address."""
    from .addresses import is_web_form
    for url in urls_in(text):
        if not is_web_form(url):
            return url
    return None


# --- the domain (section 2) -----------------------------------------------------------
_CONFUSABLE_SCRIPTS = ("CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE")


def domain(url: str) -> tuple[str, bool]:
    """The host of a URL as shown: without ``www.``, internationalised names decoded,
    and whether it may be mistaken for another (a label that mixes Latin with Cyrillic,
    Greek and the like, or one written wholly in such letters under a Latin TLD)."""
    try:
        host = (urlsplit(url).hostname or "").rstrip(".")
    except ValueError:
        return "", False
    labels = []
    for label in host.split("."):
        if label.startswith("xn--"):
            try:
                label = label.encode("ascii").decode("idna")
            except UnicodeError:
                pass
        labels.append(label)
    if len(labels) > 2 and labels[0] == "www":
        labels = labels[1:]
    shown = ".".join(labels)
    odd = False
    for label in labels[:-1]:
        scripts = set()
        for ch in label:
            if ch.isalpha():
                name = unicodedata.name(ch, "")
                scripts.add(next((s for s in _CONFUSABLE_SCRIPTS if name.startswith(s)),
                                 "LATIN" if name.startswith("LATIN") else "OTHER"))
        if "LATIN" in scripts and len(scripts) > 1:
            odd = True
        if scripts and scripts <= set(_CONFUSABLE_SCRIPTS) and labels[-1].isascii():
            odd = True
    return shown, odd


def forbidden_host(host: str) -> bool:
    """A host a card is never fetched from (section 7.2): this machine, the local
    network, and addresses that are not public."""
    host = (host or "").strip("[]").rstrip(".").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".lan",
                                                          ".internal", ".home.arpa")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host                       # a bare name: a local one
    return not ip.is_global


# --- reading a page (section 7.3) ------------------------------------------------------
@dataclass
class Meta:
    """What a page's ``<head>`` says about it: texts, and the addresses of its picture
    and icons (absolute)."""
    title: str = ""
    desc: str = ""
    site: str = ""
    picture: str | None = None
    icons: list[str] = field(default_factory=list)     # best first; /favicon.ico last


class _Head(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.icons: list[tuple[int, str]] = []
        self.title: str | None = None
        self._in_title = False
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "body":
            self.done = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").strip().lower()
            val = a.get("content", "").strip()
            if key and val and key not in self.meta:
                self.meta[key] = val
        elif tag == "link":
            rels = a.get("rel", "").lower().split()
            href = a.get("href", "").strip()
            if href and ("icon" in rels or "apple-touch-icon" in rels):
                self.icons.append((_icon_size(a.get("sizes", ""), rels), href))
        elif tag == "title" and self.title is None:
            self._in_title = True
            self.title = ""

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self.done = True

    def handle_data(self, data):
        if self._in_title and self.title is not None:
            self.title += data


def _icon_size(sizes: str, rels) -> int:
    best = 0
    for s in sizes.lower().split():
        w, _, h = s.partition("x")
        if w.isdigit() and h.isdigit():
            best = max(best, min(int(w), int(h)))
    if not best:
        best = 180 if "apple-touch-icon" in rels else 16     # the usual sizes
    return best


def read_head(html: str, base_url: str) -> Meta:
    """What a page says about itself, from the first source that has it (section 7.3):
    ``og:*``, ``twitter:*``, ``<title>`` / ``<meta name="description">``. Relative
    addresses are resolved against ``base_url`` (the address after redirects); an
    ``og:url`` is ignored. Icons: the largest of at most 192 pixels first, then the
    others, then ``/favicon.ico``."""
    p = _Head()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 - html.parser is lenient; anything else: what we have
        pass
    m = p.meta

    def first(*keys):
        for k in keys:
            if clean_text(m.get(k, "")):
                return clean_text(m[k])
        return ""
    site = first("og:site_name", "application-name")
    title = first("og:title", "twitter:title")
    if not title:
        title = clean_text(p.title or "")
        if site:                                     # "Title | Site" -> "Title" (7.3)
            for sep in (" | ", " - ", " – ", " — "):
                if title.endswith(sep + site):
                    title = title[: -len(sep + site)].strip()
                    break
    desc = first("og:description", "twitter:description", "description")
    pic = first("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src")
    picture = _absolute(pic, base_url) if pic else None
    sized = sorted(((s, h) for s, h in p.icons if s <= 192), key=lambda t: -t[0])
    icons = []
    for _, href in sized + [(0, h) for s, h in p.icons if s > 192]:
        url = _absolute(href, base_url)
        if url and url not in icons:
            icons.append(url)
    fav = _absolute("/favicon.ico", base_url)
    if fav and fav not in icons:
        icons.append(fav)
    return Meta(title=cut(title, MAX_TITLE), desc=cut(desc, MAX_DESC),
                site=cut(site, MAX_SITE), picture=picture, icons=icons)


def _absolute(href: str, base: str) -> str | None:
    try:
        url = urljoin(base, href.strip())
    except ValueError:
        return None
    return url if _is_web(url) else None


def charset_of(content_type: str, head: bytes) -> str:
    """The text encoding of a page: from its ``Content-Type``, else a ``<meta charset>``
    in its first octets, else UTF-8."""
    m = re.search(r"charset=[\"']?([\w.:-]+)", content_type or "", re.IGNORECASE)
    if not m:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w.:-]+)", head[:4096], re.IGNORECASE)
        if m:
            return m.group(1).decode("ascii", "ignore") or "utf-8"
        return "utf-8"
    return m.group(1)
