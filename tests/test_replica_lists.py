"""A list council's replicas against one local node, over simulated days (UN-RFC 0020,
#56): three replicas measure an announced node, post reports and canaries, and post
the same node list once the node has been reached on 5 of 7 days."""

import json
import random
from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
import unseenet.client.session.council as sess_council
import unseenet.client.session.posting as posting
import unseenet.replica.lists as rlists
import unseenet.replica.run as run_mod
from unseenet import known_nodes
from unseenet.client.session import Session
from unseenet.core import announcements as an
from unseenet.core import crypto
from unseenet.core import lists as ls
from unseenet.core.article import new_article
from unseenet.core.groups import Manifest, make_manifest
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig
from unseenet.replica.run import Replica

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def world(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    from unseenet.node import server as node_server
    monkeypatch.setattr(node_server, "POST_PAST", timedelta(days=3650))
    monkeypatch.setattr(Node, "_keep_old", lambda self, art, manifest: True)
    owner = crypto.Identity.generate()
    ann = make_manifest(owner, "unseenet.nodes.announce", "open", pow_bits=8)
    monkeypatch.setattr(known_nodes, "NODES_ANNOUNCE_GROUP", ann.group)
    monkeypatch.setattr(rlists, "NODES_ANNOUNCE_GROUP", ann.group)
    monkeypatch.setattr(ls, "_onion", lambda a: True)        # a local node, not an onion
    node = Node(Store(), NodeConfig(name="kvisten", min_pow=6, forward_delay=(0, 0)),
                key=crypto.Identity.generate())
    node.store.add(ann, ann.to_bytes())
    node.store.set_manifest(Manifest.from_article(ann))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    clock = [(datetime.now(timezone.utc) - timedelta(days=40)).replace(
        hour=21, minute=0, second=0, microsecond=0)]
    for mod in (posting, run_mod, sess_council, rlists):
        real = mod.new_article
        monkeypatch.setattr(mod, "new_article",
                            lambda *a, _real=real, **k: _real(*a, **{**k, "now": k.get("now") or clock[0]}))
    sessions = []
    for name in ("r1", "r2", "r3"):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        sessions.append(s)
    yield node, ann, addr, clock, sessions
    for s in sessions:
        await s.close()
    server.close()


async def found_lists(sessions, when, public=False, imported=None, root=None):
    keys = [s.identity().key_text for s in sessions]
    a = sessions[0]
    groups = {}
    parts = [("claims", "open"), ("reports", "channel"), ("nodes", "channel")]
    if root is not None:
        parts.append(("hierarchies", "channel"))
    if public:                                           # UN-RFC 0061 section 3
        parts += [("proposals", "open"), ("talk", "open"), ("log", "channel")]
    for part, kind in parts:
        g, body = a.council_genesis(f"unseenet.lists.{part}", kind, keys,
                                    fields={"min_pow": 0}, date=when)
        for s in sessions:
            await s.council_sign(g, body)
        groups[part] = g
    lists = {"nodes": groups["nodes"]}
    if root is not None:
        lists["root"] = groups["hierarchies"]
    fields = {"min_pow": 0, "lists": lists, "claims": groups["claims"],
              "reports": groups["reports"], "min_software": {"unseenet": "0.1.0"}}
    fields.update({k: groups[k] for k in ("proposals", "talk", "log") if k in groups})
    imp = None
    if imported is not None or root is not None:         # section 9
        imp = ls.import_body({k: v for k, v in (("nodes", imported), ("root", root)) if v})
        fields["import"] = ls.import_hash(imp)
    gid, body = a.council_genesis("unseenet.lists", "channel", keys, fields=fields, date=when)
    for s in sessions:
        await s.council_sign(gid, body)
    if imp:
        await sessions[-1].post(gid, ls.IMPORT_SUBJECT, imp)
    return gid, groups


def announce(node, ann, addr, when):
    body = an.make_body(f"test:{addr}", "kvisten", {"groups": ["*"]}, when)
    art = new_article(ann.group, an.subject("kvisten"), body, now=when, from_name="kvisten",
                      extra=[("Content-Type", "application/json")]).finalize(node.key, 8)
    node.store.add(art, art.to_bytes())


async def test_three_replicas_measure_report_and_list_a_node(world, tmp_path):
    node, ann, addr, clock, sessions = world
    gid, groups = await found_lists(sessions, clock[0] - timedelta(hours=21))
    announce(node, ann, addr, clock[0] - timedelta(hours=1))
    reps = [Replica(s, "unseenet.none@abcdefghijklmnop", now=lambda: clock[0],
                    rng=random.Random(k), levels=lambda k: 4, ripen=False,
                    config=lambda: {"lists": gid})
            for k, s in enumerate(sessions)]
    for _ in range(8):
        for r in reps:
            status = await r.run_once()
        clock[0] += timedelta(days=1)
    lst = status["lists"]
    assert lst["members"] == 3 and lst["announced"] == 1, lst
    nk = node.key.key_text
    # every replica reported every day, and found the node connected and complete
    reports = [m for m in await sessions[0].fetch_group(groups["reports"])
               if (m.subject or "").startswith(ls.REPORT_PREFIX)]
    assert len(reports) == 3 * 8
    last = ls.parse_report(reports[-1].body, key=reports[-1].author_key, date=reports[-1].date)
    assert nk in last.reached and nk not in last.disconnected and nk not in last.incomplete
    assert last.software[nk].startswith("unseenet ")
    # the node list: the three replicas computed the same, and it holds the node
    lists = [m for m in await sessions[0].fetch_group(groups["nodes"]) if m.readable]
    assert lists and {m.author_key for m in lists} <= {s.identity().key_text for s in sessions}
    newest = json.loads(lists[-1].body)
    assert [n["node_key"] for n in newest["nodes"]] == [nk]
    assert newest["updated"].startswith("council 1 day ")
    days = {}
    for m in lists:
        days.setdefault(json.loads(m.body)["updated"], set()).add(m.body)
    assert all(len(bodies) == 1 for bodies in days.values())   # same inputs, same list
    # listed the day before, it now keeps its place by the grace (section 6.1)
    assert reps[0].st["lists"]["verdicts"][nk] == "listed, and not down"
    # and the operator reads it in plain words
    from unseenet.replica.cli import explain
    text = "\n".join(explain(status, {"lists": gid}))
    assert "list council" in text and "holds 1" in text


async def test_a_list_decision_takes_a_node_off(world):
    """A ``remove`` proposal (UN-RFC 0020 section 6.7) passes its hearing, and the
    replicas leave the node off the list from the day it applies."""
    from unseenet.core import proposals as pr
    node, ann, addr, clock, sessions = world
    gid, groups = await found_lists(sessions, clock[0] - timedelta(hours=21), public=True)
    announce(node, ann, addr, clock[0] - timedelta(hours=1))
    reps = [Replica(s, "unseenet.none@abcdefghijklmnop", now=lambda: clock[0],
                    rng=random.Random(k), levels=lambda k: 4, ripen=False,
                    config=lambda: {"lists": gid})
            for k, s in enumerate(sessions)]

    async def days(n):
        for _ in range(n):
            for r in reps:
                await r.run_once()
            clock[0] += timedelta(days=1)

    await days(8)
    nk = node.key.key_text
    assert reps[0].st["lists"]["verdicts"][nk] == "listed, and not down"   # the grace, 6.1
    announce(node, ann, addr, clock[0] - timedelta(hours=2))     # it renews its announcement
    pid, body = pr.make_proposal(gid, 1, {"list": {"remove": {"list": "nodes", "entry": nk}}},
                                 "it serves spam to everybody")
    for s in sessions[:2]:
        await s.post(groups["proposals"], f"{pr.PROPOSAL} {pid}", body)
    await days(20)               # 14 days' hearing and a day's grace; the list lags 2 days
    sub = reps[2].st["lists"]["public"]
    assert [d[1] for d in sub["list_decisions"]] == [pid]
    assert reps[2].st["lists"]["verdicts"][nk] == "removed by a decision of the council"
    newest = [m for m in await sessions[0].fetch_group(groups["nodes"]) if m.readable][-1]
    assert json.loads(newest.body)["nodes"] == []
    logged = [m.subject for m in await sessions[0].fetch_group(groups["log"]) if m.readable]
    assert f"hearing {pid} closed" in logged
    # the registrar's own state was not touched
    assert "list_decisions" not in reps[2].st


async def test_an_imported_node_stays_until_it_announces(world):
    """Section 9: the genesis import keeps a node listed that has not announced itself
    yet; one that is announced and measured is listed by the rules beside it."""
    node, ann, addr, clock, sessions = world
    old = {"name": "old", "address": "b" * 56 + ".onion", "node_key": "ed25519:" + "q" * 52}
    gid, groups = await found_lists(sessions, clock[0] - timedelta(hours=21),
                                    imported={"v": 1, "updated": "2026-10-17", "nodes": [old]})
    announce(node, ann, addr, clock[0] - timedelta(hours=1))
    reps = [Replica(s, "unseenet.none@abcdefghijklmnop", now=lambda: clock[0],
                    rng=random.Random(k), levels=lambda k: 4, ripen=False,
                    config=lambda: {"lists": gid})
            for k, s in enumerate(sessions)]
    for _ in range(3):
        for r in reps:
            await r.run_once()
        clock[0] += timedelta(days=1)
    newest = [m for m in await sessions[0].fetch_group(groups["nodes"]) if m.readable][-1]
    assert [n["node_key"] for n in json.loads(newest.body)["nodes"]] == [old["node_key"]]
    assert reps[0].st["lists"]["verdicts"][old["node_key"]].startswith("imported at the genesis")


async def test_the_replicas_keep_the_root_list(world, tmp_path):
    """Sections 5.2 and 6.2: a user claims a hierarchy with a commit and a reveal in the
    claims group; the replicas post the same root list - the import's entries and the
    new grant."""
    from unseenet import hierarchies as hz
    from unseenet import names as nm
    from unseenet.core import hierarchy_claims as hc
    node, ann, addr, clock, sessions = world
    project = crypto.Identity.generate()
    root = {"v": 1, "updated": "2026-10-31", "hierarchies": [
        {"name": "unseenet", "policy": "governed", "maintainer": project.key_text,
         "list": f"unseenet.checkgroups@{project.fingerprint}", "title": "The Unseenet project"},
        {"name": "alt", "policy": "free", "title": "Anything goes"},
        {"name": "usenet", "policy": "reserved", "title": "Usenet"}]}
    gid, groups = await found_lists(sessions, clock[0] - timedelta(hours=21), root=root)
    user = Session(Vault.open(tmp_path / "user.vault", "pw", **KDF), status=lambda *_: None)
    user.new_identity("user", "User")
    user.add_node(addr)
    me = user.identity()
    claim = hc.make_claim("claim", "games", list=f"games.list@{me.fingerprint}", title="Games")
    commit, nonce = hc.make_commit(claim)
    cid = await user.post(groups["claims"], nm.COMMIT_SUBJECT, commit)
    clock[0] += timedelta(hours=2)
    await user.post(groups["claims"], nm.reveal_subject(cid),
                    hc.make_reveal(claim, nonce, f"inbox@{me.fingerprint}"))
    reps = [Replica(s, "unseenet.none@abcdefghijklmnop", now=lambda: clock[0],
                    rng=random.Random(k), levels=lambda k: 4, ripen=False,
                    tlds=lambda: {"dk", "com"}, dns_txt=lambda n: [],
                    config=lambda: {"lists": gid})
            for k, s in enumerate(sessions)]
    for _ in range(3):
        for r in reps:
            status = await r.run_once()
        clock[0] += timedelta(days=1)
    posted = [m for m in await sessions[0].fetch_group(groups["hierarchies"]) if m.readable]
    assert posted and {m.author_key for m in posted} <= {s.identity().key_text for s in sessions}
    assert len({m.body for m in posted}) == 1                 # the same list from all three
    _, got = hz.parse_root_list(posted[-1].body)
    assert got["games"].maintainer == me.key_text and got["games"].policy == "governed"
    assert got["unseenet"].maintainer == project.key_text
    assert got["alt"].policy == "free" and got["usenet"].policy == "reserved"
    assert status["lists"]["granted"] == 2
    await user.close()
