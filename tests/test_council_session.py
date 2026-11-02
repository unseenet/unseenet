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


async def test_a_council_with_a_founding_period(net, tmp_path, capsys):
    a, b = net("andreas"), net("bente")
    draft = tmp_path / "dk.lister.council.json"
    await cli.c_council(App(a), Namespace(
        json=False, identity=None, what="create", name="dk.lister", type="channel",
        member=[b.identity().key_text], title="", description="", min_pow=None,
        retention_days=None, min_level=None, sponsors=None, out=str(draft), sign=False,
        founding=3, founding_size=9))
    out = capsys.readouterr().out
    assert "Founding   until" in out and "founder:" in out and "(you)" in out
    gid = json.loads(draft.read_text())["group"]
    m = CouncilManifest.from_body(gid, json.loads(draft.read_text())["body"])
    assert m.founding.founder == a.identity().public_key and m.founding.size == 9
    with pytest.raises(SessionError, match="1 to 3 years"):
        a.council_genesis("dk.x", "open", [a.identity().key_text, b.identity().key_text],
                          founding_years=4)


async def test_a_council_with_a_room(net, tmp_path, capsys):
    """``council create --room``: the room's genesis goes in the same draft and is
    signed with it; the council names it (UN-RFC 0054 section 21)."""
    a, b = net("andreas"), net("bente")
    draft = tmp_path / "dk.lister.council.json"
    await cli.c_council(App(a), Namespace(
        json=True, identity=None, what="create", name="dk.lister", type="channel",
        member=[b.identity().key_text], title="", description="", min_pow=None,
        retention_days=None, min_level=None, sponsors=None, out=str(draft), sign=True,
        room=True))
    capsys.readouterr()
    d = json.loads(draft.read_text())
    room = d["also"][0]["group"]
    assert room.startswith("dk.lister.room@")
    assert CouncilManifest.from_body(d["group"], d["body"]).room == room
    await cli.c_council(App(b), Namespace(json=True, identity=None, what="sign",
                                          draft=str(draft), yes=True))
    capsys.readouterr()
    assert (await a.council_chain(room)).current.type == "closed"
    assert (await a.council_chain(d["group"])).current.room == room


async def test_a_registrar_council_drafted_by_its_founder(net, tmp_path, capsys):
    """``council create --without-me --founder KEY --claims``: the draft for a council
    registrar (UN-RFC 0054 section 14), made by its founder, who is not a member; the
    claims group is in the same draft and named by the council."""
    a, b, c, f = net("a"), net("b"), net("c"), net("founder")
    draft = tmp_path / "unseenet.names.council.json"
    await cli.c_council(App(f), Namespace(
        json=True, identity=None, what="create", name="unseenet.names", type="channel",
        member=[x.identity().key_text for x in (a, b, c)], title="", description="",
        min_pow=None, retention_days=None, min_level=3, sponsors=None, out=str(draft),
        sign=True, founding=3, founding_size=9, founder=f.identity().key_text,
        without_me=True, claims=True))
    capsys.readouterr()
    d = json.loads(draft.read_text())
    m = CouncilManifest.from_body(d["group"], d["body"])
    assert f.identity().public_key not in m.keys and len(m.keys) == 3
    assert m.founding.founder == f.identity().public_key and m.min_level == 3
    claims = d["also"][0]["group"]
    assert claims.startswith("unseenet.names.claims@") and m.data["claims"] == claims
    assert not (await f.council_copies(d["group"]))          # not a member: nothing posted


async def test_a_list_council_with_its_import(net, tmp_path, capsys):
    """``council create --lists nodes --groups --import nodes.json``: a list council
    (UN-RFC 0020 sections 4, 9, 10) - its node list, reports and claims groups in the
    draft, and the import named by its hash, posted in the council group on signing."""
    from unseenet.core import lists as ls
    a, b = net("a"), net("b")
    nodes = tmp_path / "nodes.json"
    nodes.write_text(json.dumps({"v": 1, "updated": "2026-10-17", "nodes": [
        {"name": "n1", "address": "a" * 56 + ".onion", "node_key": "ed25519:" + "k" * 52}]}))
    draft = tmp_path / "unseenet.lists.council.json"
    await cli.c_council(App(a), Namespace(
        json=True, identity=None, what="create", name="unseenet.lists", type="channel",
        member=[b.identity().key_text], title="", description="", min_pow=None,
        retention_days=None, min_level=3, sponsors=None, out=str(draft), sign=True,
        groups=True, lists="nodes", import_file=str(nodes)))
    capsys.readouterr()
    d = json.loads(draft.read_text())
    m = CouncilManifest.from_body(d["group"], d["body"])
    lc = ls.list_council(m.data)
    assert lc.lists["nodes"].startswith("unseenet.nodes@")
    assert lc.reports.startswith("unseenet.lists.reports@")
    assert lc.claims.startswith("unseenet.lists.claims@")
    assert {"proposals", "talk", "log"} <= set(m.data)
    (post,) = d["posts"]
    assert post["group"] == d["group"] and ls.import_hash(post["body"]) == lc.import_id
    assert set(ls.imported_nodes(post["body"])) == {"ed25519:" + "k" * 52}
    await cli.c_council(App(b), Namespace(json=True, identity=None, what="sign",
                                          draft=str(draft), yes=True))
    capsys.readouterr()
    assert (await a.council_chain(d["group"])).current is not None
    bodies = [x.body for x in await a.fetch_group(d["group"]) if x.readable]
    assert sum(ls.import_hash(x) == lc.import_id for x in bodies if x) == 1   # the last signer's


async def test_a_list_council_adds_the_root_list(net, tmp_path, capsys):
    """``council add-list <council> root --import hierarchies.json``: the draft of the new
    list group, with the import posted in the council's group, and the manifest change
    (``lists`` and ``imports``) that a member proposes (UN-RFC 0020 sections 9, 10)."""
    from unseenet.core import lists as ls
    from unseenet.core import proposals as pr
    a, b = net("a"), net("b")
    draft = tmp_path / "unseenet.lists.council.json"
    await cli.c_council(App(a), Namespace(
        json=True, identity=None, what="create", name="unseenet.lists", type="channel",
        member=[b.identity().key_text], title="", description="", min_pow=None,
        retention_days=None, min_level=3, sponsors=None, out=str(draft), sign=True,
        groups=True, lists="nodes", import_file=None))
    await cli.c_council(App(b), Namespace(json=True, identity=None, what="sign",
                                          draft=str(draft), yes=True))
    capsys.readouterr()
    gid = json.loads(draft.read_text())["group"]
    root = tmp_path / "hierarchies.json"
    root.write_text(json.dumps({"v": 1, "updated": "2026-10-31", "hierarchies": [
        {"name": "alt", "policy": "free", "title": "Anything goes"}]}))
    out = tmp_path / "unseenet.hierarchies.council.json"
    await cli.c_council(App(a), Namespace(json=True, identity=None, what="add-list",
                                          council=gid, kind="root", import_file=str(root),
                                          out=str(out)))
    capsys.readouterr()
    d = json.loads(out.read_text())
    assert d["group"].startswith("unseenet.hierarchies@")
    change = json.loads(out.with_name("unseenet.hierarchies.change.json").read_text())
    fields = change["manifest"]["fields"]
    assert fields["lists"]["root"] == d["group"] and "nodes" in fields["lists"]
    (post,) = d["posts"]
    assert post["group"] == gid and ls.import_hash(post["body"]) == fields["imports"]["root"]
    assert "alt" in ls.imported_root(post["body"])
    pr.make_proposal(gid, 1, change, "the council keeps the root list")      # a valid change
    # the manifest it makes is a list council with both lists
    cur = (await a.council_chain(gid)).current
    lc = ls.list_council({**cur.data, **fields})
    assert set(lc.lists) == {"nodes", "root"} and ls.import_for(lc, "root") == fields["imports"]["root"]


async def test_a_list_council_adds_the_entrance_list(net, tmp_path, capsys):
    """``council add-list <council> entrances``: the list group and, beside it, the open
    group where entrances announce themselves (UN-RFC 0020 section 5.1), both in the
    draft; the change names them in ``lists`` and ``announce``."""
    from unseenet.core import lists as ls
    from unseenet.core import proposals as pr
    a, b = net("a"), net("b")
    draft = tmp_path / "unseenet.lists.council.json"
    await cli.c_council(App(a), Namespace(
        json=True, identity=None, what="create", name="unseenet.lists", type="channel",
        member=[b.identity().key_text], title="", description="", min_pow=None,
        retention_days=None, min_level=3, sponsors=None, out=str(draft), sign=True,
        groups=True, lists="nodes", import_file=None))
    await cli.c_council(App(b), Namespace(json=True, identity=None, what="sign",
                                          draft=str(draft), yes=True))
    capsys.readouterr()
    gid = json.loads(draft.read_text())["group"]
    out = tmp_path / "unseenet.entrances.council.json"
    await cli.c_council(App(a), Namespace(json=True, identity=None, what="add-list",
                                          council=gid, kind="entrances", import_file=None,
                                          out=str(out)))
    capsys.readouterr()
    d = json.loads(out.read_text())
    assert d["group"].startswith("unseenet.entrances@")
    (also,) = d["also"]
    assert also["group"].startswith("unseenet.entrances.announce@")
    assert CouncilManifest.from_body(also["group"], also["body"]).type == "open"
    change = json.loads(out.with_name("unseenet.entrances.change.json").read_text())
    fields = change["manifest"]["fields"]
    assert fields["lists"]["entrances"] == d["group"]
    assert fields["announce"] == {"entrances": also["group"]}
    pr.make_proposal(gid, 1, change, "the council keeps the entrance list")
    cur = (await a.council_chain(gid)).current
    lc = ls.list_council({**cur.data, **fields})
    assert set(lc.lists) == {"nodes", "entrances"} and lc.announce["entrances"] == also["group"]


async def test_a_list_council_created_with_entrances(net, tmp_path, capsys):
    from unseenet.core import lists as ls
    a, b = net("a"), net("b")
    draft = tmp_path / "x.lists.council.json"
    await cli.c_council(App(a), Namespace(
        json=True, identity=None, what="create", name="x.lists", type="channel",
        member=[b.identity().key_text], title="", description="", min_pow=None,
        retention_days=None, min_level=3, sponsors=None, out=str(draft), sign=False,
        groups=False, lists="nodes,entrances", import_file=None))
    capsys.readouterr()
    d = json.loads(draft.read_text())
    lc = ls.list_council(CouncilManifest.from_body(d["group"], d["body"]).data)
    assert lc.announce["entrances"].startswith("x.entrances.announce@")
    assert lc.announce["entrances"] in {x["group"] for x in d["also"]}


async def test_an_entrance_announces_itself(net, tmp_path, capsys):
    """``council announce-entrance``: the operator's entrance key posts its announcement
    in the council's announcement group (UN-RFC 0020 section 5.1)."""
    from unseenet.core import entrances as en
    a, b, e = net("a"), net("b"), net("e")
    draft = tmp_path / "x.lists.council.json"
    await cli.c_council(App(a), Namespace(
        json=True, identity=None, what="create", name="x.lists", type="channel",
        member=[b.identity().key_text], title="", description="", min_pow=None,
        retention_days=None, min_level=3, sponsors=None, out=str(draft), sign=True,
        groups=False, lists="nodes,entrances", import_file=None))
    await cli.c_council(App(b), Namespace(json=True, identity=None, what="sign",
                                          draft=str(draft), yes=True))
    capsys.readouterr()
    gid = json.loads(draft.read_text())["group"]
    onion = "e" * 56 + ".onion"
    await cli.c_council(App(e), Namespace(
        json=True, identity=None, what="announce-entrance", council=gid, onion=onion,
        url="https://web.example/", publisher=None, name="web", operator="@e",
        contact=None, description="A test entrance"))
    out = json.loads(capsys.readouterr().out)
    assert out["key"] == e.identity().key_text
    (m,) = [x for x in await a.fetch_group(out["group"]) if x.readable]
    got = en.parse(m.body, key=m.author_key, date=m.date)
    assert got.key == e.identity().key_text and got.onion == onion
    assert got.publisher.startswith("unseenet.releases@") and got.description == "A test entrance"
    with pytest.raises(SystemExit):
        await cli.c_council(App(e), Namespace(
            json=True, identity=None, what="announce-entrance", council=gid, onion=None,
            url=None, publisher=None, name=None, operator=None, contact=None, description=None))


async def test_a_list_council_adds_the_gateway_directory(net, tmp_path, capsys):
    """``council add-directory <council> gateways``: an open data group of the council
    where gateways announce themselves (UN-RFC 0038 section 6.1), and the change naming
    it in ``announce``."""
    from unseenet.core import lists as ls
    from unseenet.core import proposals as pr
    a, b = net("a"), net("b")
    draft = tmp_path / "unseenet.lists.council.json"
    await cli.c_council(App(a), Namespace(
        json=True, identity=None, what="create", name="unseenet.lists", type="channel",
        member=[b.identity().key_text], title="", description="", min_pow=None,
        retention_days=None, min_level=3, sponsors=None, out=str(draft), sign=True,
        groups=True, lists="nodes", import_file=None))
    await cli.c_council(App(b), Namespace(json=True, identity=None, what="sign",
                                          draft=str(draft), yes=True))
    capsys.readouterr()
    gid = json.loads(draft.read_text())["group"]
    out = tmp_path / "gw.council.json"
    await cli.c_council(App(a), Namespace(json=True, identity=None, what="add-directory",
                                          council=gid, kind="gateways", out=str(out)))
    capsys.readouterr()
    d = json.loads(out.read_text())
    m = CouncilManifest.from_body(d["group"], d["body"])
    assert d["group"].startswith("unseenet.gateways@") and m.type == "open"
    assert m.data["view"] == "data"
    change = json.loads(out.with_name("unseenet.gateways.change.json").read_text())
    assert change["manifest"]["fields"]["announce"] == {"gateways": d["group"]}
    pr.make_proposal(gid, 1, change, "the council keeps the gateway directory")
    cur = (await a.council_chain(gid)).current
    lc = ls.list_council({**cur.data, **change["manifest"]["fields"]})
    assert lc.announce["gateways"] == d["group"]
