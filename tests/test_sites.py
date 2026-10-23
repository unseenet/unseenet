"""#212: sites and pages on the node (UN-RFC 0035)."""
from datetime import datetime, timedelta, timezone

import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import Manifest, canonical_json, make_manifest
from unseenet.core.store import Store
from unseenet.node.pulling import Puller
from unseenet.node.server import Node, NodeConfig, PeerConfig

BITS = 8
NOW = datetime.now(timezone.utc) - timedelta(days=2)
STEP = timedelta(minutes=10)            # Date is rounded to 10 minutes


def _node(name="a", sites="accept", **kw) -> Node:
    return Node(Store(), NodeConfig(name=name, min_pow=BITS, forward_delay=(0, 0), sites=sites, **kw))


def _site(owner, *, posters=(), serial=1, **fields):
    m = make_manifest(owner, "dk.wiki", "channel", view="pages", posters=list(posters),
                      serial=serial, pow_bits=BITS, retention_days=30)
    if not fields:
        return m
    data = Manifest.from_article(m).raw | fields
    return new_article(m.group, None, canonical_json(data),
                       extra=[("Control", "manifest"), ("Content-Type", "application/json")]
                       ).finalize(owner, BITS)


def _page(who, gid, path, text="Hej\n", *, title="Side", replaces=(), when=None, removed=False,
          extra=()):
    hdrs = [("Page", path), ("Content-Type", "text/markdown; charset=utf-8; variant=unseenet")]
    if replaces:
        hdrs.append(("Supersedes", " ".join(replaces)))
    if removed:
        hdrs.append(("Page-Removed", "yes"))
    return new_article(gid, title, "" if removed else text, from_name="X", now=when or NOW,
                       extra=hdrs + list(extra)).finalize(who, BITS)


def _put(node, art, when=None):
    """Pages at their own (past) time; a manifest at the real time it was made."""
    node.accept(art.to_bytes(), now=None if art.control else (when or NOW) + timedelta(seconds=1))
    return art


def test_sites_are_off_unless_the_operator_turns_them_on():
    owner = crypto.Identity.generate()
    with pytest.raises(ArticleError, match="no sites"):
        _node(sites="refuse").accept(_site(owner).to_bytes())
    _node().accept(_site(owner).to_bytes())
    assert _node().node_info()["policy"]["sites"] == "accept"
    assert Node(Store(), NodeConfig()).node_info()["policy"]["sites"] == "refuse"


def test_what_a_page_article_must_be():
    a = _node()
    owner, poster, someone = (crypto.Identity.generate() for _ in range(3))
    g = _put(a, _site(owner, posters=[poster.key_text])).group
    _put(a, _page(owner, g, "index"))
    _put(a, _page(poster, g, "projects/ovos"))
    for art, why in (
            (_page(someone, g, "x"), "writers"),
            (_page(owner, g, "Store/Bogstaver"), "path"),
            (_page(owner, g, "a/../b"), "path"),
            (_page(owner, g, "x", title="t" * 129), "title"),
            (_page(owner, g, "x", extra=[("References", "<a@b>")]), "reply"),
            (_page(owner, g, "x", extra=[("Page-Removed", "yes")]), "removal")):
        with pytest.raises(ArticleError, match=why):
            _put(a, art)
    other = _put(a, _page(owner, g, "about"))
    with pytest.raises(ArticleError, match="own path"):
        _put(a, _page(owner, g, "index", replaces=[other.message_id], when=NOW + STEP), NOW + STEP)
    plain = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    a.accept(plain.to_bytes())
    with pytest.raises(ArticleError, match="site"):
        _put(a, _page(owner, plain.group, "index"))


def test_current_previous_and_falling_back():
    a = _node()
    owner, poster = crypto.Identity.generate(), crypto.Identity.generate()
    g = _put(a, _site(owner, posters=[poster.key_text])).group
    v1 = _put(a, _page(owner, g, "index", "en\n"))
    v2 = _put(a, _page(poster, g, "index", "to\n", replaces=[v1.message_id], when=NOW + STEP), NOW + STEP)
    currents, force = a.store.site(g)
    assert currents["index"][0].message_id == v2.message_id
    assert currents["index"][1].message_id == v1.message_id and force == ["index"]
    assert a.store.get(v1.message_id)                          # replaced, not withdrawn
    a.accept(_site(owner, serial=2).to_bytes())                 # the poster is removed
    assert a.store.site(g)[0]["index"][0].message_id == v1.message_id


def test_pages_in_force_and_the_home_page():
    a = _node()
    owner = crypto.Identity.generate()
    g = _put(a, _site(owner, max_pages=2)).group
    _put(a, _page(owner, g, "index"))
    for i, p in enumerate(("one", "two", "three"), 1):
        _put(a, _page(owner, g, p, when=NOW + i * STEP), NOW + i * STEP)
    assert a.store.site(g)[1] == ["index", "three"]
    with pytest.raises(ArticleError, match="max_pages"):
        Manifest.from_article(_site(owner, max_pages=101))


def test_kept_versions_outlive_the_window():
    a = _node()
    owner = crypto.Identity.generate()
    g = _put(a, _site(owner)).group
    v1 = _put(a, _page(owner, g, "index", "1\n"))
    v2 = _put(a, _page(owner, g, "index", "2\n", replaces=[v1.message_id], when=NOW + STEP), NOW + STEP)
    v3 = _put(a, _page(owner, g, "index", "3\n", replaces=[v2.message_id, v1.message_id],
                       when=NOW + 2 * STEP), NOW + 2 * STEP)
    gone = _put(a, _page(owner, g, "old"))
    removal = _put(a, _page(owner, g, "old", removed=True, replaces=[gone.message_id],
                            when=NOW + 3 * STEP), NOW + 3 * STEP)
    a.store.db.execute("UPDATE articles SET date = date - ?", (60 * 86400,))   # all past 30 days
    a.store.db.execute("UPDATE pages SET date = date - ?", (60 * 86400,))
    a.store.db.commit()
    a.store.expire(90)
    assert a.store.get(v3.message_id) and a.store.get(v2.message_id)        # current and previous
    assert a.store.get(v1.message_id) is None                                # older: expired
    assert a.store.get(removal.message_id) is None and a.store.get(gone.message_id) is None
    assert a.store.state_ids(g) == [a.store.manifest(g).message_id, v3.message_id, v2.message_id]


async def test_a_new_node_gets_the_whole_site():
    a = _node("a")
    owner = crypto.Identity.generate()
    g = _put(a, _site(owner)).group
    old = NOW - timedelta(days=40)
    home = _put(a, _page(owner, g, "index", when=old), old)
    about = _put(a, _page(owner, g, "about", when=old), old)
    server = await a.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    b = _node("b", peers=[PeerConfig(name="a", address=addr)])
    res = await Puller(b, b.config.peers[0]).run_once()
    assert b.store.get(home.message_id) and b.store.get(about.message_id), res
    assert sorted(b.store.site(g)[1]) == ["about", "index"]
    server.close()


def test_a_personal_site():
    a = _node()
    me = crypto.Identity.generate()
    site = make_manifest(me, "site", "channel", view="pages", pow_bits=BITS)
    a.accept(site.to_bytes())
    _put(a, _page(me, site.group, "index"))
    assert a.store.site(site.group)[1] == ["index"]
