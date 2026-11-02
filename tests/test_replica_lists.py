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
    clock = [(datetime.now(timezone.utc) - timedelta(days=20)).replace(
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


async def found_lists(sessions, when):
    keys = [s.identity().key_text for s in sessions]
    a = sessions[0]
    groups = {}
    for part, kind in (("claims", "open"), ("reports", "channel"), ("nodes", "channel")):
        g, body = a.council_genesis(f"unseenet.lists.{part}", kind, keys,
                                    fields={"min_pow": 0}, date=when)
        for s in sessions:
            await s.council_sign(g, body)
        groups[part] = g
    fields = {"min_pow": 0, "lists": {"nodes": groups["nodes"]}, "claims": groups["claims"],
              "reports": groups["reports"], "min_software": {"unseenet": "0.1.0"}}
    gid, body = a.council_genesis("unseenet.lists", "channel", keys, fields=fields, date=when)
    for s in sessions:
        await s.council_sign(gid, body)
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
    assert reps[0].st["lists"]["verdicts"][nk].startswith("reached on")
    # and the operator reads it in plain words
    from unseenet.replica.cli import explain
    text = "\n".join(explain(status, {"lists": gid}))
    assert "list council" in text and "holds 1" in text
