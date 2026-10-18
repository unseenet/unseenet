"""UN-RFC 0022: profiles, pictures, identicons, and what nodes carry."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core import profiles as prof
from unseenet.core.article import ArticleError
from unseenet.core.encoding import DS, H, b64
from unseenet.core.groups import Manifest, make_group_id, manifest_article
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100        # enough for the type check


def _picture(**kw):
    return prof.make_picture(PNG, "image/png", 64, **kw)


# --- the profile object --------------------------------------------------------

def test_profile_object_rules():
    p = prof.make_profile("Hej\n", [{"kind": "github", "value": "andlo"},
                                    {"kind": "x-pixelfed", "value": "@andlo@pixelfed.social"}],
                          ["da", "en"], bot=True)
    assert p == {"v": 1, "about": "Hej", "bot": True, "lang": ["da", "en"],
                 "links": [{"kind": "github", "value": "andlo"},
                           {"kind": "x-pixelfed", "value": "@andlo@pixelfed.social"}]}
    for bad in ({"v": 2}, {"v": 1, "about": "x" * 2049},
                {"v": 1, "links": [{"kind": "myspace", "value": "a"}]},
                {"v": 1, "links": [{"kind": "web", "value": ""}]},
                {"v": 1, "links": [{"kind": "web", "value": "a"}] * 17},
                {"v": 1, "lang": ["not a tag"]}, {"v": 1, "bot": "yes"},
                {"v": 1, "avatar": _picture()}):            # public: picture is in avatar@
        with pytest.raises(prof.ProfileError):
            prof.check_profile(bad)
    assert prof.check_profile({"v": 1, "avatar": _picture()}, private=True)
    assert prof.check_profile({"v": 1, "future": 1})          # unknown fields are kept
    assert prof.is_empty({"v": 1, "bot": True})


def test_about_is_shown_without_control_characters():
    assert prof.clean_text("a\x1b[31mb\nc\x85") == "a\ufffd[31mb\nc\ufffd"


def test_picture_rules():
    assert prof.check_picture(_picture(alt="me")) == PNG
    for bad in (dict(_picture(), type="image/gif"), dict(_picture(), px=129),
                dict(_picture(), px=31), dict(_picture(), type="image/jpeg"),   # not JPEG
                dict(_picture(), data=b64(b"\x89PNG\r\n\x1a\n" + bytes(8200)))):
        with pytest.raises(prof.ProfileError):
            prof.check_picture(bad)


def test_identicon_follows_the_spec():
    pk = crypto.Identity.generate().public_key
    seed = H(DS("UNSEENET-IDENTICON-1") + pk)
    icon = prof.identicon(pk)
    assert icon.hue == (256 * seed[0] + seed[1]) % 360
    for i in range(15):
        c, r = divmod(i, 5)
        bit = bool((seed[2 + i // 8] >> (i % 8)) & 1)
        assert icon.cells[r][c] == bit and icon.cells[r][4 - c] == bit
    assert prof.identicon(pk) == icon                          # the same everywhere
    assert len(icon.lines()) == 5 and icon.hex().startswith("#")


def test_profile_manifest_is_key_bound_data_group():
    me = crypto.Identity.generate()
    m = Manifest.from_article(prof.profile_manifest(me, prof.make_profile("Hej"), pow_bits=BITS))
    assert m.group_id == prof.profile_id(me.public_key) and m.view == "data"
    assert m.type == "channel" and not m.posters and m.expires is not None
    assert prof.profile_from_manifest(m).about == "Hej"
    empty = Manifest.from_article(prof.profile_manifest(me, None, serial=2, pow_bits=BITS))
    assert prof.profile_from_manifest(empty) is None


# --- nodes ----------------------------------------------------------------------

def _node(**kw):
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), **kw))


def test_node_takes_profiles_even_when_closed_to_new_groups():
    me = crypto.Identity.generate()
    node = _node(new_groups="manual")
    node.accept(prof.profile_manifest(me, prof.make_profile("Hej"), pow_bits=BITS).to_bytes())
    assert node.store.manifest(prof.profile_id(me.public_key)) is not None
    info = node.node_info()["policy"]
    assert info["profiles"] == "accept" and info["avatars"] == "refuse"


def test_node_refuses_pictures_unless_turned_on():
    me = crypto.Identity.generate()
    art = prof.avatar_manifest(me, _picture(), pow_bits=BITS)
    with pytest.raises(ArticleError, match="pictures"):
        _node().accept(art.to_bytes())
    on = _node(avatars="accept")
    on.accept(art.to_bytes())
    assert prof.picture_from_manifest(on.store.manifest(prof.avatar_id(me.public_key)))


def test_node_refuses_profiles_when_told_to():
    me = crypto.Identity.generate()
    with pytest.raises(ArticleError, match="profiles"):
        _node(profiles="refuse").accept(
            prof.profile_manifest(me, prof.make_profile("x"), pow_bits=BITS).to_bytes())


def test_node_refuses_bad_or_misplaced_profiles():
    me = crypto.Identity.generate()
    node = _node()
    gid = prof.profile_id(me.public_key)
    bad = {"v": 1, "name": "profile", "type": "channel", "owner": me.key_text, "serial": 1,
           "min_pow": 0, "retention_days": 7, "view": "data", "profile": {"v": 1, "bot": "y"}}
    with pytest.raises(ArticleError, match="bot"):
        node.accept(manifest_article(me, gid, bad, BITS).to_bytes())
    elsewhere = {"v": 1, "name": "dk.snak", "type": "open", "owner": me.key_text, "serial": 1,
                 "min_pow": 0, "retention_days": 90, "profile": {"v": 1, "about": "x"}}
    with pytest.raises(ArticleError, match="profile@"):
        node.accept(manifest_article(me, make_group_id("dk.snak", me.public_key),
                                     elsewhere, BITS).to_bytes())


# --- clients --------------------------------------------------------------------

async def test_publish_read_change_and_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = _node(avatars="accept")
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    me, reader = session("me"), session("reader")
    key = me.identity().key_text
    assert await reader.profile_of(key) is None                 # none yet: not an error
    assert not me.has_published_profile()

    await me.publish_profile(prof.make_profile("Hej fra mig", [{"kind": "github", "value": "andlo"}]))
    assert me.has_published_profile() and me.my_profile()["about"] == "Hej fra mig"
    got = await reader.profile_of(key)                          # cached as "none" ...
    assert got is None
    got = await reader.profile_of(key, refresh=True)            # ... until refreshed
    assert got.about == "Hej fra mig" and got.links[0]["value"] == "andlo"

    second = await me.publish_profile(prof.make_profile("Ny tekst", bot=True))
    assert second["serial"] == 2
    got = await reader.profile_of(key, refresh=True)
    assert got.about == "Ny tekst" and got.bot

    await me.publish_picture(_picture(alt="a drawing"))
    assert (await reader.picture_of(key))["alt"] == "a drawing"

    # both groups are ours and key-bound, so they are renewed with the inbox
    assert sorted(me.key_bound_groups()) == sorted([prof.profile_id(me.identity().public_key),
                                                     prof.avatar_id(me.identity().public_key)])

    await me.publish_profile(None)
    assert await reader.profile_of(key, refresh=True) is None and me.my_profile() is None

    reader.hide_profile(key)
    assert reader.profile_hidden(key)
    for s in (me, reader):
        await s.close()
    server.close()
