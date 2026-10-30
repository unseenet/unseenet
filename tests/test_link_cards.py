"""#792: link cards (UN-RFC 0059) - reading a page's head, the header and a reader's
checks, the icon and picture, making a card over (a stand-in for) Tor, and posting and
reading one in an open group, a closed group and a private post."""

import io
from datetime import datetime, timezone

import pytest

import unseenet.client.session as sess
from unseenet.client import media, webfetch
from unseenet.client.session import CardDraft, Session, SessionError
from unseenet.core import blobs as bl
from unseenet.core import cards as cd
from unseenet.core.article import Article
from unseenet.core.blobs import BlobStore
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}
BT = "https://www.bt.dk/krimi/ansat-i-politiet-snoed-fleggaard-nu-er-han-doemt"
AV = "https://autohuset-vestergaard.dk/"

# the heads of the two pages tried in #790, as they were (30 Oct 2026), shortened
BT_HEAD = """<!DOCTYPE html><html lang="da"><head><meta charSet="utf-8"/>
<meta property="og:url" content="https://www.bt.dk/krimi/ansat-i-politiet-snoed-fleggaard-nu-er-han-doemt"/>
<title>Ansat i politiet snød Fleggaard: Nu er han dømt | Krimi | Nyheder | B.T.</title>
<meta name="description" content="Retten i Sønderborg har idømt en mellemleder i politiet en bødestraf for bedrageri og misbrug af stilling."/>
<meta property="og:site_name" content="B.T."/><meta property="og:type" content="article"/>
<meta property="og:title" content="Ansat i politiet snød Fleggaard: Nu er han dømt"/>
<meta property="og:description" content="Retten i Sønderborg har idømt en mellemleder i politiet en bødestraf for bedrageri og misbrug af stilling."/>
<meta property="og:image" content="/brands/bt/share.jpg"/>
<meta property="twitter:card" content="summary_large_image"/>
<link rel="icon" type="image/png" sizes="32x32" href="/brands/bt/icon-32x32.png"/>
<link rel="apple-touch-icon" type="image/png" sizes="192x192" href="/brands/bt/icon-192x192.png"/>
</head><body><h1>not read</h1></body></html>"""

AV_HEAD = """<!doctype html><html><head>
<title>Autohuset Vestergaard | Bilforhandler af nye biler og brugte biler</title>
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<meta name="description" content="7 bilmærker - 11 bilhuse og altid masser af nye og brugte biler på lager. Hos os gør vi alt for at give dig den bedste bil oplevelse - kig her.">
<meta name="og:type" content="website"><meta name="og:url" content>
<meta name="og:description" content="7 bilmærker - 11 bilhuse og altid masser af nye og brugte biler på lager. Hos os gør vi alt for at give dig den bedste bil oplevelse - kig her.">
<meta name="twitter:title" content="Autohuset Vestergaard | Bilforhandler af nye biler og brugte biler">
</head><body></body></html>"""


def _png(size=(40, 40), colour=(200, 30, 40)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "PNG")
    return buf.getvalue()


def _ico() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (128, 128), (10, 90, 160, 255)).save(buf, "ICO", sizes=[(16, 16), (128, 128)])
    return buf.getvalue()


# --- reading a page (section 7.3) -------------------------------------------------------
def test_a_newspaper_page():
    m = cd.read_head(BT_HEAD, BT)
    assert m.title == "Ansat i politiet snød Fleggaard: Nu er han dømt"     # og:title wins
    assert m.desc.startswith("Retten i Sønderborg") and m.site == "B.T."
    assert m.picture == "https://www.bt.dk/brands/bt/share.jpg"            # relative, resolved
    assert m.icons == ["https://www.bt.dk/brands/bt/icon-192x192.png",
                       "https://www.bt.dk/brands/bt/icon-32x32.png",
                       "https://www.bt.dk/favicon.ico"]


def test_a_page_with_little_in_its_head():
    m = cd.read_head(AV_HEAD, AV)
    assert m.title == "Autohuset Vestergaard | Bilforhandler af nye biler og brugte biler"
    assert m.desc.startswith("7 bilmærker") and m.site == "" and m.picture is None
    assert m.icons == ["https://autohuset-vestergaard.dk/favicon.ico"]


def test_title_without_the_site_and_long_texts_cut():
    head = ('<head><title>Et emne - Avisen</title><meta property="og:site_name" content="Avisen">'
            '<meta name="description" content="' + "ord " * 200 + '"></head>')
    m = cd.read_head(head, "https://avisen.example/a")
    assert m.title == "Et emne"
    assert len(m.desc) <= cd.MAX_DESC and m.desc.endswith("…")


# --- URLs and domains -------------------------------------------------------------------
def test_urls_in_a_text():
    text = (f"Se {BT}. Og (https://example.org/x_(y))!\n> citat https://quoted.example/\n"
            "https://unseenet.net/a/dk.snak.marsvin")
    assert cd.urls_in(text) == [BT, "https://example.org/x_(y)", "https://unseenet.net/a/dk.snak.marsvin"]
    assert "https://quoted.example/" in cd.urls_in(text, quoted=True)
    assert cd.first_url("https://unseenet.net/a/dk.snak.marsvin og " + AV) == AV
    assert cd.same_url(AV, "https://autohuset-vestergaard.dk#top")


def test_the_domain_as_shown():
    assert cd.domain(BT) == ("bt.dk", False)
    assert cd.domain("https://xn--blbrgrd-fxak7p.dk/")[0] == "blåbærgrød.dk"
    assert cd.domain("https://bаnk.dk/")[1] is True          # a Cyrillic а among Latin
    assert cd.domain("https://аррӏе.com/")[1] is True   # all Cyrillic, .com


def test_hosts_never_fetched():
    for host in ("localhost", "printer.local", "10.0.0.5", "192.168.1.1", "[::1]", "nas",
                 "169.254.1.1", "router.home.arpa"):
        assert cd.forbidden_host(host), host
    for host in ("bt.dk", "93.184.216.34", "abc.onion"):
        assert not cd.forbidden_host(host), host


# --- the header and a reader's checks (sections 4, 5) ----------------------------------------
def test_header_round_trip_and_checks():
    icon = media.card_icon(_png())
    card = cd.Card(url=BT, title="Ansat i politiet snød Fleggaard", desc="Retten ...",
                   site="B.T.", icon=icon, image="blob1:abc",
                   made=datetime(2026, 10, 30, 12, 31, tzinfo=timezone.utc))
    value = cd.header_value(card)
    assert "\n" not in value
    body = f"Så blev han dømt. {BT}\n"
    got = cd.check(value, body, ["blob1:abc"])
    assert (got.url, got.title, got.site, got.icon, got.image) == (BT, card.title, "B.T.", icon, "blob1:abc")
    assert got.made == card.made and got.domain == "bt.dk"
    assert cd.check(value, "no link here\n", ["blob1:abc"]) is None        # URL not in the text
    assert cd.check(value, body, []) is None                              # picture not attached
    no_title = cd.header_value(cd.Card(url=BT, title=" "))
    assert cd.check(no_title, body) is None
    ours = cd.header_value(cd.Card(url="https://unseenet.net/a/dk.snak.marsvin", title="x"))
    assert cd.check(ours, "https://unseenet.net/a/dk.snak.marsvin") is None   # 4.3
    big = cd.header_value(cd.Card(url=BT, title="t", icon=_png((64, 64))))
    assert cd.check(big, body).icon is None                               # 5: dropped
    js = cd.header_value(cd.Card(url="javascript:alert(1)", title="t"))
    assert cd.check(js, "javascript:alert(1)") is None


def test_icon_and_picture():
    icon = media.card_icon(_ico())
    assert cd.icon_ok(icon) and len(icon) <= cd.ICON_OCTETS
    from PIL import Image
    assert Image.open(io.BytesIO(icon)).size == (32, 32)
    pic = media.card_picture(_png((1200, 630)))
    assert pic.media_type == "image/jpeg" and max(pic.dim) <= cd.PICTURE_PX
    with pytest.raises(ValueError):
        media.card_icon(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")


# --- making a card (section 7), Tor and the web stood in for ----------------------------------
@pytest.fixture
def web(monkeypatch):
    pages = {BT: ("text/html; charset=utf-8", BT_HEAD.encode()),
             AV: ("text/html", AV_HEAD.encode()),
             "https://www.bt.dk/brands/bt/share.jpg": ("image/png", _png((1200, 630))),
             "https://www.bt.dk/brands/bt/icon-192x192.png": ("image/png", _png((192, 192))),
             "https://autohuset-vestergaard.dk/favicon.ico": ("image/x-icon", _ico())}
    asked = []

    async def fetch(url, socks, *, limit, accept=webfetch.PAGE_ACCEPT, language="en"):
        asked.append(url)
        if url not in pages:
            raise webfetch.FetchError("the page answered 404")
        ctype, octets = pages[url]
        return webfetch.Fetched(url, 200, ctype, octets[:limit], len(octets) > limit)
    monkeypatch.setattr(webfetch, "fetch", fetch)
    return pages, asked


def _session(tmp_path, name="alice") -> Session:
    s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity(name, name.title())
    return s


async def test_make_a_card(web, tmp_path, monkeypatch):
    s = _session(tmp_path)

    async def tor(status):
        return 9050
    monkeypatch.setattr(s, "_ensure_tor", tor)
    d = await s.make_card(BT)
    assert d.title.startswith("Ansat i politiet") and d.site == "B.T." and not d.note
    assert cd.icon_ok(d.icon) and d.picture.media_type == "image/jpeg"
    assert d.to_dict()["domain"] == "bt.dk"
    d = await s.make_card(AV)
    assert d.picture is None and cd.icon_ok(d.icon) and d.title.startswith("Autohuset")
    d = await s.make_card("https://gone.example/")
    assert d.title == "" and "write a title yourself" in d.note             # never an error
    s.set_link_cards(False)
    with pytest.raises(SessionError, match="turned off"):
        await s.make_card(BT)
    await s.close()


def test_cards_off_in_the_bootable_client(tmp_path, monkeypatch):
    s = _session(tmp_path)
    monkeypatch.setenv("UNSEENET_BOOTABLE", "1")
    assert s.link_cards() is False
    s.set_link_cards(True)
    assert s.link_cards() is True
    monkeypatch.delenv("UNSEENET_BOOTABLE")
    assert _session(tmp_path, "bob").link_cards() is True


def test_a_card_from_a_front_end():
    d = CardDraft.from_dict({"url": BT, "title": "Overskrift\nmed linjeskift", "desc": "Kort",
                             "icon": __import__("base64").b64encode(_png((64, 64))).decode(),
                             "picture": {"data": __import__("base64").b64encode(_png((900, 500))).decode()}})
    assert d.title == "Overskrift med linjeskift"
    assert cd.icon_ok(d.icon) and max(d.picture.dim) <= 600                # saved again here
    with pytest.raises(SessionError):
        CardDraft.from_dict({"url": BT})


# --- posting and reading (sections 4, 6) --------------------------------------------------------
@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    node.config.blobs = {"max_size": bl.MAX_BLOB, "encrypted": True}
    node.blobs = BlobStore()
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    made = []

    def person(name):
        s = _session(tmp_path, name)
        s.add_node(addr)
        s.data["starter_groups"] = 99
        made.append(s)
        return s
    yield node, person
    for s in made:
        await s.close()
    server.close()


def _draft(picture=True) -> CardDraft:
    return CardDraft(url=BT, title="Ansat i politiet snød Fleggaard: Nu er han dømt",
                     desc="Retten i Sønderborg ...", site="B.T.", icon=media.card_icon(_png()),
                     picture=media.card_picture(_png((1200, 630))) if picture else None,
                     made=datetime(2026, 10, 30, 12, 31, tzinfo=timezone.utc))


async def test_a_card_in_an_open_group(net):
    node, person = net
    alice, bob = person("alice"), person("bob")
    gid = await alice.create_group("nyheder", "open", min_pow=10,
                                   extra={"attachments": bl.PICTURES})
    body = f"Så blev han dømt. {BT}\n"
    with pytest.raises(SessionError, match="not in the text"):
        await alice.post(gid, "Dømt", "uden link\n", card=_draft())
    msgid = await alice.post(gid, "Dømt", body, card=_draft())
    art = Article.from_bytes(node.store.get(msgid))
    assert art.get(cd.HEADER) and art.get("Blobs")
    bob.subscribe(gid)
    await bob.fetch_group(gid)
    msg = bob.find_message(gid, msgid)
    assert msg.card.domain == "bt.dk" and msg.card.site == "B.T." and cd.icon_ok(msg.card.icon)
    (a,) = msg.attachments
    assert a["card"] is True and a["blob"] == msg.card.image
    d = msg.to_dict()["card"]
    assert d["title"].startswith("Ansat") and d["icon"] and d["image"] == a["blob"]
    assert (await bob.fetch_blob(gid, a["blob"]))[:3] == b"\xff\xd8\xff"
    # an edit keeps the card (UN-RFC 0059 section 10)
    new = await alice.edit(alice.find_message(gid, msgid) or msg, "Dømt", body + "Opdateret.\n")
    await bob.fetch_group(gid)
    assert bob.find_message(gid, new).card.title == msg.card.title


async def test_a_card_where_files_are_not_taken(net):
    node, person = net
    alice = person("alice")
    gid = await alice.create_group("snak", "open", min_pow=10)
    msgid = await alice.post(gid, "Link", f"Se {AV}\n", card=CardDraft(
        url=AV, title="Autohuset Vestergaard", icon=media.card_icon(_ico()),
        picture=media.card_picture(_png((800, 400)))))
    art = Article.from_bytes(node.store.get(msgid))
    assert not art.get("Blobs")                                   # the card goes without it
    assert cd.check(art[cd.HEADER], art.body).image is None


async def test_a_card_in_a_closed_group_and_a_private_post(net):
    node, person = net
    alice, bob = person("alice"), person("bob")
    fam = await alice.create_group("familie", "closed", min_pow=10,
                                   extra={"attachments": bl.PICTURES})
    await alice.invite(fam, bob.identity().key_text)
    msgid = await alice.post(fam, "Se", f"{BT}\n", card=_draft())
    assert not Article.from_bytes(node.store.get(msgid)).get(cd.HEADER)    # inside (4.1)
    bob.subscribe(fam)
    await bob.fetch_group(fam)
    msg = bob.find_message(fam, msgid)
    assert msg.card and msg.card.image == msg.attachments[0]["blob"]
    await bob.ensure_inbox()
    await alice.ensure_inbox()
    pid = await alice.send_private(bob.my_inbox, "Til dig", f"{BT}\n",
                                   owner_key=bob.identity().public_key, card=_draft(False))
    assert not Article.from_bytes(node.store.get(pid)).get(cd.HEADER)
    await bob.fetch_group(bob.my_inbox)
    assert bob.find_message(bob.my_inbox, pid).card.site == "B.T."
