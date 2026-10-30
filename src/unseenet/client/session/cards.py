"""Link cards (UN-RFC 0059): making one for a post, and the setting that allows it.

Belongs here: whether this client makes cards (``link_cards``, off by default in the
bootable client, section 7.5), making a card for a URL over Tor (``make_card``: the page,
its icon and picture fetched, read and re-encoded, section 7), the URL a card is made
for by default (``card_url``), and a card as it goes with a post (``CardDraft``).
``post(card=...)`` in posting.py writes it into the article; reading.py checks the
cards of articles that are read (``Message.card``).

Not here: the header and the checks (``core.cards``), fetching (``client.webfetch``),
re-encoding (``client.media``).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from ...core import cards as cd

ICON_FETCH_OCTETS = 256 * 1024      # an icon is read in this process: kept small


@dataclass
class CardDraft:
    """A card the poster can still change before it is sent: the texts, the icon (PNG
    octets) and the picture (a ``media.Prepared``, or None), and ``note``, a sentence for
    the poster when something could not be had (no picture, the page blocks Tor)."""
    url: str
    title: str = ""
    desc: str = ""
    site: str = ""
    icon: bytes | None = field(default=None, repr=False)
    picture: object | None = field(default=None, repr=False)
    made: datetime | None = None
    note: str = ""

    def card(self, image: str | None = None) -> cd.Card:
        return cd.Card(url=self.url, title=cd.cut(self.title, cd.MAX_TITLE),
                       desc=cd.cut(self.desc, cd.MAX_DESC), site=cd.cut(self.site, cd.MAX_SITE),
                       icon=self.icon, image=image, made=self.made)

    def to_dict(self) -> dict:
        """As JSON-safe data for a front end: icon and picture in standard base64."""
        p = self.picture
        shown, odd = cd.domain(self.url)
        return {"url": self.url, "domain": shown, "domain_confusable": odd,
                "title": self.title, "desc": self.desc, "site": self.site,
                "icon": base64.b64encode(self.icon).decode() if self.icon else None,
                "picture": ({"type": p.media_type, "data": base64.b64encode(p.octets).decode(),
                             "size": len(p.octets), "dim": list(p.dim) if p.dim else None}
                            if p is not None else None),
                "made": self.made.isoformat() if self.made else None, "note": self.note}

    @classmethod
    def from_dict(cls, data: dict) -> "CardDraft":
        """A card a front end sends with a post (as ``to_dict`` gave it, perhaps changed).
        The icon and picture are checked and saved again here, whatever the front end
        sent. ``SessionError`` with a sentence for people."""
        from .. import media
        if not isinstance(data, dict):
            raise SessionError("a card is {url, title, desc, site, icon, picture}")
        url = str(data.get("url") or "").strip()
        title = cd.clean_text(str(data.get("title") or ""))
        if not url or not title:
            raise SessionError("a card needs its link and a title")

        def octets(value, what):
            if not value:
                return None
            try:
                return base64.b64decode(str(value), validate=True)
            except ValueError:
                raise SessionError(f"the card's {what} is not base64") from None
        icon = octets(data.get("icon"), "icon")
        if icon is not None and not cd.icon_ok(icon):
            try:
                icon = media.card_icon(icon)
            except ValueError:
                icon = None
        pic = data.get("picture")
        picture = None
        if isinstance(pic, dict) and pic.get("data"):
            raw = octets(pic["data"], "picture")
            try:
                picture = media.card_picture(raw)
            except ValueError as exc:
                raise SessionError(f"the card's picture: {exc}") from exc
        made = None
        if data.get("made"):
            try:
                made = datetime.fromisoformat(str(data["made"]))
            except ValueError:
                made = None
        return cls(url=url, title=title, desc=cd.clean_text(str(data.get("desc") or "")),
                   site=cd.clean_text(str(data.get("site") or "")), icon=icon,
                   picture=picture, made=made or datetime.now(timezone.utc))


class CardsMixin:
    # --- reading (section 4.2) ---
    @staticmethod
    def _take_card(msg: Message, get) -> None:
        """The card of an article read, checked as a reader must (section 4.2): set on
        ``msg.card``, and its picture's attachment marked ``"card": True`` so a client
        shows it in the card only (section 6). ``get`` reads a header (outer, or inner
        when the article was encrypted)."""
        value = get(cd.HEADER)
        if not value or not msg.readable:
            return
        card = cd.check(value, msg.body or "", [a["blob"] for a in msg.attachments])
        msg.card = card
        if card is not None and card.image:
            msg.attachments = tuple({**a, "card": True} if a["blob"] == card.image else a
                                    for a in msg.attachments)

    # --- sending (sections 4, 6) ---
    async def _card_files(self, group_id: str, card: "CardDraft | None", body: str,
                          files: list) -> tuple[list, object | None]:
        """The files of a post with a card: ``files`` and the card's picture as one more,
        unless the group takes no files - then the card goes without it (section 6).
        ``SessionError`` when the card's link is not in the text (section 4.2)."""
        if card is None:
            return files, None
        if not any(cd.same_url(card.url, u) for u in cd.urls_in(body, quoted=True)):
            raise SessionError("the card's link is not in the text")
        if not cd.clean_text(card.title):
            raise SessionError("a card needs a title")
        if card.picture is None:
            return files, None
        if not isinstance(self.manifest_data(group_id).get("attachments"), dict):
            m = await self.fetch_manifest(group_id)        # it may take files by now
            if m is not None:
                self.group_entry(group_id)["manifest"] = dict(m.raw)
        if not isinstance(self.manifest_data(group_id).get("attachments"), dict):
            return files, None
        return files + [card.picture], card.picture

    @staticmethod
    def _card_header(card: "CardDraft | None", picture, files: list, blobs: list) -> list:
        """The ``Link-Card`` header for a post, naming its picture's blob (as stored:
        for an encrypted post the ciphertext's ID), or ``[]`` without a card."""
        if card is None:
            return []
        image = None
        if picture is not None:
            for f, (bid, _) in zip(files, blobs):
                if f is picture:
                    image = bid
        return [(cd.HEADER, cd.header_value(card.card(image)))]

    # --- the setting (section 7.5) ---
    def link_cards(self) -> bool:
        """True when this client makes link cards from the web. Off by default in the
        bootable client (``UNSEENET_BOOTABLE``), on elsewhere; the user's choice wins."""
        chosen = self.data.get("link_cards")
        if isinstance(chosen, bool):
            return chosen
        return os.environ.get("UNSEENET_BOOTABLE") != "1"

    def set_link_cards(self, on: bool) -> None:
        """Make link cards from the web (True) or not (False); kept with your settings."""
        self.data["link_cards"] = bool(on)
        self.save()

    @staticmethod
    def card_url(text: str) -> str | None:
        """The URL a card is made for by default: the first web link in the text that is
        not quoted and not an Unseenet address (section 7.1)."""
        return cd.first_url(text)

    # --- making a card (section 7) ---
    async def make_card(self, url: str, *, language: str = "en") -> CardDraft:
        """A card for ``url``, made over Tor (section 7): the page's ``<head>`` read in
        the order of section 7.3, its icon and picture fetched and saved again
        (sections 5, 6, 7.4). What cannot be had is left out, with a ``note``; a page
        that cannot be read at all gives a card with no title for the poster to fill in.
        ``SessionError`` when cards are off, the link is not one, or Tor is not there."""
        from .. import webfetch
        if not self.link_cards():
            raise SessionError("link cards are turned off")
        url = (url or "").strip()
        if not url or len(url.encode()) > cd.MAX_URL:
            raise SessionError("that is not a link a card can be made for")
        from ...core.addresses import is_web_form
        if is_web_form(url):
            raise SessionError("Unseenet addresses get their card from the network")
        socks = await self._ensure_tor(lambda *a, **k: None)
        draft = CardDraft(url=url, made=datetime.now(timezone.utc))

        async def page():
            got = await webfetch.fetch(url, socks, limit=cd.HTML_OCTETS, language=language)
            ctype = got.content_type.split(";")[0].strip().lower()
            if ctype and ctype not in ("text/html", "application/xhtml+xml"):
                raise webfetch.FetchError("the link is not a web page")
            text = got.octets.decode(cd.charset_of(got.content_type, got.octets), "replace")
            return cd.read_head(text, got.url)
        try:
            meta = await asyncio.wait_for(page(), cd.FETCH_SECONDS)
        except (webfetch.FetchError, LookupError) as exc:
            draft.note = f"No card from the page: {exc}. You can write a title yourself."
            return draft
        except asyncio.TimeoutError:
            draft.note = ("The page did not answer over Tor in time. You can write a "
                          "title yourself.")
            return draft
        draft.title, draft.desc, draft.site = meta.title, meta.desc, meta.site
        icon, picture = await asyncio.gather(self._card_icon(meta.icons, socks),
                                             self._card_picture(meta.picture, socks))
        draft.icon, draft.picture = icon, picture
        if not draft.title:
            draft.note = "The page gives no title. You can write one yourself."
        elif meta.picture and picture is None:
            draft.note = "The page's picture could not be had - the card goes without one."
        return draft

    async def _card_icon(self, urls, socks) -> bytes | None:
        """The first of the page's icons that can be fetched and made into a card icon."""
        from .. import media, webfetch
        for url in list(urls)[:4]:
            try:
                got = await asyncio.wait_for(
                    webfetch.fetch(url, socks, limit=ICON_FETCH_OCTETS,
                                   accept=webfetch.PICTURE_ACCEPT), cd.FETCH_SECONDS)
            except (webfetch.FetchError, asyncio.TimeoutError):
                continue
            if got.cut or got.octets.lstrip()[:5].lower() in (b"<svg ", b"<?xml"):
                continue                               # too large, or SVG (section 7.4)
            try:
                return await asyncio.to_thread(media.card_icon, got.octets)
            except ValueError:
                continue
        return None

    async def _card_picture(self, url, socks):
        """The page's picture, decoded in the separate decoding process (UN-RFC 0027
        section 9.2) and saved again small (section 6); None when it cannot be had."""
        from .. import decode, media, webfetch
        if not url:
            return None
        try:
            got = await asyncio.wait_for(
                webfetch.fetch(url, socks, limit=cd.FILE_OCTETS, accept=webfetch.PICTURE_ACCEPT),
                cd.FETCH_SECONDS)
        except (webfetch.FetchError, asyncio.TimeoutError):
            return None
        if got.cut:
            return None
        try:
            clean = await decode.picture_async(got.octets)
            return await asyncio.to_thread(media.card_picture, clean.octets)
        except (decode.DecodeError, ValueError):
            return None
