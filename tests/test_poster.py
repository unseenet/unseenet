"""The headless posting API (core/poster.py): keys without prompts, posting to
several nodes, postage, "later" retries, and reading back."""

import asyncio

import pytest

from unseenet.core import crypto
from unseenet.core.article import new_article
from unseenet.core.groups import make_manifest
from unseenet.core.poster import Poster, PosterError, load_key
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8


async def start_node(min_pow=BITS):
    node = Node(Store(), NodeConfig(min_pow=min_pow, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    return node, server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def test_load_key(tmp_path, monkeypatch):
    me = crypto.Identity.generate()
    monkeypatch.delenv("UNSEENET_SEED", raising=False)
    with pytest.raises(PosterError):
        load_key()
    monkeypatch.setenv("UNSEENET_SEED", me.seed.hex())
    assert load_key().key_text == me.key_text
    f = tmp_path / "bot.key"
    f.write_text(me.seed.hex() + "\n")
    assert load_key(key_file=f).key_text == me.key_text

    v = Vault.open(tmp_path / "bot.vault", "pw", ops=1, mem=8192 * 1024)
    v.data["identities"] = {"bot": {"seed": me.seed.hex(), "display": "Bot"}}
    v.save()
    monkeypatch.delenv("UNSEENET_VAULT_PASSPHRASE", raising=False)
    with pytest.raises(PosterError):                 # never prompts
        load_key(vault=tmp_path / "bot.vault")
    monkeypatch.setenv("UNSEENET_VAULT_PASSPHRASE", "pw")
    assert load_key(vault=tmp_path / "bot.vault").key_text == me.key_text


async def test_post_to_several_nodes_with_postage_and_read_back():
    owner, bot = crypto.Identity.generate(), crypto.Identity.generate()
    manifest = make_manifest(owner, "news", "channel", posters=[bot.key_text], min_pow=10,
                             pow_bits=10)
    (a, sa, addr_a), (b, sb, addr_b) = await start_node(), await start_node(min_pow=9)
    for node in (a, b):
        node.accept(manifest.to_bytes())
    down = "127.0.0.1:1"
    async with Poster(bot, [addr_a, down, addr_b], from_name="News bot", tor="none") as p:
        result = await p.post(manifest.group, "Today", "Something happened")
        assert result.ok and result.accepted == [addr_a, addr_b] and down in result.unreachable
        art = await p.article(result.message_id)
        assert art is not None and art.proven_pow() >= 10      # the group asked for 10 bits
        assert art.get("Message-Kind") == "post" and art.get("From") == "News bot"
        assert (await p.post(manifest.group, "Today", "Something happened")).ok  # duplicate is fine
        roots = await p.recent_threads(manifest.group)
        # the same post twice is one article - unless the two straddle a 10-minute Date
        # boundary (Date is rounded, UN-RFC 0002), when they are two (#369)
        assert (result.message_id, "Today") in roots and all(s == "Today" for _, s in roots)
        assert len(roots) <= 2
        assert (await p.post(manifest.group, "Tomorrow", "More")).ok   # a poster starts threads
    stranger = Poster(crypto.Identity.generate(), [addr_a], tor="none")
    async with stranger:
        no = await stranger.post(manifest.group, "Spam", "no")
    assert not no.ok and "permission" in no.refused[addr_a]
    for s in (sa, sb):
        s.close()


async def test_later_is_retried(monkeypatch):
    owner, bot, reader = (crypto.Identity.generate() for _ in range(3))
    manifest = make_manifest(owner, "news", "channel", posters=[bot.key_text], comments="open",
                             pow_bits=BITS)
    node, server, addr = await start_node()
    node.accept(manifest.to_bytes())
    root = new_article(manifest.group, "Today", "x\n", from_name="bot").finalize(bot, BITS)

    async def root_arrives():
        await asyncio.sleep(0.05)
        node.accept(root.to_bytes())

    async with Poster(reader, [addr], tor="none", later_pause=0.1) as p:
        task = asyncio.create_task(root_arrives())
        result = await p.post(manifest.group, "Re: Today", "A comment",
                              references=[root.message_id])
        await task
    assert result.ok
    server.close()


def test_build_rules():
    p = Poster(crypto.Identity.generate(), [], tor="none")
    gid = "news@" + "a" * 16
    with pytest.raises(ValueError):
        p.build(gid, "", "no subject")
    chat = p.build(gid, "ignored", "hej", kind="chat")
    assert chat.get("Subject") == "" and chat.get("Message-Kind") == "chat"
    with pytest.raises(ValueError):
        p.build(gid, "x", "y", kind="letter")


# --- files on posts (#474, UN-RFC 0027) -------------------------------------------

def _png(w=40, h=30) -> bytes:
    import io

    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


def _channel_with_files(owner, bot, attachments):
    """A channel the bot posts in; ``attachments`` as in its manifest (None: no files)."""
    from unseenet.core.groups import Manifest, canonical_json
    m = make_manifest(owner, "space", "channel", posters=[bot.key_text], pow_bits=BITS)
    if attachments is None:
        return m
    data = Manifest.from_article(m).raw | {"attachments": attachments}
    art = new_article(m.group, None, canonical_json(data),
                      extra=[("Control", "manifest"), ("Content-Type", "application/json")])
    return art.finalize(owner, BITS)


async def _node_with_blobs(**blobs):
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), blobs=blobs or None))
    server = await node.serve("127.0.0.1", 0)
    return node, server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def test_a_picture_goes_with_the_post_and_reads_back(tmp_path):
    from unseenet.client.session import Session
    from unseenet.core import blobs as bl
    owner, bot = crypto.Identity.generate(), crypto.Identity.generate()
    manifest = _channel_with_files(owner, bot, {"max_size": 1048576, "types": ["image/*"]})
    node, server, addr = await _node_with_blobs(max_size=1048576)
    node.accept(manifest.to_bytes())
    octets = _png()
    async with Poster(bot, [addr], from_name="NASA bot", tor="none",
                      state=tmp_path / "bot.json") as p:
        result = await p.post(manifest.group, "Image of the day", "The Moon",
                              files=[("moon.png", octets, "The Moon over the sea")])
    assert result.ok and result.accepted == [addr], result
    reader = Session(Vault.open(tmp_path / "r.vault", "pw", ops=1, mem=8192 * 1024),
                     status=lambda *_: None)
    reader.new_identity("r", "R")
    reader.add_node(addr)
    reader.subscribe(manifest.group)
    try:
        [msg] = reader.visible(await reader.fetch_group(manifest.group))
        [att] = msg.attachments
        assert att["name"] == "moon.png" and att["type"] == "image/png"
        assert att["alt"] == "The Moon over the sea" and att["dim"] == [40, 30]
        sent = await reader.fetch_blob(manifest.group, att["blob"])
        assert att["blob"] == bl.blob_id(sent) and sent.startswith(b"\x89PNG")
    finally:
        await reader.close()
        server.close()


async def test_files_are_checked_before_any_postage(tmp_path):
    owner, bot = crypto.Identity.generate(), crypto.Identity.generate()
    manifest = _channel_with_files(owner, bot, None)          # the group takes no files
    node, server, addr = await _node_with_blobs(max_size=1048576)
    node.accept(manifest.to_bytes())
    async with Poster(bot, [addr], tor="none", state=tmp_path / "bot.json") as p:
        with pytest.raises(PosterError, match="takes no files"):
            await p.post(manifest.group, "Picture", "x", files=[("a.png", _png())])
        with pytest.raises(PosterError, match="a file must be"):
            await p.post(manifest.group, "Picture", "x", files=[42])
    server.close()


async def test_a_node_without_files_refuses_the_post(tmp_path):
    owner, bot = crypto.Identity.generate(), crypto.Identity.generate()
    manifest = _channel_with_files(owner, bot, {"max_size": 1048576})
    node, server, addr = await _node_with_blobs()              # blobs off on this node
    node.accept(manifest.to_bytes())
    async with Poster(bot, [addr], tor="none", state=tmp_path / "bot.json") as p:
        result = await p.post(manifest.group, "Picture", "x", files=[("a.png", _png())])
    assert not result.ok and "carries no files" in result.refused[addr]
    server.close()


def _card(url, picture=True):
    """A link card as ``make_card`` gives one (UN-RFC 0059), without going to the web."""
    from datetime import datetime, timezone

    from unseenet.client import media
    from unseenet.client.session import CardDraft
    return CardDraft(url=url, title="Kunstig solformørkelse", desc="ESA's Proba-3",
                     site="ESA", made=datetime(2026, 10, 30, tzinfo=timezone.utc),
                     picture=media.card_picture(_png(1200, 630)) if picture else None)


async def _read_back(tmp_path, addr, group):
    from unseenet.client.session import Session
    reader = Session(Vault.open(tmp_path / "r.vault", "pw", ops=1, mem=8192 * 1024),
                     status=lambda *_: None)
    reader.new_identity("r", "R")
    reader.add_node(addr)
    reader.subscribe(group)
    return reader, reader.visible(await reader.fetch_group(group))


async def test_a_link_card_goes_with_the_post(tmp_path):
    url = "https://www.esa.int/proba-3"
    owner, bot = crypto.Identity.generate(), crypto.Identity.generate()
    manifest = _channel_with_files(owner, bot, {"max_size": 1048576, "types": ["image/*"]})
    node, server, addr = await _node_with_blobs(max_size=1048576)
    node.accept(manifest.to_bytes())
    async with Poster(bot, [addr], tor="none", state=tmp_path / "bot.json") as p:
        result = await p.post(manifest.group, "Proba-3", f"Fra [ESA]({url})", card=_card(url))
    assert result.ok, result
    reader, [msg] = await _read_back(tmp_path, addr, manifest.group)
    try:
        assert msg.card.url == url and msg.card.title == "Kunstig solformørkelse"
        [att] = msg.attachments                     # the card's picture, and only in the card
        assert att["card"] is True and msg.card.image == att["blob"]
    finally:
        await reader.close()
        server.close()


async def test_a_link_card_without_files_and_a_card_for_another_link(tmp_path):
    url = "https://www.esa.int/proba-3"
    owner, bot = crypto.Identity.generate(), crypto.Identity.generate()
    manifest = _channel_with_files(owner, bot, None)          # the group takes no files
    node, server, addr = await _node_with_blobs(max_size=1048576)
    node.accept(manifest.to_bytes())
    async with Poster(bot, [addr], tor="none", state=tmp_path / "bot.json") as p:
        with pytest.raises(PosterError, match="not in the text"):
            await p.post(manifest.group, "Proba-3", "no link here", card=_card(url))
        result = await p.post(manifest.group, "Proba-3", f"Se {url}", card=_card(url))
    assert result.ok, result
    reader, [msg] = await _read_back(tmp_path, addr, manifest.group)
    try:
        assert msg.card.url == url and msg.card.image is None and not msg.attachments
    finally:
        await reader.close()
        server.close()
