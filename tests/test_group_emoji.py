"""UN-RFC 0056: a group's own emoji, in <name>.emoji@<fp> - the rules of a set, the
node's (off by default, reserved names, refusal lists), and the owner publishing and a
reader reading them."""

import io

import pytest
from PIL import Image

from unseenet.client.session import SessionError
from unseenet.core import group_emoji as ge
from unseenet.core import crypto
from unseenet.core.encoding import b64decode
from unseenet.core.groups import Manifest

from test_localapi_owner import _setup


def _png(colour=(200, 120, 40, 255), size=(300, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", size, colour).save(out, "PNG")
    return out.getvalue()


def test_names_ids_and_the_set():
    fp = crypto.Identity.generate().fingerprint
    assert ge.emoji_group_id(f"dk.snak.marsvin@{fp}") == f"dk.snak.marsvin.emoji@{fp}"
    assert ge.main_group_of(f"dk.snak.marsvin.emoji@{fp}") == f"dk.snak.marsvin@{fp}"
    assert ge.main_group_of(f"dk.snak@{fp}") is None
    assert ge.is_emoji_name("a.emoji") and not ge.is_emoji_name("emoji")
    ge.check_name("marsvin")
    for bad in ("tada", "x", "Marsvin", "a b", "x" * 33):     # a standard name, or not a name
        with pytest.raises(ge.EmojiError):
            ge.check_name(bad)
    from unseenet.client.session import Session
    pic = Session.make_group_emoji(_png(), "  A guinea pig  ")
    assert pic["px"] == 32 and pic["alt"] == "A guinea pig" and pic["type"] in ge.TYPES
    raw = b64decode(pic["data"])
    assert len(raw) <= ge.MAX_OCTETS
    img = Image.open(io.BytesIO(raw))
    assert img.size == (32, 32) and not img.info.get("exif")
    with pytest.raises(ge.EmojiError):                       # at most 16
        ge.check_set({f"e{i:02d}": pic for i in range(17)})
    # a reader leaves out what is wrong; a node or the owner refuses the whole set
    mixed = {"marsvin": pic, "tada": pic, "big": {**pic, "px": 64}}
    assert set(ge.check_set(mixed, strict=False)) == {"marsvin"}
    with pytest.raises(ge.EmojiError):
        ge.check_set(mixed)
    ident = crypto.Identity.generate()
    gid = f"dk.test@{ident.fingerprint}"
    art = ge.emoji_manifest(ident, gid, {f"e{i:02d}": pic for i in range(16)})
    assert len(art.to_bytes()) <= ge.MANIFEST_MAX                # sixteen fit every node
    m = Manifest.from_article(art)
    assert m.view == "data" and set(ge.emoji_of(m)) == {f"e{i:02d}" for i in range(16)}


async def test_the_node_carries_them_only_when_turned_on(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)       # emoji: refuse
    gid = (await api.create_group({"name": "dk.test", "type": "open"}))["id"]
    pic = owner.make_group_emoji(_png())
    with pytest.raises(SessionError, match="does not carry group emoji"):
        await owner.set_group_emoji(gid, {"marsvin": pic})
    await owner.close()
    await other.close()
    server.close()


async def test_owner_publishes_and_a_reader_reads(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch, emoji="accept")
    gid = (await api.create_group({"name": "dk.test", "type": "open"}))["id"]
    pic = owner.make_group_emoji(_png(), "A guinea pig")
    assert owner.group_emoji_possible(gid)
    with pytest.raises(SessionError, match="standard emoji"):
        await owner.set_group_emoji(gid, {"tada": pic})
    assert await owner.set_group_emoji(gid, {"marsvin": pic}) == {"marsvin": pic}
    assert ge.emoji_group_id(gid) not in owner.data["subscribed"]      # read, not followed
    other.subscribe(gid)
    await other.fetch_unknown_manifests()
    assert other.group_emoji(gid) == {}
    assert await other.fetch_group_emoji(gid) == {"marsvin": pic}
    with pytest.raises(SessionError):                                    # not the owner
        await other.set_group_emoji(gid, {})
    assert await owner.set_group_emoji(gid, {}) == {}                    # taken away
    assert await other.fetch_group_emoji(gid) == {}
    with pytest.raises(SessionError, match="kept for a group's emoji"):  # reserved (3.1)
        await api.create_group({"name": "dk.test.emoji", "type": "open"})
    await owner.close()
    await other.close()
    server.close()


async def test_not_in_a_closed_group(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch, emoji="accept")
    gid = (await api.create_group({"name": "dk.lukket", "type": "closed"}))["id"]
    assert not owner.group_emoji_possible(gid)
    with pytest.raises(SessionError, match="cannot have its own emoji"):
        await owner.set_group_emoji(gid, {"marsvin": owner.make_group_emoji(_png())})
    await owner.close()
    await other.close()
    server.close()


async def test_the_node_refuses_what_is_not_an_emoji_group(tmp_path, monkeypatch):
    from unseenet.core.groups import make_manifest, manifest_article
    server, owner, other, api = await _setup(tmp_path, monkeypatch, emoji="accept",
                                             new_groups="accept")
    ident = owner.identity()
    pic = owner.make_group_emoji(_png())
    plain = make_manifest(ident, "dk.fake.emoji", "open", pow_bits=8)      # an ordinary group
    with pytest.raises(Exception, match="emoji group is a data channel"):
        await owner._post_article(plain)
    data = {"v": 1, "name": "dk.plain", "type": "open", "owner": ident.key_text, "serial": 1,
            "min_pow": 0, "retention_days": 7, "emoji": {"marsvin": pic}}
    with pytest.raises(Exception, match="belongs in a <name>.emoji group"):
        await owner._post_article(manifest_article(ident, f"dk.plain@{ident.fingerprint}", data, 8))
    await owner.close()
    await other.close()
    server.close()


async def test_through_the_local_api(tmp_path, monkeypatch):
    import base64
    from unseenet.client.localapi import LocalAPI
    server, owner, other, api = await _setup(tmp_path, monkeypatch, emoji="accept")
    gid = (await api.create_group({"name": "dk.test", "type": "open"}))["id"]
    data = base64.b64encode(_png()).decode()
    prev = (await api.change_group_emoji(gid, {"preview": {"data": data, "alt": "Et marsvin"}}))["picture"]
    assert prev["px"] == 32 and api.group(gid)["group"]["emoji"] == {}      # nothing published
    got = await api.change_group_emoji(gid, {"add": {"name": ":marsvin:", "data": data, "alt": "Et marsvin"}})
    assert set(got["emoji"]) == {"marsvin"}
    got = await api.change_group_emoji(gid, {"rename": {"from": "marsvin", "to": "gris"}})
    got = await api.change_group_emoji(gid, {"alt": {"name": "gris", "alt": "En gris"}})
    assert got["emoji"]["gris"]["alt"] == "En gris"
    head = api.group(gid)["group"]
    assert head["emoji_possible"] and set(head["emoji"]) == {"gris"}
    with pytest.raises(SessionError, match="standard emoji"):
        await api.change_group_emoji(gid, {"add": {"name": "smile", "data": data}})
    theirs = LocalAPI(session=other)
    other.subscribe(gid)
    await other.fetch_unknown_manifests()
    assert set((await theirs.group_emoji(gid))["emoji"]) == {"gris"}
    got = await api.change_group_emoji(gid, {"remove": "gris"})
    assert got["emoji"] == {}
    await owner.close()
    await other.close()
    server.close()
