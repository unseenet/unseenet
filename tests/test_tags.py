"""Tags (UN-RFC 0052, #657): the author's own, only in a header; nodes check the form
and nothing else; a group's tags in its manifest."""

import pytest

from unseenet.client.session import Session
from unseenet.core import crypto, tags as tg
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


def test_what_a_tag_is():
    for ok in ("politics", "linux", "økonomi", "3d", "c-sharp", "日本"):
        assert tg.is_tag(ok), ok
    for bad in ("Linux", "c++", "two words", "-x", "", "a" * 33, "#linux", "under_score"):
        assert not tg.is_tag(bad), bad
    assert tg.normalize(["#Linux", " Politics ", "linux", "c++", "Økonomi"]) == ["linux", "politics", "økonomi"]
    assert tg.normalize([f"t{i}" for i in range(12)]) == [f"t{i}" for i in range(8)]
    assert tg.parse("politics, linux,spoiler") == ("politics", "linux", "spoiler")
    for bad in ("Politics", "a, a", ", ".join(f"t{i}" for i in range(9)), "a,,b"):
        with pytest.raises(tg.TagError):
            tg.parse(bad)
    assert tg.warnings(("linux", "spoiler", "gore")) == ("gore", "spoiler")


def test_nodes_check_the_form_only():
    owner, writer = crypto.Identity.generate(), crypto.Identity.generate()
    n = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), min_ripe=None))
    m = make_manifest(owner, "alt.snak", "open", pow_bits=16, extra={"tags": ["politics"]})
    n.accept(m.to_bytes())
    good = new_article(m.group, "Hej", "x\n", from_name="w", extra=[("Tags", "linux, spoiler")]).finalize(writer, 10)
    n.accept(good.to_bytes())                                   # carried as any other
    bad = new_article(m.group, "Hej", "x\n", from_name="w", extra=[("Tags", "Linux")]).finalize(writer, 10)
    with pytest.raises(ArticleError, match="syntax"):
        n.accept(bad.to_bytes())
    with pytest.raises(ValueError):
        make_manifest(owner, "alt.x", "open", pow_bits=16, extra={"tags": ["Bad tag"]})
    with pytest.raises(ValueError):
        make_manifest(owner, "alt.y", "open", pow_bits=16, extra={"tags": []})


@pytest.fixture
def two(tmp_path, monkeypatch, fast_ripening):
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    return node, tmp_path


async def test_post_with_tags_open_and_closed(two):
    node, tmp = two
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    me = Session(Vault.open(tmp / "me.vault", "pw", **KDF), status=lambda *_: None)
    me.new_identity("me", "Me"); me.add_node(addr)
    try:
        gid = await me.create_group("dk.politik", "open", min_pow=8, extra={"tags": ["politics"]})
        await me.post(gid, "Valg", "Om #EU og !dk.snak\n", tags=["#Danmark", "Valg", "spoiler"])
        [m] = await me.fetch_group(gid)
        # chips, then #words in the text; !dk.snak is a group, not a tag; the text is kept
        assert m.tags == ("danmark", "valg", "spoiler", "eu") and m.body.startswith("Om #EU og !dk.snak")
        assert me.group_info(gid).tags == ("politics",)
        closed = await me.create_group("dk.hemmelig", "closed", min_pow=8)
        await me.post(closed, "Inde", "y\n", tags=["linux"])
        [c] = await me.fetch_group(closed)
        assert c.tags == ("linux",)
        raw = node.store.get(c.message_id)                   # nodes never see them
        assert b"Tags:" not in raw.split(b"\r\n\r\n", 1)[0]
    finally:
        await me.close()
        server.close()


async def test_everything_with_a_tag(two):
    """UN-RFC 0052 section 7: the posts with a tag in the groups you follow - the
    author's, the group's - newest first, as a feed; not in groups you do not follow."""
    from unseenet.client.localapi import LocalAPI
    from unseenet.client.session import TAGGED
    node, tmp = two
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    me = Session(Vault.open(tmp / "me.vault", "pw", **KDF), status=lambda *_: None)
    me.new_identity("me", "Me"); me.add_node(addr)
    try:
        a = await me.create_group("dk.snak", "open", min_pow=8)
        b = await me.create_group("dk.linux", "open", min_pow=8, extra={"tags": ["linux"]})
        c = await me.create_group("dk.andet", "open", min_pow=8)
        one = await me.post(a, "Kerne", "Om #linux\n")
        two_ = await me.post(b, "Distro", "x\n")                      # the group's tag
        await me.post(a, "Mad", "#opskrift\n")
        await me.post(c, "Linux her", "#linux\n")
        me.data["subscribed"].remove(c)                              # not followed: not shown
        for g in (a, b):
            await me.fetch_group(g)
        assert {m.message_id for m in me.tagged("#Linux")} == {two_, one}   # same second: no order
        got = LocalAPI(session=me).group(TAGGED + "linux")
        assert got["group"]["label"] == "#linux" and got["group"]["view"] == "feed"
        assert {r["message"]["id"] for r in got["rows"]} == {two_, one}
        assert me.tagged("nonsense tag!") == []
    finally:
        await me.close()
        server.close()
