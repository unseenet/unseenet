"""#442: unseenet: addresses in the local client API (UN-RFC 0046 section 4.13, UN-RFC
0031 section 3.4.1), against a real node: the addresses in the answers, to copy, and
GET /api/address saying what any address names - the older join form too."""

import pytest

from unseenet.client.localapi import LocalAPI
from unseenet.client.localapi import server as srv
from unseenet.client.session import SessionError
from unseenet.core import addresses as addr

from test_localapi_owner import _setup


async def test_addresses_in_the_answers_and_opened(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    gid = (await api.create_group({"name": "dk.adr", "type": "open"}))["id"]
    mid = await owner.post(gid, "Velkommen", "tekst\n")
    await owner.fetch_group(gid)

    g = api.group(gid)
    assert g["group"]["address"] == f"unseenet:{gid}"           # no onion: no n= hint
    row = next(r for r in g["rows"] if r["message"]["id"] == mid)
    assert row["address"] == addr.post_address(gid, mid)
    key = other.identity().key_text
    assert (await api.profile(key))["address"] == f"unseenet:{other.identity().fingerprint}"

    got = await api.address(f"unseenet:{gid}")
    assert got["kind"] == "group" and got["available"] and got["followed"]
    assert got["group"]["id"] == gid and got["group"]["type"] == "open"

    got = await api.address(row["address"])
    assert got["kind"] == "post" and got["message"]["subject"] == "Velkommen"
    assert got["message"]["id"] == mid

    got = await api.address(f"unseenet:join?g={gid}")            # the older invitation form
    assert got["kind"] == "group" and got["address"] == f"unseenet:{gid}"

    # someone else's view: a group they do not follow yet, read from the node
    theirs = LocalAPI(session=other)
    got = await theirs.address(f"unseenet:{gid}")
    assert got["available"] and not got["followed"]

    fp = owner.identity().fingerprint                             # an identity: the key if known
    got = await theirs.address(f"unseenet:{fp}")
    assert got["kind"] == "identity" and got["key"] is None       # not met yet
    await other.fetch_group(gid)                                  # now they have read the owner
    got = await theirs.address(f"unseenet:{fp}")
    assert got["kind"] == "identity" and got["fingerprint"] == fp and not got["mine"]
    assert got["key"] == owner.identity().key_text                  # an author they have read
    assert (await api.address(f"unseenet:{fp}"))["mine"]

    gone = await api.address("unseenet:dk.findes.ikke@aaaaaaaaaaaaaaaa")
    assert gone["available"] is False
    with pytest.raises(SessionError, match="not an address"):
        await api.address("https://example.org")
    await owner.close()
    await other.close()
    server.close()


def test_the_route():
    assert ("GET", "/api/address") in [(m, p) for m, p, _ in srv.ROUTES]
