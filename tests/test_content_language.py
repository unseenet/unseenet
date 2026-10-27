"""#671, UN-RFC 0052 section 5a: the language of a post - the author's choice, suggested
by what they used last in the group, then the group's, then a one-language profile;
better none than a wrong one."""

import pytest

import unseenet.client.session as sess
from unseenet.client import scoring as sc
from unseenet.client.session import Session
from unseenet.core import crypto, tags as tg
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


def test_the_header_and_the_node():
    assert tg.normalize_languages(["da-DK", "EN", "en", "x", "dansk"]) == ["da", "en"]
    assert tg.parse_languages("en, da") == ("en", "da")
    for bad in ("DA", "da, da", "danish", "da, en, de, sv, fi"):
        with pytest.raises(tg.TagError):
            tg.parse_languages(bad)
    owner, writer = crypto.Identity.generate(), crypto.Identity.generate()
    n = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), min_ripe=None))
    m = make_manifest(owner, "dk.snak", "open", pow_bits=16, extra={"languages": ["da"]})
    n.accept(m.to_bytes())
    n.accept(new_article(m.group, "Hej", "x\n", from_name="w",
                         extra=[("Content-Language", "da")]).finalize(writer, 10).to_bytes())
    with pytest.raises(ArticleError, match="syntax"):
        n.accept(new_article(m.group, "Hej", "x\n", from_name="w",
                             extra=[("Content-Language", "Danish")]).finalize(writer, 10).to_bytes())
    with pytest.raises(ValueError):
        make_manifest(owner, "dk.x", "open", pow_bits=16, extra={"languages": ["dansk"]})


async def test_suggested_remembered_and_in_rules(tmp_path, monkeypatch, fast_ripening):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    me = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    me.new_identity("me", "Me"); me.add_node(addr)
    try:
        dk = await me.create_group("dk.snak", "open", min_pow=8, extra={"languages": ["da"]})
        dev = await me.create_group("alt.dev", "open", min_pow=8)
        assert me.suggest_languages(dk) == (["da"], "group")
        assert me.suggest_languages(dev) == ([], "")                # better none than wrong
        await me.post(dev, "Hello", "in English\n", languages=["en"])
        assert me.suggest_languages(dev) == (["en"], "you")          # remembered here ...
        assert me.suggest_languages(dk) == (["da"], "group")         # ... and only here
        await me.post(dk, "Hej", "på dansk\n", languages=["da"])
        await me.post(dk, "Hi", "this one in English\n", languages=["en"])
        assert me.suggest_languages(dk) == (["en"], "you")           # the last choice
        await me.post(dk, "Uden", "x\n")                              # None: no header
        await me.send_chat(dk, "en linje")                            # a chat line: suggested
        closed = await me.create_group("dk.lukket", "closed", min_pow=8)
        await me.post(closed, "Hemmeligt", "x\n", languages=["da"])
        by = {m.subject: m for m in await me.fetch_group(dk)}
        assert by["Hej"].languages == ("da",) and by["Hi"].languages == ("en",) and by["Uden"].languages == ()
        [line] = [m for m in by.values() if m.kind == "chat"]
        assert line.languages == ("en",)                               # what you used here last
        [c] = await me.fetch_group(closed)
        assert c.languages == ("da",)
        raw = node.store.get(c.message_id)
        assert b"Content-Language" not in raw.split(b"\r\n\r\n", 1)[0]  # inside the encryption
        assert me.group_info(dk).languages == ("da",)
        rs = sc.parse("+10 if lang da\n")
        assert sc.score(rs, me.post_facts(by["Hej"]), me.scoring_context(), "groups").score == 10
        assert sc.score(rs, me.post_facts(by["Uden"]), me.scoring_context(), "groups").score == 0
    finally:
        await me.close()
        server.close()
