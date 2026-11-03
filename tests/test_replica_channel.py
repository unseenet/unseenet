"""The replica's operator channel (UN-RFC 0065 section 8, #874 part 2): what it tells its
operators after a round, and council work from their everyday client through the same
functions as ``unseenet-replica`` - with what it queues posted at once."""

import json
from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
from unseenet.client import operator as oc
from unseenet.client.session import Session
from unseenet.core import proposals as pr
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig
from unseenet.replica import cli as rcli
from unseenet.replica import operator as ro

KDF = {"ops": 1, "mem": 8192 * 1024}
LABEL = "removal:ed25519:aaaa"


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


class FakeReplica:
    """What ReplicaChannel uses of the running replica: its session and its outbox."""
    def __init__(self, s, d):
        self.s, self.d, self.posted = s, d, []

    async def _outbox(self):
        for path in sorted((self.d / "outbox").glob("*.json")):
            self.posted.append(json.loads(path.read_text()))
            path.unlink()


def _state(d, now):
    pid, body = pr.make_proposal("unseenet.lists@x", 3, {"manifest": {"fields": {"min_pow": 24}}},
                                 "Proposals cost more postage")
    st = {"role": "full member", "group": "unseenet.names@x", "key": "ed25519:me",
          "held": {LABEL: {"kind": "removal", "why": "inactive for 90 days"}},
          "groups": {"proposals": "unseenet.names.proposals@x", "talk": "unseenet.names.talk@x"},
          "proposals_pending": {pid: {"body": body, "by": ["ed25519:other"]}},
          "hearings": [{"id": "HEAR", "state": "open", "kind": "manifest", "objections": 0,
                        "active": 3, "reason": "The council keeps the gateway directory",
                        "closes": (now + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ")}],
          "posts": {"talk": [], "log": []}}
    (d / "status.json").write_text(json.dumps(st))
    (d / "config.json").write_text("{}")
    return st, pid


async def _say(p, gid, text):
    await p.send_private(gid, "", text + "\n", kind="chat", as_team=gid)


async def test_council_work_from_chat(net, tmp_path):
    owner, andreas, replica = net("owner"), net("andreas"), net("replica")
    await andreas.ensure_inbox()
    d = tmp_path / "state"
    d.mkdir()
    now = datetime.now(timezone.utc)
    st, pid = _state(d, now)
    gid = await owner.create_group("operator.replica2", "inbox")
    rep = FakeReplica(replica, d)
    rc = ro.ReplicaChannel(rep, gid, "commands", d, warn_delay=0, code=lambda: "1234")
    await oc.add_server(owner, gid, oc.make_channel_key(replica, gid), "replica2")
    await owner.add_team_reader(gid, andreas.identity().key_text)
    await andreas.fetch_group(andreas.my_inbox)
    await andreas.accept_team_invitation(next(m for m in andreas.private_messages()
                                              if andreas.team_invitation(m)))

    # after a round: the held change is told, with an offer to agree
    await rc.round(st)
    notices = [m for m in await andreas.fetch_group(gid) if m.operator and m.operator["notice"]]
    held = next(m for m in notices if m.operator["notice"] == "held")
    assert LABEL in held.body and held.operator["offers"][0]["reply"] == f"agree {LABEL}"
    await rc.round(st)                                       # told once
    assert len([m for m in await andreas.fetch_group(gid)
                if m.operator and m.operator["notice"] == "held"]) == 1
    assert "closing:HEAR" in rc.chan.state["open"]          # in the next digest

    async def ask(text):
        await _say(andreas, gid, text)
        return [a for _, a in await rc.chan.poll()]

    # agree: asked, then done - the same as unseenet-replica agree
    [a] = await ask(f"agree {LABEL}")
    assert a.result == "asked" and "inactive" not in a.text and LABEL in a.text
    [a] = await ask("yes 1234")
    assert a.result == "done" and LABEL in json.loads((d / "config.json").read_text())["agreed"]

    # second: posted at once, not at the next round
    [a] = await ask(f"second {pid}")
    assert a.result == "asked" and "Proposals cost more postage" in a.text
    [a] = await ask("yes 1234")
    assert a.result == "done" and "Posted." in a.text
    assert rep.posted[-1]["subject"] == f"proposal {pid}"

    # talk: the text after the verb, every line of it
    [a] = await ask("talk: Hej rådet\nanden linje")
    assert a.result == "asked"
    [a] = await ask("yes 1234")
    assert rep.posted[-1]["subject"] == "Hej rådet" and "anden linje" in rep.posted[-1]["body"]

    # what chat may not do, and reading
    [a] = await ask("resign")
    assert a.result == "refused" and "only on the server" in a.text
    [a] = await ask("hearings")
    assert a.result == "done" and "HEAR" in a.text and pid in a.text
    [a] = await ask("status")
    assert "registrar unseenet.names@x" in a.text
    [a] = await ask("object NOPE because")
    assert a.result == "refused" and "No proposal NOPE" in a.text


async def test_the_configuration_names_the_channel(net, tmp_path, capsys):
    replica = net("replica")
    d = tmp_path / "state"
    d.mkdir()
    (d / "config.json").write_text("{}")
    rep = FakeReplica(replica, d)
    rep.status = {}
    assert ro.setup_channel(rep, {}, d) is None
    assert ro.setup_channel(rep, {"channel": "operator@x", "operator_channel": "off"}, d) is None
    rc = ro.setup_channel(rep, {"channel": "operator@x"}, d)
    assert rc.chan.desk.mode == "notices"                      # the default
    assert rep.status["channel"]["key"] == replica.team_key("operator@x").key_text

    from argparse import Namespace
    rcli.channel(Namespace(dir=str(d), group="operator@x", mode="commands"))
    cfg = json.loads((d / "config.json").read_text())
    assert cfg == {"channel": "operator@x", "operator_channel": "commands"}
    assert "next round" in capsys.readouterr().out
    (d / "status.json").write_text(json.dumps({"channel": {"group": "operator@x",
                                                           "key": "ed25519:k", "reader": False}}))
    rcli.channel(Namespace(dir=str(d), group=None, mode=None))
    out = capsys.readouterr().out
    assert "ed25519:k" in out and "unseenet operator add-server operator@x ed25519:k" in out
