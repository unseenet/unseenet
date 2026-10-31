"""Replicas of a council registrar against one local node, over simulated months
(UN-RFC 0054 sections 8-13 and 20, #690): three members and a shadow decide the same
claims, the shadow is admitted after 60 days of agreeing, a member that signs a
certificate no claim explains is removed, and one that resigns is removed too - each
change one manifest that the replicas computed alike."""

import os
from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
import unseenet.client.session.council as sess_council
import unseenet.client.session.posting as posting
import unseenet.registrar as registrar_mod
import unseenet.replica.run as run_mod
from unseenet import names as nm
from unseenet.client import naming
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig
from unseenet.replica import rules
from unseenet.replica.run import Replica

KDF = {"ops": 1, "mem": 8192 * 1024}
TLDS = {"com", "dk", "org"}


class Net:
    def __init__(self, addr, tmp, start):
        self.addr, self.tmp = addr, tmp
        self.clock = start
        self.sessions = []

    def session(self, name):
        s = Session(Vault.open(self.tmp / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(self.addr)
        self.sessions.append(s)
        return s

    def replica(self, s, group, **kw):
        return Replica(s, group, tlds=lambda: TLDS, dns_txt=lambda n: [], now=lambda: self.clock,
                       levels=lambda k: 4, **kw)

    async def found(self, members, founder=None):
        keys = [m.identity().key_text for m in members]
        a = members[0]
        fk = dict(founding_years=1, founder=founder.identity().key_text) if founder else {}
        claims, body = a.council_genesis("unseenet.names.claims", "open", keys,
                                         fields={"min_pow": 8, "retention_days": 365},
                                         date=self.clock, **fk)
        for m in members:
            await m.council_sign(claims, body)
        group, body = a.council_genesis("unseenet.names", "channel", keys,
                                        fields={"min_pow": 0, "retention_days": 365,
                                                "claims": claims}, date=self.clock, **fk)
        for m in members:
            await m.council_sign(group, body)
        return group, claims


@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    from unseenet.node import server as node_server
    monkeypatch.setattr(node_server, "POST_PAST", timedelta(days=3650))
    # months pass on the test's clock, not the node's: it keeps what is old to it
    monkeypatch.setattr(Node, "_keep_old", lambda self, art, manifest: True)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    start = (datetime.now(timezone.utc) - timedelta(days=110)).replace(
        hour=0, minute=30, second=0, microsecond=0)
    w = Net(f"127.0.0.1:{server.sockets[0].getsockname()[1]}", tmp_path, start)
    for mod in (posting, registrar_mod, run_mod, sess_council):
        real = mod.new_article
        monkeypatch.setattr(mod, "new_article",
                            lambda *a, _real=real, **k: _real(*a, **{**k, "now": k.get("now") or w.clock}))
    yield w
    for s in w.sessions:
        await s.close()
    server.close()


async def claim(net, user, name, replicas=()):
    """A whole public claim: commit now, reveal an hour and a half later. The replicas
    run in between, as they do every few minutes: a commit seen more than an hour
    after its Date is late (UN-RFC 0054 section 8)."""
    await naming.claim(user, name)
    net.clock += timedelta(minutes=10)
    for r in replicas:
        await r.run_once()
    net.clock -= timedelta(minutes=10)
    c = naming._store(user)["commits"][-1]
    c["date"] = nm.rfc3339(net.clock.replace(minute=net.clock.minute // 10 * 10, second=0,
                                             microsecond=0))
    net.clock += timedelta(minutes=90)
    assert await naming.reveal_due(user, now=net.clock) == [name]


async def test_replicas_agree_admit_a_shadow_and_remove_a_member(net, monkeypatch):
    a, b, c = net.session("a"), net.session("b"), net.session("c")
    group, claims = await net.found([a, b, c])
    monkeypatch.setattr(nm, "NAMES_GROUP", group)
    shadow = net.session("shadow")
    user = net.session("user")
    reps = [net.replica(s, group) for s in (a, b, c)]
    sh = net.replica(shadow, group)
    await user.refresh_naming()
    assert naming.claims_are_public(user)

    names = iter(["lorensen", "andlo", "marsvin", "sonia", "jaxie", "regin", "bente", "ole"])
    admitted = None
    for day in range(80):
        if day % 10 == 1:                          # a claim now and then
            await claim(net, user, next(names), (*reps, sh))
        net.clock = net.clock.replace(hour=21)     # past every report's random time
        for r in (*reps, sh):
            await r.run_once()
        chain = await a.council_chain(group)
        if admitted is None and chain.current.member(shadow.identity().public_key):
            admitted = rules.day_of(net.clock)
            break
        net.clock = net.clock.replace(minute=30) + timedelta(hours=4)    # the next day

    # every member decided every claim alike, and issued one certificate each
    certs = [rules.Cert(nm.parse_certificate(m.body), m.date)
             for m in await user.fetch_group(group) if m.subject.startswith("name ")]
    by = {}
    for x in certs:
        by.setdefault(x.cert.decision, set()).add(x.cert.registrar)
    assert len(by) == 3                    # a key holds at most 3 names: the rest refused
    assert all(v == {s.identity().key_text for s in (a, b, c)} for v in by.values())
    await user.refresh_naming()
    assert {x.name for x in naming.my_names(user)} == {"lorensen", "andlo", "marsvin"}
    # ... and every replica made the same decisions, refusals included (section 10)
    hashes = [[d[2] for d in r.reg.st["decisions"]] for r in (*reps, sh)]
    assert len(hashes[0]) == 7 and all(h == hashes[0] for h in hashes)

    # the shadow's reports agreed with the council, and it was admitted on probation
    assert admitted is not None
    cur = (await a.council_chain(group)).current
    m = cur.member(shadow.identity().public_key)
    assert cur.seq == 2 and not m.full and m.by is None
    # 60 settled days, all known to the members: on the 68th day after the genesis
    assert m.joined == admitted == rules.day_of(net.clock)
    assert (admitted - cur.members[0].joined).days == 68
    # ... in the claims group too (section 8)
    for r in reps:
        await r.run_once()
    assert (await a.council_chain(claims)).current.member(shadow.identity().public_key)

    # a member signs a certificate no claim explains: the others remove it
    forged = nm.make_certificate(c.identity(), "microsoft", user.identity().key_text, 1,
                                 claim="<nothing@x>", claimed=net.clock)
    await reps[2].reg._post_json("name microsoft", forged.to_json() + "\n")
    posted = rules.day_of(net.clock)
    # judged once its commit would surely have been seen: 8 days and an hour on
    net.clock += timedelta(days=1)
    for r in reps[:2]:
        await r.run_once()
    assert reps[0].status.get("next_change") is None
    net.clock += timedelta(days=8)
    for r in reps:
        await r.run_once()
    cur = (await a.council_chain(group)).current
    assert cur.member(c.identity().public_key) is None and cur.seq == 3
    assert cur.date == posted                       # the day of the certificate itself
    assert reps[0].status["role"] == "full member"
    assert sh.role(cur) == "member on probation"

    # a member resigns (section 20); the remaining full members remove it - but not
    # below 2 full members, so here the change would not count and nothing happens
    await reps[1].reg._post_json(rules.RESIGN, "{}\n")
    net.clock += timedelta(days=1)
    for r in reps[:2]:
        await r.run_once()
    assert (await a.council_chain(group)).current.seq == 3


async def test_holding_and_agreeing(net, monkeypatch, tmp_path):
    """Section 13: an operator who holds removals sees the change and lets it go."""
    from unseenet.replica import cli
    a, b, c = net.session("a"), net.session("b"), net.session("c")
    group, _ = await net.found([a, b, c])
    monkeypatch.setattr(nm, "NAMES_GROUP", group)
    dirs = [tmp_path / n for n in "abc"]
    for d in dirs:
        d.mkdir()
        cli.write_config(d, {"group": group, "hold": ["removal"]})
    reps = [net.replica(s, group, state_dir=d, config=lambda d=d: cli.read_config(d))
            for s, d in zip((a, b, c), dirs)]
    for r in reps:
        await r.run_once()
    forged = nm.make_certificate(c.identity(), "microsoft", a.identity().key_text, 1,
                                 claim="<nothing@x>", claimed=net.clock)
    await reps[2].reg._post_json("name microsoft", forged.to_json() + "\n")
    posted = rules.day_of(net.clock)
    # judged once its commit would surely have been seen: 8 days and an hour on
    net.clock += timedelta(days=1)
    for r in reps[:2]:
        await r.run_once()
    assert reps[0].status.get("next_change") is None
    net.clock += timedelta(days=8)
    for r in reps[:2]:
        await r.run_once()
    assert (await a.council_chain(group)).current.seq == 1         # held by both
    held = reps[0].status["held"]
    (label,) = held
    assert label == f"removal:{c.identity().key_text}"
    text = "\n".join(cli.explain(cli.read_status(dirs[0]), cli.read_config(dirs[0])))
    assert "HELD, waiting for you" in text and f"unseenet-replica agree {label}" in text
    assert "FULL MEMBER" in text

    # both operators agree
    for d in dirs[:2]:
        args = type("A", (), {"dir": str(d), "label": label, "force": False})()
        assert cli.agree(args) == 0
    for r in reps[:2]:
        await r.run_once()
    cur = (await a.council_chain(group)).current
    assert cur.seq == 2 and cur.member(c.identity().public_key) is None


def test_status_in_plain_words():
    from unseenet.replica import cli
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    st = {"role": "shadow", "group": "unseenet.names@x", "key": "ed25519:k", "level": 2,
          "min_level": 4, "reports_60": 12, "members": 3, "full": 3,
          "time": "2026-11-01T11:55:00Z", "software": "unseenet-replica 0.7.0"}
    text = "\n".join(cli.explain(st, {}, now))
    assert "SHADOW" in text and "12 (55 are needed)" in text and "level 2 of the 4" in text
    assert "5 minutes ago" in text
    st["time"] = "2026-11-01T09:00:00Z"
    assert "is it running?" in "\n".join(cli.explain(st, {}, now))
    assert "has not finished a round" in cli.explain({}, {}, now)[0]


async def test_the_founder_admits_a_shadow_faster(net, monkeypatch):
    """Section 19: the founder - not a member - asks; the replicas admit the shadow once it
    has reported for 7 settled days, and promote it after 30 days. Then the founder
    renounces, and the replicas post that too."""
    a, b, founder = net.session("a"), net.session("b"), net.session("project")
    group, claims = await net.found([a, b], founder=founder)
    monkeypatch.setattr(nm, "NAMES_GROUP", group)
    shadow = net.session("shadow")
    reps = [net.replica(s, group) for s in (a, b)]
    sh = net.replica(shadow, group)
    from unseenet.client.session import SessionError
    with pytest.raises(SessionError, match="only the council's founder"):
        await a.council_act(group, "admit", shadow.identity().key_text)
    await founder.council_act(group, "admit", shadow.identity().key_text)
    start = rules.day_of(net.clock)
    for day in range(60):
        net.clock = net.clock.replace(hour=21)
        for r in (*reps, sh):
            await r.run_once()
        m = (await a.council_chain(group)).current.member(shadow.identity().public_key)
        if m is not None and m.full:
            break
        net.clock = net.clock.replace(minute=30) + timedelta(hours=4)
    cur = (await a.council_chain(group)).current
    m = cur.member(shadow.identity().public_key)
    assert m.by == "founder" and m.full
    assert (m.joined - start).days == 15                 # 7 settled days: days 0-6, by day 15
    assert (rules.day_of(net.clock) - m.joined).days == 30
    for r in reps:                    # the claims group follows at the next round (section 8)
        await r.run_once()
    assert (await a.council_chain(claims)).current.member(shadow.identity().public_key).full

    await founder.council_act(group, "renounce")
    net.clock += timedelta(days=1)
    for r in (*reps, sh):
        await r.run_once()
    for r in (*reps, sh):                                 # three full members: 2 of 3 count
        await r.run_once()
    assert (await a.council_chain(group)).current.founding.renounced
    with pytest.raises(SessionError, match="renounced"):
        await founder.council_act(group, "admit", a.identity().key_text)


def test_setup_without_systemd(tmp_path, monkeypatch, capsys):
    """``unseenet-replica setup --no-systemd``: key, vault, passphrase and config in one
    folder; ``status`` before the first round says what to expect."""
    import json as _json
    import shutil
    from unseenet.replica import cli
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    real = shutil.which
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/bin/tor" if n == "tor" else real(n))
    d = tmp_path / "replica"
    assert cli.main(["--dir", str(d), "setup", "--no-systemd", "--hold", "removal",
                     "--group", "unseenet.names@abcdefghijklmnop"]) == 0
    out = capsys.readouterr().out
    assert "SHADOW" in out and "ed25519:" in out
    assert (d / "replica.vault").exists() and (d / "passphrase").exists()
    if os.name == "posix":                         # only the owner reads it
        assert (d / "passphrase").stat().st_mode & 0o077 == 0
    cfg = _json.loads((d / "config.json").read_text())
    assert cfg["hold"] == ["removal"] and cfg["group"] == "unseenet.names@abcdefghijklmnop"
    assert cli.main(["--dir", str(d), "setup", "--no-systemd"]) == 1        # not twice
    capsys.readouterr()
    assert cli.main(["--dir", str(d), "status"]) == 0
    assert "has not finished a round" in capsys.readouterr().out
    assert cli.main(["--dir", str(d), "hold", "all"]) == 0
    assert _json.loads((d / "config.json").read_text())["hold"] == ["admission", "promotion", "removal"]
    with pytest.raises(SystemExit):
        cli.main(["--dir", str(d), "hold", "everything"])
