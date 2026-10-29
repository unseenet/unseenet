"""unseenet#771: a key that arrives - copied, or restored from its words - finds its own
feed and site started, rather than *Start your feed* and *Start your site*.

A copy carries identities and closed groups' secrets (UN-RFC 0050 3.6), not the vault's
entries for these public, key-bound groups; their manifests on the network say they exist.
"""
from unseenet.client.localapi import LocalAPI
from unseenet.client.session import Session
from unseenet.core import recovery as rc
from unseenet.core.vault import Vault

from test_localapi_owner import KDF, _setup


async def test_a_restored_key_has_its_feed_and_site(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch, sites="accept")
    feed = (await api.start_feed({"comments": "open"}))["id"]
    site = await owner.start_personal_group("site")
    words = rc.words_from_seed(bytes.fromhex(owner.data["identities"]["owner"]["seed"]))

    # the same key in another vault: nothing about its feed and site there yet
    name, _ident, _new = other.restore_identity(words, "owner-copy")   # now the one in use
    theirs = LocalAPI(session=other)
    assert theirs.my_feed()["started"] is False and theirs.my_feed("site")["started"] is False

    # restoring reads the network, and takes them as started
    await other.restore_from_network(name)
    assert theirs.my_feed() == {**theirs.my_feed(), "id": feed, "started": True, "followed": True}
    assert theirs.my_feed("site")["id"] == site and theirs.my_feed("site")["started"] is True
    assert other.has_personal_group("feed") and other.has_personal_group("site")

    # nothing further to take over, and nothing taken from someone else's key
    assert await other.adopt_published_personal_groups([name]) == {name: [feed, site]}
    assert await owner.adopt_published_personal_groups(["owner"]) == {"owner": [feed, site]}
    for s in (owner, other):
        await s.close()
    server.close()


async def test_a_key_with_no_feed_or_site_is_left_as_it_is(tmp_path, monkeypatch):
    server, owner, other, _api = await _setup(tmp_path, monkeypatch)
    assert await other.adopt_published_personal_groups(["other"]) == {}
    assert not other.has_personal_group("feed") and not other.has_personal_group("site")
    for s in (owner, other):
        await s.close()
    server.close()


async def test_quiet_when_no_node_answers(tmp_path):
    s = Session(Vault.open(tmp_path / "alone.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("alone", "Alone")
    s.add_node("127.0.0.1:9")                        # nothing listens there
    assert await s.adopt_published_personal_groups(["alone"]) == {}
    await s.close()
