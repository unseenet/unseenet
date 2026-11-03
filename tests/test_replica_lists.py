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


async def found_lists(sessions, when, public=False, imported=None, root=None, entrances=False,
                      sources=None):
    keys = [s.identity().key_text for s in sessions]
    a = sessions[0]
    groups = {}
    parts = [("claims", "open"), ("reports", "channel"), ("nodes", "channel")]
    if root is not None:
        parts.append(("hierarchies", "channel"))
    if entrances:                                        # section 6.3
        parts += [("entrances", "channel"), ("entrances.announce", "open")]
    if sources is not None:                              # section 6.8
        parts.append(("sources", "channel"))
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
    if sources is not None:
        lists["sources"] = groups["sources"]
        fields["publishers"] = ["unseenet.releases@ph5fc5hop5232qsz"]
    if entrances:
        lists["entrances"] = groups["entrances"]
        fields["announce"] = {"entrances": groups["entrances.announce"]}
    fields.update({k: groups[k] for k in ("proposals", "talk", "log") if k in groups})
    imp = None
    if imported is not None or root is not None or sources is not None:   # section 9
        imp = ls.import_body({k: v for k, v in (("nodes", imported), ("root", root),
                                                 ("sources", sources)) if v})
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


async def test_dns_answers_are_decided_by_the_replicas_together(world, tmp_path):
    """#888 (UN-RFC 0020 section 6.2): a claim of a name equal to a top-level domain.
    One replica's DNS says no; the other two find the key. Each puts what it found in
    its daily report, and all three post the same root list, granting by the majority."""
    from unseenet import hierarchies as hz
    from unseenet import names as nm
    from unseenet.core import hierarchy_claims as hc
    node, ann, addr, clock, sessions = world
    root = {"v": 1, "updated": "2026-10-31", "hierarchies": [
        {"name": "alt", "policy": "free", "title": "Anything goes"}]}
    gid, groups = await found_lists(sessions, clock[0] - timedelta(hours=21), root=root)
    user = Session(Vault.open(tmp_path / "user.vault", "pw", **KDF), status=lambda *_: None)
    user.new_identity("user", "User")
    user.add_node(addr)
    me = user.identity()
    claim = hc.make_claim("claim", "dk", list=f"dk.list@{me.fingerprint}", title="Danmark")
    commit, nonce = hc.make_commit(claim)
    cid = await user.post(groups["claims"], nm.COMMIT_SUBJECT, commit)
    clock[0] += timedelta(hours=2)
    await user.post(groups["claims"], nm.reveal_subject(cid),
                    hc.make_reveal(claim, nonce, f"inbox@{me.fingerprint}"))
    record = [nm.dns_record_value(me.key_text), "v=spf1 -all"]
    answers = [lambda n: record if n == nm.tld_record_name("dk") else [],
               lambda n: record if n == nm.tld_record_name("dk") else [],
               lambda n: []]                                   # this one's DNS says no
    reps = [Replica(s, "unseenet.none@abcdefghijklmnop", now=lambda: clock[0],
                    rng=random.Random(k), levels=lambda k: 4, ripen=False,
                    tlds=lambda: {"dk", "com"}, dns_txt=answers[k],
                    config=lambda: {"lists": gid})
            for k, s in enumerate(sessions)]
    for _ in range(5):
        for r in reps:
            await r.run_once()
        clock[0] += timedelta(days=1)
    reports = [ls.parse_report(m.body, key=m.author_key, date=m.date)
               for m in await sessions[0].fetch_group(groups["reports"])
               if (m.subject or "").startswith(ls.REPORT_PREFIX)]
    assert {tuple(r.dns.get("dk", ["?"])) for r in reports} == {(me.key_text,), ()}
    posted = [m for m in await sessions[0].fetch_group(groups["hierarchies"]) if m.readable]
    by_day = {}
    for m in posted:
        by_day.setdefault(json.loads(m.body)["updated"], set()).add(m.body)
    assert posted and all(len(b) == 1 for b in by_day.values()), by_day   # all three alike
    _, got = hz.parse_root_list(posted[-1].body)
    assert got["dk"].maintainer == me.key_text
    assert all(r.st["lists"]["root"]["tld_grants"] == {"dk": me.key_text} for r in reps)
    await user.close()


async def test_the_replicas_keep_the_sources_list(world, tmp_path):
    """UN-RFC 0020 section 6.8: the sources list is the import, with the passed ``sources``
    decisions applied; the replicas post it alike, and a client reads it."""
    node, ann, addr, clock, sessions = world
    start = {"files": ["https://github.com/unseenet/{repo}/releases/download/{tag}/{name}"],
             "index": ["https://pypi.org/simple/"]}
    gid, groups = await found_lists(sessions, clock[0] - timedelta(hours=21), sources=start)
    reps = [Replica(s, "unseenet.none@abcdefghijklmnop", now=lambda: clock[0],
                    rng=random.Random(k), levels=lambda k: 4, ripen=False,
                    config=lambda: {"lists": gid})
            for k, s in enumerate(sessions)]
    for _ in range(3):
        for r in reps:
            status = await r.run_once()
        clock[0] += timedelta(days=1)
    posted = [m for m in await sessions[0].fetch_group(groups["sources"]) if m.readable]
    by_day = {}
    for m in posted:
        by_day.setdefault(json.loads(m.body)["updated"], set()).add(m.body)
    assert posted and all(len(b) == 1 for b in by_day.values())   # the same from all three
    _, got = ls.parse_sources_list(posted[-1].body)
    assert list(got.files) == start["files"] and list(got.index) == start["index"]
    assert status["lists"]["sources"]
    day, shown = await sessions[0].council_sources(gid)
    assert shown.files == got.files and day == posted[-1].date


async def test_the_replicas_list_an_entrance_serving_its_publishers_release(world, monkeypatch):
    """Section 6.3: an entrance announces itself naming its publisher; the replicas
    fetch it over Tor (here: a fake web), check every file against the publisher's
    signed release post, and list it after 14 good days. One that changes a file does
    not get on."""
    import hashlib

    import unseenet.replica.entrances as rent
    from unseenet.core import entrances as en
    node, ann, addr, clock, sessions = world
    gid, groups = await found_lists(sessions, clock[0] - timedelta(hours=21), entrances=True)
    # a publisher's releases channel, and its release post of the web client
    publisher = crypto.Identity.generate()
    channel = make_manifest(publisher, "acme.releases", "channel", pow_bits=8)
    node.store.add(channel, channel.to_bytes())
    node.store.set_manifest(Manifest.from_article(channel))
    files = {"index.html": b"<html>hello</html>", "app.js": b"console.log(1)"}
    sums = "\n".join(f"{hashlib.sha256(v).hexdigest()}  {k}" for k, v in files.items())
    rel = new_article(channel.group, "Unseenet web client 1.0", f"Unseenet web client 1.0\n\n{sums}\n",
                      now=clock[0] - timedelta(hours=20), from_name="Acme").finalize(publisher, 8)
    node.store.add(rel, rel.to_bytes())
    # two entrances: a good one and one that changes a file
    good, bad = crypto.Identity.generate(), crypto.Identity.generate()
    web = {}
    for ident, onion, js in ((good, "g" * 56 + ".onion", files["app.js"]),
                             (bad, "b" * 56 + ".onion", b"steal()")):
        base = f"http://{onion}/"
        web[base + ".well-known/unseenet-entrance"] = json.dumps(
            {"key": ident.key_text, "software": "unseenet-entrance 0.5.0"}).encode()
        web[base + "version.json"] = b'{"version": "1.0"}'
        web[base + "index.html"] = files["index.html"]
        web[base + "app.js"] = js
        body = en.make_body(channel.group, clock[0] - timedelta(hours=2), onion=onion,
                            name=onion[:4], operator="@op")
        art = new_article(groups["entrances.announce"], en.subject(onion[:4]), body,
                          now=clock[0] - timedelta(hours=2), from_name=onion[:4],
                          extra=[("Content-Type", "application/json")]).finalize(ident, 8)
        node.store.add(art, art.to_bytes())

    async def fake_fetch(self, url, limit):
        if url not in web:
            raise ValueError("404")
        return web[url]
    monkeypatch.setattr(rent.EntranceDuties, "_fetch_entrance", fake_fetch)
    reps = [Replica(s, "unseenet.none@abcdefghijklmnop", now=lambda: clock[0],
                    rng=random.Random(k), levels=lambda k: 4, ripen=False,
                    config=lambda: {"lists": gid})
            for k, s in enumerate(sessions)]
    for _ in range(17):
        for r in reps:
            status = await r.run_once()
        clock[0] += timedelta(days=1)
    reports = [m for m in await sessions[0].fetch_group(groups["reports"])
               if (m.subject or "").startswith(ls.REPORT_PREFIX)]
    last = ls.parse_report(reports[-1].body, key=reports[-1].author_key, date=reports[-1].date)
    assert good.key_text in last.reached and bad.key_text in last.reached
    assert last.served == {good.key_text: "1.0"}
    assert last.software[good.key_text] == "unseenet-entrance 0.5.0"
    posted = [m for m in await sessions[0].fetch_group(groups["entrances"]) if m.readable]
    newest = json.loads(posted[-1].body)
    assert [e["key"] for e in newest["entrances"]] == [good.key_text]
    assert newest["entrances"][0]["publisher"] == channel.group
    verdicts = reps[0].st["lists"]["entrances"]["verdicts"]
    assert "all are needed" in verdicts[bad.key_text]
    assert status["lists"]["entrances"] == 1
    from unseenet.replica.cli import explain
    assert "entrance list it computed last" in "\n".join(explain(status, {"lists": gid}))
