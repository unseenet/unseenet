"""#387 part 4: profiles, following feeds and people, the timeline and addresses, from the
command line through Session."""
import io
import json
from argparse import Namespace

import pytest
from PIL import Image

from unseenet import cli
from unseenet.core import profiles as prof
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
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), sites="accept",
                                    profiles="accept", avatars="accept"))
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
                home=None, yes=True, of=None, about=None, markdown=False, link=None, lang=None,
                feed=None, picture=None, alt=None, remove_picture=False, empty=False,
                refresh=False, limit=50, group=None, message=None, page=None, node=None,
                follow=False)
    return Namespace(**(base | kw))


def _json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


async def test_following_a_person_and_their_feeds(setup, capsys):
    node, app = setup
    alice, bob = await app("alice"), await app("bob")
    akey = alice.session.identity().key_text
    fp = alice.session.identity().fingerprint
    await cli.c_feed_start(alice, _args())
    feed = _json(capsys)["group"]
    await cli.c_group_create(bob, _args(name="dk.klub", type="channel", view="feed", poster=[akey]))
    club = _json(capsys)["group"]                  # bob's club, where alice posts
    await cli.c_group_create(bob, _args(name="dk.bobs", type="channel", view="feed"))
    not_hers = _json(capsys)["group"]              # listed by alice, but not hers
    await cli.c_profile(alice, _args(about="Hej", feed=[club, not_hers]))
    capsys.readouterr()

    carol = await app("carol")
    await cli.c_follow(carol, _args(target=fp))
    r = _json(capsys)
    assert sorted(r["feeds"]) == sorted([feed, club]) and r["key"] == akey
    assert not_hers not in carol.session.data["subscribed"]

    await cli.c_follow(carol, _args(target=club))  # also on its own
    await cli.c_site_start(alice, _args())
    site = _json(capsys)["group"]
    await cli.c_profile(alice, _args(feed=[not_hers]))      # club no longer listed
    capsys.readouterr()
    await cli.c_following(carol, _args(refresh=True))
    out = _json(capsys)
    assert out["new"] == [site] and club in carol.session.data["subscribed"]   # kept: own follow

    await cli.c_unfollow(carol, _args(target=fp))
    gone = _json(capsys)["unsubscribed"]
    assert sorted(gone) == sorted([feed, site]) and club in carol.session.data["subscribed"]
    assert carol.session.following() == []


async def test_following_by_name_follows_the_key(setup, monkeypatch, capsys):
    node, app = setup
    alice, bob = await app("alice"), await app("bob")
    await cli.c_feed_start(alice, _args())
    feed = _json(capsys)["group"]
    from unseenet.client import naming
    akey = alice.session.identity().key_text
    monkeypatch.setattr(naming, "key_for_name", lambda s, name: akey if name == "alice@lorensen" else None)
    await cli.c_follow(bob, _args(target="alice@lorensen"))
    r = _json(capsys)
    assert r["name"] == "alice@lorensen" and r["key"] == akey and r["feeds"] == [feed]
    with pytest.raises(SystemExit, match="no identity"):
        await cli.c_follow(bob, _args(target="nobody@nowhere"))


async def test_the_timeline(setup, capsys):
    node, app = setup
    alice, bob = await app("alice"), await app("bob")
    await cli.c_feed_start(alice, _args())
    feed = _json(capsys)["group"]
    await cli.c_group_create(alice, _args(name="dk.andet", type="channel", view="feed"))
    other = _json(capsys)["group"]
    for subject in ("Første", "Anden"):
        await cli.c_post(alice, _args(group=feed, subject=subject))
    first = _json(capsys)["message_id"]
    await cli.c_post(alice, _args(group=other, subject="Ikke fulgt"))
    capsys.readouterr()
    await cli.c_follow(bob, _args(target=alice.session.identity().fingerprint))
    capsys.readouterr()
    await cli.c_post(bob, _args(group=feed, reply_to=first, body="En kommentar\n"))
    capsys.readouterr()
    await cli.c_timeline(bob, _args())
    entries = _json(capsys)["entries"]
    assert sorted(e["subject"] for e in entries) == ["Anden", "Første"]       # no comment, no unfollowed feed
    assert all(e["feed"] == feed for e in entries)


async def test_a_profile_and_its_picture(setup, tmp_path, capsys):
    node, app = setup
    alice, bob = await app("alice"), await app("bob")
    img = Image.new("RGB", (400, 300), (200, 80, 20))
    ex = Image.Exif()
    ex[0x010F] = "SecretCam"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=ex)
    (tmp_path / "me.jpg").write_bytes(buf.getvalue())
    await cli.c_profile(alice, _args(about="Jeg skriver om marsvin.", link=["web=https://example.org"],
                                     lang=["da"], picture=str(tmp_path / "me.jpg"), alt="Mig"))
    mine = _json(capsys)["profile"]
    assert mine["about"].startswith("Jeg") and mine["links"][0]["kind"] == "web"
    fp = alice.session.identity().fingerprint
    pic = prof.picture_from_manifest(node.store.manifest(f"avatar@{fp}"))
    data = prof.check_picture(pic)
    assert pic["px"] <= 128 and len(data) <= 8192 and b"SecretCam" not in data and pic["alt"] == "Mig"
    await cli.c_profile(bob, _args(of=fp))
    assert _json(capsys)["profile"]["about"] == "Jeg skriver om marsvin."


async def test_addresses(setup, capsys):
    node, app = setup
    alice = await app("alice")
    await cli.c_group_create(alice, _args(name="dk.wiki", type="channel", view="pages"))
    gid = _json(capsys)["group"]
    await cli.c_post(alice, _args(group=gid, subject="Hej"))
    mid = _json(capsys)["message_id"]
    await cli.c_address(alice, _args())
    assert _json(capsys)["address"] == "unseenet:" + alice.session.identity().fingerprint
    await cli.c_address(alice, _args(group=gid, message=mid))
    post = _json(capsys)["address"]
    assert post == f"unseenet:{gid}?m={mid.strip('<>')}"
    bob = await app("bob")
    await cli.c_open(bob, _args(address=post))
    seen = _json(capsys)
    assert seen["kind"] == "post" and seen["subject"] == "Hej" and seen["view"] == "pages"
    await cli.c_open(bob, _args(address=f"unseenet:{gid}", follow=True))
    assert _json(capsys)["following"] and gid in bob.session.data["subscribed"]
    await cli.c_open(bob, _args(address="unseenet:dk.ingen@aaaaaaaaaaaaaaaa"))
    assert _json(capsys)["available"] is False
    with pytest.raises(SystemExit, match="Not an address"):
        await cli.c_open(bob, _args(address="https://example.org"))



async def test_the_timeline_in_the_next_command(setup, tmp_path, capsys):
    """Found on the test nodes: each command is a new process, so what follow learnt
    about a feed must be in the vault - else the timeline did not know it was a feed."""
    node, app = setup
    alice, bob = await app("alice"), await app("bob")
    await cli.c_feed_start(alice, _args())
    feed = _json(capsys)["group"]
    await cli.c_post(alice, _args(group=feed, subject="Hej verden"))
    capsys.readouterr()
    await cli.c_follow(bob, _args(target=alice.session.identity().fingerprint))
    capsys.readouterr()
    again = cli.App(Vault.open(tmp_path / "bob.vault", "pw", **KDF))     # the next command
    again.data["nodes"][:] = bob.data["nodes"]
    try:
        await cli.c_timeline(again, _args())
        assert [e["subject"] for e in _json(capsys)["entries"]] == ["Hej verden"]
        again.data["groups"][feed].pop("manifest")                     # and if it is not known
        await cli.c_timeline(again, _args())
        assert [e["subject"] for e in _json(capsys)["entries"]] == ["Hej verden"]
    finally:
        if again._session is not None:
            await again._session.close()


async def test_a_profile_from_a_restored_vault(setup, tmp_path, monkeypatch, capsys):
    """Found making the demo's weekly run: a new vault with the same key (restored
    from a backup, a second device, a CI run) did not know the profile's serial, began
    at 1, and the node refused it as older. It asks the network first now."""
    import io as _io
    node, app = setup
    first = await app("first")
    seed = first.data["identities"]["first"]["seed"]
    await cli.c_profile(first, _args(about="Once"))
    capsys.readouterr()
    other = cli.App(Vault.open(tmp_path / "restored.vault", "pw", **KDF))
    other.data["nodes"][:] = first.data["nodes"]
    monkeypatch.setattr("sys.stdin", _io.StringIO(seed + "\n"))
    await cli.c_id_import(other, Namespace(name="first", display=None, json=True))
    capsys.readouterr()
    try:
        await cli.c_profile(other, _args(about="Again, from another vault"))
        assert _json(capsys)["profile"]["about"] == "Again, from another vault"
        fp = other.session.identity().fingerprint
        assert node.store.manifest(f"profile@{fp}").raw["serial"] == 2
    finally:
        if other._session is not None:
            await other._session.close()


async def test_labels_for_personal_feeds_and_people_followed(setup, tmp_path, capsys):
    """#423: a personal feed is named after its owner, and a followed person keeps
    the name seen in their posts across commands - not "feed" and "?~abcd"."""
    node, app = setup
    alice, bob = await app("alice"), await app("bob")
    await cli.c_feed_start(alice, _args())
    feed = _json(capsys)["group"]
    await cli.c_post(alice, _args(group=feed, subject="Hej"))
    await cli.c_follow(bob, _args(target=alice.session.identity().fingerprint))
    capsys.readouterr()
    await cli.c_timeline(bob, _args())
    entry = _json(capsys)["entries"][0]
    assert entry["feed_label"] == "alice~" + alice.session.identity().fingerprint[:4] + "'s feed" \
        or entry["feed_label"].endswith("'s feed")
    again = cli.App(Vault.open(tmp_path / "bob.vault", "pw", **KDF))   # the next command
    again.data["nodes"][:] = bob.data["nodes"]
    try:
        await cli.c_following(again, _args())
        label = _json(capsys)["people"][0]["label"]
        assert not label.startswith("?") and "alice" in label
    finally:
        if again._session is not None:
            await again._session.close()
