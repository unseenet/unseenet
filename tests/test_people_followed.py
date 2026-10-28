"""#706: what you follow because of a person sits under that person - feed and site
together, by name - not as hierarchies called feed and site."""

from unseenet.client.localapi import LocalAPI

from test_localapi_owner import _setup


async def test_a_persons_feed_and_site_together(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch, sites="accept")
    feed = (await api.start_feed({"comments": "open"}))["id"]
    site = await owner.start_personal_group("site")
    await owner.put_page(site, "index", "# Hej\n")
    key = owner.identity().key_text
    theirs = LocalAPI(session=other)
    await theirs.set_following({"person": key})
    other.subscribe(site)
    await other.fetch_unknown_manifests()
    d = theirs.groups()
    [p] = d["people_followed"]
    assert p["key"] == key and p["groups"] == {"feed": feed, "site": site}
    assert p["label"] and p["fingerprint"] == owner.identity().fingerprint
    assert not {h["name"] for h in d["hierarchies"]} & {"feed", "site"}
    # your own feed is not among the people you follow
    assert api.groups()["people_followed"] == []
    await owner.close()
    await other.close()
    server.close()
