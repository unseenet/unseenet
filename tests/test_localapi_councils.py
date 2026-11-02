"""#841: councils in the local client API (UN-RFC 0046 section 4.26) - a genesis and who
still has to sign, signing it, the council in plain fields, and acting in it, with the
same checks as ``unseenet council``."""

import pytest

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI
from unseenet.client.localapi import server as srv
from unseenet.client.localapi.api import NotFound
from unseenet.client.session import Session, SessionError
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    made = []

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title())
        p.add_node(addr)
        made.append(p)
        return p
    yield person
    for p in made:
        await p.close()
    server.close()


async def test_a_council_through_the_api(net):
    a, b, c = net("andreas"), net("bente"), net("carl")
    keys = [x.identity().key_text for x in (a, b)]
    gid, body = a.council_genesis("dk.raad", "open", keys, founding_years=1)
    api_a, api_b, api_c = LocalAPI(session=a), LocalAPI(session=b), LocalAPI(session=c)
    with pytest.raises(NotFound):
        await api_a.council(gid)
    got = await api_a.council_post({"group": gid, "action": "sign", "body": body})
    assert got["posted"] and "every member" in got["text"]
    shown = await api_b.council(gid)
    assert shown["counts"] is False and shown["missing"] == [b.identity().key_text]
    assert [m["you"] for m in shown["members"]] == [False, True]
    await api_b.council_post({"group": gid, "action": "sign", "body": body})
    shown = await api_c.council(gid)
    assert shown["counts"] and not shown["disputed"] and shown["seq"] == 1
    assert shown["full"] == 2 and shown["you"] is None and shown["max_members"] == 16
    assert shown["founding"]["founder"] == keys[0] and shown["founding"]["lasts"]
    assert not shown["founding"]["you"]
    assert (await api_a.council(gid))["founding"]["you"]
    assert (await api_a.council(gid))["you"] == "full member"

    # acting: the session's checks, in plain words
    with pytest.raises(SessionError, match="founder"):
        await api_b.council_post({"group": gid, "action": "admit", "key": c.identity().key_text})
    with pytest.raises(SessionError, match="not a member"):
        await api_c.council_post({"group": gid, "action": "resign"})
    with pytest.raises(SessionError, match="why"):
        await api_c.council_post({"group": gid, "action": "object",
                                  "key": b.identity().key_text})
    got = await api_a.council_post({"group": gid, "action": "admit",
                                    "key": c.identity().key_text})
    assert got["posted"] and "admit" in got["text"] and got["council"]["counts"]
    got = await api_c.council_post({"group": gid, "action": "object",
                                    "key": b.identity().key_text, "reason": "fordi"})
    assert "Everybody can see it" in got["text"]
    with pytest.raises(SessionError, match="action is one of"):
        await api_a.council_post({"group": gid, "action": "steal"})
    assert (await api_a.council_hearings(gid)) == {"group": gid, "hearings": []}


def test_the_routes_are_there():
    routes = {(m, p) for m, p, _ in srv.ROUTES}
    assert {("GET", "/api/council"), ("POST", "/api/council"),
            ("GET", "/api/council/hearings")} <= routes
