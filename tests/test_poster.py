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
        assert roots == [(result.message_id, "Today")]
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
