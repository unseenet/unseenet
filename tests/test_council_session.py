"""Council groups from the client: a new council from a draft, each member signing it,
counting the chain in the client, and the command line (UN-RFC 0054 Part I, #688)."""

import json
from argparse import Namespace
from datetime import timedelta

import pytest

import unseenet.client.session as sess
from unseenet import cli
from unseenet.client.session import Session, SessionError
from unseenet.core.council import CouncilManifest, next_body
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}
BITS = 8


@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
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


class App:
    def __init__(self, s):
        self.session = s


async def test_a_council_from_a_draft_to_a_manifest(net):
    a, b, c = net("andreas"), net("bente"), net("carl")
    gid, body = a.council_genesis("dk.lister", "channel",
                                  [x.identity().key_text for x in (a, b, c)],
                                  fields={"title": "Lister", "min_pow": 0})
    await a.council_sign(gid, body)
    await b.council_sign(gid, body)
    assert await c.fetch_manifest(gid) is None          # not every member yet
    await c.council_sign(gid, body)
    m = await c.fetch_manifest(gid)
    assert m is not None and m.is_council and m.title == "Lister"

    # a later manifest: two of three is a majority
    g = CouncilManifest.from_body(gid, body)
    b2 = next_body(g, date=g.date + timedelta(days=1), title="Lister i Danmark")
    await a.council_sign(gid, b2)
    assert (await b.fetch_manifest(gid)).serial == 1
    await b.council_sign(gid, b2)
    assert (await c.fetch_manifest(gid)).title == "Lister i Danmark"


async def test_signing_says_why_it_would_not_count(net):
    a, b, outsider = net("andreas"), net("bente"), net("ole")
    gid, body = a.council_genesis("dk.raad", "open", [a.identity().key_text, b.identity().key_text])
    with pytest.raises(SessionError, match="not one of its members"):
        await outsider.council_sign(gid, body)
    with pytest.raises(SessionError, match="at least 2 members"):
        a.council_genesis("dk.alene", "open", [a.identity().key_text])
    await a.council_sign(gid, body)
    await b.council_sign(gid, body)
    g = CouncilManifest.from_body(gid, body)
    wrong = next_body(g, date=g.date + timedelta(days=1), members=g.members[:1])
    with pytest.raises(SessionError, match="fewer than 2 full members"):
        await a.council_sign(gid, wrong)


async def test_the_command_line(net, tmp_path, capsys):
    a, b = net("andreas"), net("bente")
    draft = tmp_path / "dk.lister.council.json"
    await cli.c_council(App(a), Namespace(
        json=True, identity=None, what="create", name="dk.lister", type="channel",
        member=[b.identity().key_text], title="Lister", description="", min_pow=None,
        retention_days=None, min_level=None, sponsors=None, out=str(draft), sign=True))
    gid = json.loads(capsys.readouterr().out)["group"]
    await cli.c_council(App(b), Namespace(json=True, identity=None, what="show", group=gid))
    shown = json.loads(capsys.readouterr().out)
    assert shown["seq"] == 0 and shown["missing"] == [b.identity().key_text]
    await cli.c_council(App(b), Namespace(json=True, identity=None, what="sign",
                                          draft=str(draft), yes=True))
    capsys.readouterr()
    await cli.c_council(App(a), Namespace(json=True, identity=None, what="show", group=gid))
    shown = json.loads(capsys.readouterr().out)
    assert shown["seq"] == 1 and len(shown["members"]) == 2
