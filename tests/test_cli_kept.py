"""#387 part 3: pins, the pages of sites and personal groups, from the command line
through Session - and a reader's client sees what the node keeps."""
import json
from argparse import Namespace

import pytest

from unseenet import cli
from unseenet.core.groups import is_key_bound
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(cli, "DEFAULT_POW", BITS)
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", BITS)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), sites="accept"))
    server = await node.serve("127.0.0.1", 0)
    address = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    apps = []

    async def app(name):
        a = cli.App(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF))
        a.data["nodes"].append(address)
        await cli.c_id_new(a, Namespace(name=name, display=None))
        apps.append(a)
        return a

    yield node, app
    for a in apps:
        if a._session is not None:
            await a._session.close()
    server.close()


def _args(**kw):
    base = dict(identity=None, json=True, subject=None, body="Tekst\n", kind="post", reply_to=None,
                edit=None, format=None, attach=None, publish_outside_tor=False, local=False,
                moderator=None, poster=None, title=None, description=None, min_pow=BITS,
                retention_days=None, view=None, kinds=None, rules=None, comments=None,
                comment_days=None, attachments=None, types=None, max_pins=None, max_pages=None,
                home=None, note=None, unpin=False, yes=True)
    return Namespace(**(base | kw))


def _json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


async def test_pins_as_the_owner_sets_them_and_a_reader_sees_them(setup, capsys):
    node, app = setup
    me, other = await app("me"), await app("other")
    await cli.c_group_create(me, _args(name="dk.nyt", type="channel", max_pins=3))
    gid = _json(capsys)["group"]
    await cli.c_post(me, _args(group=gid, subject="Regler"))
    rules = _json(capsys)["message_id"]
    await cli.c_post(me, _args(group=gid, subject="Velkommen"))
    welcome = _json(capsys)["message_id"]

    await cli.c_pin(me, _args(group=gid, message_id=rules, note="Læs dem først"))
    await cli.c_pin(me, _args(group=gid, message_id=welcome))
    await cli.c_pin(me, _args(group=gid, message_id=rules, unpin=True))
    capsys.readouterr()
    await cli.c_pins(other, _args(group=gid))
    seen = _json(capsys)["pins"]
    assert [p["id"] for p in seen] == [welcome]
    print("NODE MARKERS", node.store.markers(gid)); print("NODE PINS", node.store.pins_in_force(gid))
    assert [p.target for p in node.store.pins_in_force(gid)] == [welcome]   # as the node keeps
    with pytest.raises(SystemExit, match="owner or a moderator"):
        await cli.c_pin(other, _args(group=gid, message_id=rules))
    with pytest.raises(SystemExit, match="not pinned"):
        await cli.c_pin(me, _args(group=gid, message_id=rules, unpin=True))


async def test_a_site_its_versions_and_a_removal(setup, tmp_path, capsys):
    node, app = setup
    me, other = await app("me"), await app("other")
    await cli.c_group_create(me, _args(name="dk.wiki", type="channel", view="pages"))
    gid = _json(capsys)["group"]
    page = tmp_path / "index.md"
    page.write_text("# Velkommen\n\nFørste version.\n")
    await cli.c_page_put(me, _args(group=gid, path="index", file=str(page), title="Forside"))
    v1 = _json(capsys)["message_id"]
    (tmp_path / "about.md").write_text("Om os.\n")
    await cli.c_page_put(me, _args(group=gid, path="about", file=str(tmp_path / "about.md")))
    page.write_text("# Velkommen\n\nAnden version.\n")
    await cli.c_page_put(me, _args(group=gid, path="index", file=str(page), title="Forside"))
    v2 = _json(capsys)["message_id"]

    await cli.c_pages(other, _args(group=gid))
    seen = _json(capsys)
    assert [p["path"] for p in seen["pages"]] == ["index", "about"]           # home first
    assert seen["pages"][0]["current"] == v2 and seen["pages"][0]["previous"] == v1
    currents, force = node.store.site(gid)
    assert currents["index"][0].message_id == v2 and sorted(force) == ["about", "index"]

    await cli.c_page_remove(me, _args(group=gid, path="about"))
    capsys.readouterr()
    await cli.c_pages(other, _args(group=gid))
    assert [p["path"] for p in _json(capsys)["pages"]] == ["index"]
    with pytest.raises(SystemExit, match="writers"):
        await cli.c_page_put(other, _args(group=gid, path="index", file=str(page)))
    with pytest.raises(SystemExit, match="path"):
        await cli.c_page_put(me, _args(group=gid, path="Store/Bogstaver", file=str(page)))


async def test_a_personal_feed_and_site(setup, tmp_path, capsys):
    node, app = setup
    me = await app("me")
    await cli.c_feed_start(me, _args())
    feed = _json(capsys)["group"]
    assert feed.startswith("feed@") and is_key_bound(feed)
    m = node.store.manifest(feed)
    assert m.view == "feed" and m.raw["comments"] == "open" and "expires" in m.raw
    await cli.c_post(me, _args(group=feed, subject="Mit første opslag"))
    assert node.store.get(_json(capsys)["message_id"])
    await cli.c_feed_start(me, _args())                                 # again: the same feed
    assert _json(capsys)["group"] == feed and node.store.manifest(feed).raw["serial"] == 1

    await cli.c_site_start(me, _args())
    site = _json(capsys)["group"]
    assert site.startswith("site@") and node.store.manifest(site).view == "pages"
    (tmp_path / "index.md").write_text("Min side.\n")
    await cli.c_page_put(me, _args(group=site, path="index", file=str(tmp_path / "index.md")))
    assert node.store.site(site)[1] == ["index"]


async def test_starting_a_personal_group_asks_first(setup, capsys):
    node, app = setup
    me = await app("me")
    with pytest.raises(SystemExit, match="--yes"):
        await cli.c_feed_start(me, _args(yes=False))
    assert "cannot be recalled" in capsys.readouterr().err
