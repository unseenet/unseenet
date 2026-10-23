"""#387 part 1: the CLI as one more client on Session - groups, manifests, withdrawing."""
import json
from argparse import Namespace

import pytest

from unseenet import cli
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(cli, "DEFAULT_POW", BITS)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), sites="accept"))
    server = await node.serve("127.0.0.1", 0)
    address = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    apps = []

    async def app(name, *identities):
        a = cli.App(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF))
        a.data["nodes"].append(address)
        for ident in identities or (name,):
            await cli.c_id_new(a, Namespace(name=ident, display=None))
        apps.append(a)
        return a

    yield node, app
    for a in apps:
        if a._session is not None:
            await a._session.close()
    server.close()


def _args(**kw):
    base = dict(identity=None, json=True, local=False, moderator=None, poster=None, title=None,
                description=None, min_pow=BITS, retention_days=None, view=None, kinds=None,
                rules=None, comments=None, comment_days=None, attachments=None, types=None,
                max_pins=None, max_pages=None, home=None)
    return Namespace(**(base | kw))


def _json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


async def test_create_show_and_edit_a_channel(setup, capsys):
    node, app = setup
    me = await app("me")
    poster = await app("poster")
    pkey = poster.session.identity().key_text
    await cli.c_group_create(me, _args(name="dk.marsvin", type="channel", view="feed",
                                       comments="open", poster=[pkey], attachments=1048576,
                                       types="image/*", max_pins=3, title="Marsvin"))
    gid = _json(capsys)["group"]
    await cli.c_group_show(me, _args(group=gid))
    m = _json(capsys)
    assert m["view"] == "feed" and m["posters"] == [pkey] and m["comments"] == "open"
    assert m["attachments"] == {"max_size": 1048576, "types": ["image/*"]} and m["max_pins"] == 3

    other = (await app("other")).session.identity().key_text
    await cli.c_group_edit(me, _args(group=gid, add_poster=[other], remove_poster=[pkey],
                                     add_moderator=None, remove_moderator=None,
                                     ban=[pkey], unban=None, reason="spam", attachments=0))
    m = _json(capsys)
    assert m["posters"] == [other] and m["banned"][0] == {"key": pkey, "reason": "spam"}
    assert "attachments" not in m and m["serial"] == 2
    assert node.store.manifest(gid).raw["serial"] == 2
    with pytest.raises(SystemExit, match="sites"):
        await cli.c_group_edit(me, _args(group=gid, add_poster=None, remove_poster=None,
                                         add_moderator=None, remove_moderator=None, ban=None,
                                         unban=None, reason=None, max_pages=5))


async def test_a_site_and_acting_as_another_identity(setup, capsys):
    node, app = setup
    me = await app("me", "andreas", "projekt")
    await cli.c_group_create(me, _args(name="dk.wiki", type="channel", view="pages", max_pages=10,
                                       home="start", identity="projekt"))
    gid = _json(capsys)["group"]
    m = node.store.manifest(gid)
    assert m.raw["max_pages"] == 10 and m.raw["home"] == "start"
    assert m.raw["owner"] == me.session.identity("projekt").key_text
    assert me.data["default_identity"] == "andreas"          # -i is for this run only
    with pytest.raises(SystemExit, match="channel"):
        await cli.c_group_create(me, _args(name="dk.wiki2", type="open", view="pages"))


async def test_withdraw_all_as_owner_but_not_others_posts_as_a_stranger(setup, capsys):
    node, app = setup
    me, them = await app("me"), await app("them")
    await cli.c_group_create(me, _args(name="dk.demo", type="open"))
    gid = _json(capsys)["group"]
    for a, subject in ((me, "Velkommen"), (them, "Hej"), (them, "Igen")):
        await cli.c_post(a, Namespace(group=gid, subject=subject, body="x\n", identity=None))
    capsys.readouterr()
    ids = {a: [] for a in (me, them)}
    await me.session.fetch_group(gid)
    welcome = next(m.message_id for m in me.session.cache[gid].values() if m.subject == "Velkommen")
    theirs = [m.message_id for m in me.session.cache[gid].values() if m.subject != "Velkommen"]
    with pytest.raises(SystemExit, match="own posts"):
        await cli.c_withdraw(them, _args(group=gid, message_id=[welcome], all=False, keep=None,
                                         reason=None, yes=True))
    await cli.c_withdraw(me, _args(group=gid, message_id=[], all=True, keep=[welcome],
                                   reason="demo reset", yes=True))
    assert sorted(_json(capsys)["withdrawn"]) == sorted(theirs)
    assert node.store.get(welcome) and not any(node.store.get(t) for t in theirs)
    assert ids
