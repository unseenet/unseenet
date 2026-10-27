"""UN-RFC 0045 through the local client API and the command line (#122, CLI parity #578)."""

import json
from argparse import Namespace

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session, SessionError
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
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


async def test_reports_through_the_local_api(net):
    from unseenet.client.localapi import LocalAPI
    from unseenet.client.localapi import server as srv
    issuer, owner, spammer, me = net("issuer"), net("owner"), net("spammer"), net("me")
    api, iapi = LocalAPI(session=me), LocalAPI(session=issuer)
    gid = await owner.create_group("alt.snak", "open", min_pow=8)
    spammer.subscribe(gid)
    await spammer.post(gid, "Ure", "køb\n")
    assert iapi.reports()["mine"] is None and "spam" in iapi.reports()["reasons"]
    mine = (await iapi.start_reports({"policy": "Spam", "automatic": True}))["mine"]
    assert mine["policy"] == "Spam" and mine["automatic"] is True
    assert iapi.settings()["report_issuer"] is True and api.settings()["report_issuer"] is False
    spam = next(m for m in await issuer.fetch_group(gid) if m.subject == "Ure")
    rid = (await iapi.publish_report({"posts": [{"id": spam.message_id, "group": gid}],
                                      "keys": [{"key": spammer.identity().key_text, "days": 30}]}))["id"]
    [r] = (await iapi.my_reports())["reports"]
    assert r["id"] == rid and r["keys"][0]["key"] == spammer.identity().key_text
    with pytest.raises(SessionError, match="days"):
        await iapi.publish_report({"keys": [{"key": spammer.identity().key_text, "days": 400}]})

    me.subscribe(gid)
    got = await api.follow_issuer({"key": issuer.identity().key_text, "label": "Jægeren"})
    assert got["issuers"][0]["label"] == "Jægeren" and got["issuers"][0]["on"]
    [shown] = [m.to_dict() for m in me.visible(await me.fetch_group(gid))]
    assert shown["reported"]["reason"] == "spam" and shown["reported"]["automatic"] is True
    api.show_reported(gid, {"id": spam.message_id})
    assert me.visible(await me.fetch_group(gid))[0].to_dict()["reported"] is None
    await api.follow_issuer({"key": issuer.identity().key_text, "on": False})
    assert api.reports()["issuers"] == []
    await iapi.withdraw_report({"id": rid})
    assert (await iapi.my_reports())["reports"] == []
    routes = {(m, p) for m, p, _ in srv.ROUTES}
    assert {("GET", "/api/reports"), ("POST", "/api/reports/follow"), ("POST", "/api/reports/publish"),
            ("POST", "/api/reports/start"), ("GET", "/api/reports/mine"), ("POST", "/api/reports/withdraw"),
            ("GET", "/api/reports/received"), ("POST", "/api/reports/hierarchy"),
            ("POST", "/api/reports/refresh"), ("POST", "/api/groups/{gid}/show")} <= routes


async def test_reports_from_the_command_line(net, capsys):
    from unseenet import cli
    issuer, owner, spammer = net("issuer"), net("owner"), net("spammer")
    gid = await owner.create_group("alt.snak", "open", min_pow=8)
    spammer.subscribe(gid)
    await spammer.post(gid, "Ure", "køb\n")

    class App:                                          # the CLI's App around a session
        def __init__(self, s):
            self.session = s

    def ns(**kw):
        return Namespace(json=True, identity=None, **kw)

    def out():
        return json.loads(capsys.readouterr().out)

    i = App(issuer)
    await cli.c_reports(i, ns(what="start", policy="Spam", contact="", automatic=False))
    assert out()["group"] == issuer.my_reports_group()
    spam = next(m for m in await issuer.fetch_group(gid) if m.subject == "Ure")
    await cli.c_reports(i, ns(what="publish", post=[[gid, spam.message_id]], key=[],
                              reason="spam", days=365, note="ure"))
    rid = out()["id"]
    await cli.c_reports(i, ns(what="mine"))
    assert [r["id"] for r in out()] == [rid]

    reader = App(net("reader"))
    reader.session.subscribe(gid)
    await cli.c_reports(reader, ns(what="follow", key=issuer.identity().key_text, label=""))
    assert out()["read"] == 1
    await cli.c_reports(reader, ns(what="hidden", group=gid))
    [row] = out()
    assert row["id"] == spam.message_id and row["reason"] == "spam"
    await cli.c_reports(reader, ns(what="issuers"))
    assert out()[0]["yours"] is True
    await cli.c_reports(i, ns(what="withdraw", msgid=rid))
    assert out()["id"] == rid
