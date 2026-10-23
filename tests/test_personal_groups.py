"""#359: the feed and pages views, and feed@/site@ as personal groups
(UN-RFC 0029 section 2.1, UN-RFC 0034 section 3.1, UN-RFC 0035 section 3)."""
import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError
from unseenet.core.groups import Manifest, is_key_bound, make_group_id, make_manifest
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig

BITS = 8


def _m(owner, name, gtype, **kw):
    return make_manifest(owner, name, gtype, pow_bits=BITS, **kw)


def test_feed_and_site_are_key_bound():
    pk = crypto.Identity.generate().public_key
    assert is_key_bound(make_group_id("feed", pk)) and is_key_bound(make_group_id("site", pk))
    assert not is_key_bound(make_group_id("dk.feed", pk))      # an ordinary group named so


def test_personal_groups_are_channels_with_their_view():
    me = crypto.Identity.generate()
    feed = Manifest.from_article(_m(me, "feed", "channel", view="feed", comments="open"))
    assert feed.view == "feed" and feed.expires is not None    # key-bound: expires
    site = Manifest.from_article(_m(me, "site", "channel", view="pages"))
    assert site.view == "pages" and site.expires is not None
    for name, gtype, view in (("feed", "open", "feed"), ("feed", "channel", "threads"),
                              ("feed", "channel", None), ("site", "channel", "feed"),
                              ("site", "moderated", "pages")):
        with pytest.raises(ArticleError, match="section 2.1|only a channel"):
            Manifest.from_article(_m(me, name, gtype, view=view))


def test_any_group_may_be_a_feed_but_only_channels_are_sites():
    me = crypto.Identity.generate()
    for gtype in ("open", "moderated", "channel", "closed"):     # UN-RFC 0034 section 3.2
        assert Manifest.from_article(_m(me, "dk.marsvin", gtype, view="feed")).view == "feed"
    assert Manifest.from_article(_m(me, "unseenet.site", "channel", view="pages")).view == "pages"
    for gtype in ("open", "moderated", "closed"):
        with pytest.raises(ArticleError, match="only a channel"):
            Manifest.from_article(_m(me, "dk.wiki", gtype, view="pages"))


def test_a_node_carries_a_personal_feed_but_does_not_list_it():
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    me = crypto.Identity.generate()
    feed = _m(me, "feed", "channel", view="feed", comments="open")
    node.accept(feed.to_bytes())
    assert node.store.manifest(feed.group) is not None
    assert feed.group not in [g for g, *_ in node.store.groups(ordinary=True)]   # UN-RFC 0040, 3
    with pytest.raises(ArticleError):
        node.accept(_m(crypto.Identity.generate(), "feed", "open", view="feed").to_bytes())


async def test_a_reader_may_see_a_feed_as_threads_and_back(tmp_path):
    from unseenet.client.session import Session
    from unseenet.core.vault import Vault
    s = Session(Vault.open(tmp_path / "v.vault", "pw", ops=1, mem=8192 * 1024),
                status=lambda *_: None)
    s.new_identity("me", "Me")
    gid = make_group_id("dk.marsvin", crypto.Identity.generate().public_key)
    s.set_view(gid, "threads")
    s.set_view(gid, "feed")
    with pytest.raises(ValueError):
        s.set_view(gid, "gallery")
