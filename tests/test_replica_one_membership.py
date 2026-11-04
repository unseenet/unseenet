"""One membership for all the project's councils (#943): the names council's replicas
keep the list council in step, a shadow computes the lists as the members do and shows
them in its one daily report, and it is admitted to both councils - or to neither, when a
list it computed differs. Three active members see no change for months."""

from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
import unseenet.client.session.council as sess_council
import unseenet.client.session.posting as posting
import unseenet.registrar as registrar_mod
import unseenet.replica.lists as rlists
import unseenet.replica.run as run_mod
from unseenet import known_nodes
from unseenet import names as nm
from unseenet.client.session import Session
from unseenet.core.groups import Manifest, make_manifest
from unseenet.core import crypto
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig
from unseenet.replica import rules
from unseenet.replica.run import Replica

KDF = {"ops": 1, "mem": 8192 * 1024}
TLDS = {"com", "dk", "org"}


class World:
    def __init__(self, addr, tmp, start):
        self.addr, self.tmp, self.clock = addr, tmp, start
        self.sessions = []

    def session(self, name):
        s = Session(Vault.open(self.tmp / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(self.addr)
        self.sessions.append(s)
        return s

    def replica(self, s, names, lists):
        return Replica(s, names, tlds=lambda: TLDS, dns_txt=lambda n: [], now=lambda: self.clock,
                       levels=lambda k: 4, ripen=False, config=lambda: {"lists": lists})

    async def genesis(self, members, name, kind, fields=None, founder=None):
        keys = [m.identity().key_text for m in members]
        fk = dict(founding_years=1, founder=founder.identity().key_text) if founder else {}
        g, body = members[0].council_genesis(name, kind, keys, fields=fields or {},
                                             date=self.clock, **fk)
        for m in members:
            await m.council_sign(g, body)
        return g

    async def found(self, members, founder):
        """The project's two councils, as founded on 2 Nov 2026: the names council and
        the list council with its node list, reports and claims - same members, same
        founder."""
        claims = await self.genesis(members, "unseenet.names.claims", "open",
                                    {"min_pow": 8, "retention_days": 365}, founder)
        names = await self.genesis(members, "unseenet.names", "channel",
                                   {"min_pow": 0, "retention_days": 365, "claims": claims}, founder)
        parts = {}
        for part, kind in (("claims", "open"), ("reports", "channel"), ("nodes", "channel")):
            parts[part] = await self.genesis(members, f"unseenet.lists.{part}", kind,
                                             {"min_pow": 0}, founder)
        lists = await self.genesis(members, "unseenet.lists", "channel", {
            "min_pow": 0, "lists": {"nodes": parts["nodes"]}, "claims": parts["claims"],
            "reports": parts["reports"], "min_software": {"unseenet": "0.1.0"}}, founder)
        return names, claims, lists, parts


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
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    node.store.add(ann, ann.to_bytes())
    node.store.set_manifest(Manifest.from_article(ann))
    server = await node.serve("127.0.0.1", 0)
    start = (datetime.now(timezone.utc) - timedelta(days=250)).replace(
        hour=0, minute=30, second=0, microsecond=0)
    w = World(f"127.0.0.1:{server.sockets[0].getsockname()[1]}", tmp_path, start)
    for mod in (posting, registrar_mod, run_mod, sess_council, rlists):
        real = mod.new_article
        monkeypatch.setattr(mod, "new_article",
                            lambda *a, _real=real, **k: _real(*a, **{**k, "now": k.get("now") or w.clock}))
    yield w
    for s in w.sessions:
        await s.close()
    server.close()


async def days(w, replicas, n, until=None, step=1):
    """Run every replica once a day, late in the day (past every random time)."""
    for _ in range(n):
        w.clock = w.clock.replace(hour=21)
        for r in replicas:
            await r.run_once()
        if until is not None and await until():
            return True
        w.clock = w.clock.replace(minute=30) + timedelta(hours=4) + timedelta(days=step - 1)
    return False


def members_of(chain):
    return {(crypto.key_to_text(m.key), m.full) for m in chain.current.members}


async def test_a_shadow_is_admitted_to_both_councils_at_once(world, monkeypatch):
    a, b, founder = world.session("a"), world.session("b"), world.session("project")
    names, claims, lists, parts = await world.found([a, b], founder)
    monkeypatch.setattr(nm, "NAMES_GROUP", names)
    shadow = world.session("shadow")
    reps = [world.replica(s, names, lists) for s in (a, b)]
    sh = world.replica(shadow, names, lists)
    await founder.council_act(names, "admit", shadow.identity().key_text)   # section 19

    async def admitted():
        return (await a.council_chain(names)).current.member(shadow.identity().public_key)
    assert await days(world, (*reps, sh), 30, until=admitted)
    # the shadow computed the node list each day, as the members did, and posted none
    assert sh.st["lists"]["outcomes"] and sh.status["lists"]["role"] == "shadow"
    posted = [m for m in await a.fetch_group(parts["nodes"]) if m.readable]
    assert posted and {m.author_key for m in posted} <= {a.identity().key_text,
                                                         b.identity().key_text}
    # its one report held the list hashes as well as the name decisions
    reports = rules.reports_by_key([nm.Post(m.message_id, m.subject or "", m.author_key, m.date,
                                            m.body) for m in await a.fetch_group(claims)
                                    if m.readable and m.author_key and m.date])
    mine = reports[shadow.identity().key_text]
    assert any("list:nodes" in r.decisions for r in mine.values())
    # the next rounds bring the list council, then its groups, to the same members
    await days(world, (*reps, sh), 3)
    want = members_of(await a.council_chain(names))
    assert shadow.identity().key_text in {k for k, _ in want}
    assert members_of(await a.council_chain(lists)) == want
    for g in parts.values():
        assert members_of(await a.council_chain(g)) == want, g
    # and the shadow is a member of the list council now: it measures and reports
    await days(world, (*reps, sh), 1)
    assert sh.status["lists"]["role"] == "member on probation"
    assert any(m.author_key == shadow.identity().key_text
               for m in await a.fetch_group(parts["reports"]) if m.readable)


async def test_a_shadow_whose_list_differs_is_admitted_to_neither(world, monkeypatch):
    a, b, founder = world.session("a"), world.session("b"), world.session("project")
    names, claims, lists, parts = await world.found([a, b], founder)
    monkeypatch.setattr(nm, "NAMES_GROUP", names)
    shadow = world.session("shadow")
    reps = [world.replica(s, names, lists) for s in (a, b)]
    sh = world.replica(shadow, names, lists)
    real = sh._note_outcome
    sh._note_outcome = lambda what, day, body: real(what, day, body.replace("council", "kouncil"))
    await founder.council_act(names, "admit", shadow.identity().key_text)

    async def admitted():
        return (await a.council_chain(names)).current.member(shadow.identity().public_key)
    assert not await days(world, (*reps, sh), 30, until=admitted)
    assert (await a.council_chain(lists)).current.member(shadow.identity().public_key) is None


async def test_three_active_members_see_no_change_for_months(world, monkeypatch):
    """The list council's members rarely post in the council group itself, but in its
    reports and lists every day: that is activity, so nobody is removed as silent."""
    a, b, c = world.session("a"), world.session("b"), world.session("c")
    founder = world.session("project")
    names, claims, lists, parts = await world.found([a, b, c], founder)
    monkeypatch.setattr(nm, "NAMES_GROUP", names)
    reps = [world.replica(s, names, lists) for s in (a, b, c)]
    await days(world, reps, 70, step=3)                    # 210 days
    for g in (names, claims, lists, *parts.values()):
        chain = await a.council_chain(g)
        assert chain.current.seq == 1 and not chain.disputed, g
    assert all(r.status.get("next_change") is None for r in reps)


async def test_a_member_silent_everywhere_is_removed_from_both(world, monkeypatch):
    a, b, c = world.session("a"), world.session("b"), world.session("c")
    founder = world.session("project")
    names, claims, lists, parts = await world.found([a, b, c], founder)
    monkeypatch.setattr(nm, "NAMES_GROUP", names)
    reps = [world.replica(s, names, lists) for s in (a, b)]     # c's replica never runs

    async def gone():
        return (await a.council_chain(names)).current.member(c.identity().public_key) is None
    assert await days(world, reps, 40, until=gone, step=3)
    await days(world, reps, 2)
    gone_key = c.identity().key_text
    for g in (lists, *parts.values()):
        assert gone_key not in {k for k, _ in members_of(await a.council_chain(g))}, g
