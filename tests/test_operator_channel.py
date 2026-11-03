"""UN-RFC 0065 (#876): a server's operator channel - commands with confirmation codes,
once only and never too old, what chat may not do, offers; and the channel itself,
a team inbox whose readers are the server's own channel key and its operators."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
from unseenet.client import operator as oc
from unseenet.client.session import Session
from unseenet.core import operator as op
from unseenet.core.groups import make_manifest
from unseenet.core import crypto
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def _desk(mode="commands", server=None, clock=None):
    done = []

    async def second(args):
        done.append(("second", args))
        return f"Seconded {args[0]}."

    def describe(args):
        if len(args) != 1:
            raise ValueError("Which proposal?")
        return f"Second proposal {args[0]}"

    async def ping(args):
        return "pong"
    cmds = [op.Command("second", "second a proposal", run=second, changes=True,
                       describe=describe, usage="<id>", label="Second it"),
            op.Command("ping", "answers pong", run=ping),
            op.Command("resign", "leave the council", cli_only=True),
            op.Command("status", "how it is", run=ping)]
    clock = clock or Clock()
    return op.Desk(cmds, {}, mode=mode, server=server, now=clock, code=lambda: "4821"), done, clock


def run(coro):
    return asyncio.run(coro)


def now_of(clock):
    return datetime.fromtimestamp(clock.t, timezone.utc)


def test_a_change_waits_for_the_code_of_the_one_who_asked():
    desk, done, clock = _desk()
    a = run(desk.take("<1>", "alice", now_of(clock), "second ABCD"))
    assert a.result == "asked" and a.code == "4821" and "yes 4821" in a.text
    assert [o.reply for o in a.offers] == ["yes 4821", "no"] and a.offers[0].label == "Second it"
    assert done == []
    assert run(desk.take("<2>", "bob", now_of(clock), "yes 4821")).result == "refused"   # not his
    b = run(desk.take("<3>", "alice", now_of(clock), "yes 4821"))
    assert b.result == "done" and done == [("second", ["ABCD"])]
    assert run(desk.take("<4>", "alice", now_of(clock), "yes 4821")).result == "refused"  # once


def test_a_typo_never_acts():
    desk, done, clock = _desk()
    assert run(desk.take("<1>", "a", now_of(clock), "secnd ABCD")).result == "refused"
    run(desk.take("<2>", "a", now_of(clock), "second ABCD"))
    wrong = run(desk.take("<3>", "a", now_of(clock), "yes 4812"))
    assert wrong.result == "refused" and "cancelled" in wrong.text.lower()
    assert run(desk.take("<4>", "a", now_of(clock), "yes 4821")).result == "refused"
    run(desk.take("<5>", "a", now_of(clock), "second ABCD"))
    other = run(desk.take("<6>", "a", now_of(clock), "ping"))            # anything else cancels
    assert other.text.startswith("Cancelled") and other.text.endswith("pong")
    run(desk.take("<7>", "a", now_of(clock), "second ABCD"))
    assert run(desk.take("<8>", "a", now_of(clock), "no")).text.startswith("Cancelled")
    assert done == []


def test_codes_expire_and_old_commands_are_too_late():
    desk, done, clock = _desk()
    run(desk.take("<1>", "a", now_of(clock), "second ABCD"))
    clock.t += op.CODE_SECONDS + 1
    assert run(desk.take("<2>", "a", now_of(clock), "yes 4821")).result == "refused"
    old = now_of(clock) - timedelta(seconds=op.COMMAND_MAX_AGE + 60)
    late = run(desk.take("<3>", "a", old, "ping"))
    assert late.result == "refused" and "too late" in late.text
    assert done == []


def test_once_only_and_what_chat_may_not_do():
    desk, _, clock = _desk()
    assert run(desk.take("<1>", "a", now_of(clock), "ping")).text == "pong"
    assert run(desk.take("<1>", "a", now_of(clock), "ping")) is None          # seen before
    r = run(desk.take("<2>", "a", now_of(clock), "resign"))
    assert r.result == "refused" and "only on the server" in r.text
    assert "resign" in desk.help() and "only on the server itself" in desk.help()


def test_notices_mode_takes_only_help_status_and_notices():
    desk, done, clock = _desk(mode="notices")
    assert run(desk.take("<1>", "a", now_of(clock), "second ABCD")).result == "refused"
    assert run(desk.take("<2>", "a", now_of(clock), "ping")).result == "refused"
    assert run(desk.take("<3>", "a", now_of(clock), "status")).result == "done"
    assert run(desk.take("<4>", "a", now_of(clock), "help")).result == "done"
    assert done == []


def test_a_shared_channel_names_the_server():
    desk, _, clock = _desk(server="replica2")
    assert run(desk.take("<1>", "a", now_of(clock), "ping")) is None           # not for it
    assert run(desk.take("<2>", "a", now_of(clock), "node3: ping")) is None
    assert run(desk.take("<3>", "a", now_of(clock), "Replica2: ping")).text == "pong"


def test_offers_and_inner_headers():
    assert op.parse_offers(["yes 4821 | Second it", "no", " | broken", "x" * 3]) == [
        op.Offer("yes 4821", "Second it"), op.Offer("no"), op.Offer("xxx")]
    assert len(op.parse_offers([f"o{i}" for i in range(9)])) == op.MAX_OFFERS
    h = op.notice_headers("disk-low", "warn", key="disk", server="node3",
                          offers=[op.offer("status")])
    f = op.operator_fields(h)
    assert f["notice"] == "disk-low" and f["level"] == "warn" and f["server"] == "node3"
    assert f["offers"] == [{"reply": "status", "label": "status"}]
    assert op.operator_fields([("Subject", "x")]) is None
    assert [n for n, _ in h if n.startswith("Offer")] == ["Offer-1"]
    two = op.operator_fields([("Offer-2", "no | Cancel"), ("Offer-1", "yes 1 | Go"),
                              ("Offer-7", "too many")])
    assert [o["reply"] for o in two["offers"]] == ["yes 1", "no"]
    for bad in (lambda: op.notice_headers("Disk Low"), lambda: op.notice_headers("x", "loud"),
                lambda: op.offer("a|b"), lambda: op.offer("x", "y" * 41)):
        with pytest.raises(ValueError):
            bad()


def test_the_manifest_flag_is_for_inboxes():
    owner = crypto.Identity.generate()
    make_manifest(owner, "operator", "inbox", pow_bits=8, extra={"operator_channel": True})
    with pytest.raises(ValueError, match="operator_channel"):
        make_manifest(owner, "dk.snak", "open", pow_bits=8, extra={"operator_channel": True})


# --- the channel on a node (sections 3, 4, 5) ---------------------------------------

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


async def test_a_channel_from_start_to_end(net):
    owner, andreas, helper, replica = net("owner"), net("andreas"), net("helper"), net("replica")
    for p in (andreas, helper):
        await p.ensure_inbox()
    gid = await owner.create_group("operator", "inbox")
    key = oc.make_channel_key(replica, gid)
    assert oc.make_channel_key(replica, gid) == key                     # made once, kept
    clock = Clock()
    clock.t = datetime.now(timezone.utc).timestamp()
    done = []

    async def second(args):
        done.append(args)
        return f"Seconded {args[0]}."
    chan = oc.OperatorChannel(replica, gid, [op.Command(
        "second", "second a proposal", run=second, changes=True, usage="<id>",
        describe=lambda a: f"Second proposal {a[0]}")], mode="commands",
        status=lambda: "All rounds fine.", now=clock, warn_delay=0, code=lambda: "1234")

    assert not await chan.ready()                                       # not a reader yet
    await oc.add_server(owner, gid, key, "replica2")
    await owner.add_team_reader(gid, andreas.identity().key_text)
    await owner.add_team_reader(gid, helper.identity().key_text)
    assert owner.manifest_data(gid)["operator_channel"] is True
    for p in (andreas, helper):
        await p.fetch_group(p.my_inbox)
        await p.accept_team_invitation(next(m for m in p.private_messages() if p.team_invitation(m)))
    assert await chan.ready()
    assert await chan.poll() == []                                      # nothing before it

    # it says hello once, a message any client can answer (UN-RFC 0065 section 7)
    assert await chan.ready()
    [hello] = [m for m in await andreas.fetch_group(gid)
               if m.operator and m.operator["notice"] == "hello"]
    assert "replica2 reads this channel now" in hello.body
    assert [o["reply"] for o in hello.operator["offers"]] == ["help", "status"]
    assert andreas.reply_target(hello) == gid                          # an answer goes there
    await andreas.send_private(andreas.reply_target(hello), "", "status\n", kind="chat",
                               references=[hello.message_id], as_team=gid)
    [(_, st)] = await chan.poll()
    assert st.result == "done" and st.text == "All rounds fine."

    # a notice: once per matter, its end once
    assert await chan.notice("twin", "Twin alarm: the key is used elsewhere.", "alarm", key="twin")
    assert await chan.notice("twin", "again", "alarm", key="twin") is None
    [n] = [m for m in await andreas.fetch_group(gid) if m.operator and m.operator["notice"] == "twin"]
    assert n.operator["level"] == "alarm" and andreas.team_sender(n)["name"] == "replica2"
    assert (await chan._open_text([])).startswith("- [alarm] Twin alarm")

    # a command, its code, the answer every reader sees
    await andreas.send_private(gid, "", "second ABCD\n", kind="chat", as_team=gid)
    [(cmd_id, asked)] = await chan.poll()
    assert asked.result == "asked" and done == []
    [q] = [m for m in await andreas.fetch_group(gid) if m.operator and m.operator["code"]]
    assert q.operator["code"] == "1234" and q.operator["for"] == cmd_id
    assert q.operator["offers"][0]["reply"] == "yes 1234"
    await helper.send_private(gid, "", "yes 1234\n", kind="chat", as_team=gid)   # not his to say
    [(_, no)] = await chan.poll()
    assert no.result == "refused" and done == []
    await andreas.send_private(gid, "", "yes 1234\n", kind="chat", as_team=gid)
    [(_, yes)] = await chan.poll()
    assert yes.result == "done" and done == [["ABCD"]]
    results = [m.operator["result"] for m in await helper.fetch_group(gid)
               if m.operator and m.operator["result"]]
    assert results == ["done", "asked", "refused", "done"]              # all readers see all
    assert await chan.poll() == []                                      # once only

    # someone who is not a reader writes to the channel: ignored
    outsider = net("outsider")
    await outsider.send_private(gid, "", "status\n", kind="chat")
    assert await chan.poll() == []


async def test_the_owner_sets_up_channels_from_the_command_line(net, capsys):
    import json
    from argparse import Namespace

    from unseenet import cli

    class App:
        def __init__(self, s):
            self.session = s

    def ns(**kw):
        return Namespace(json=True, identity=None, **kw)
    owner, andreas, node3, replica2 = net("owner"), net("andreas"), net("node3"), net("replica2")
    await andreas.ensure_inbox()
    made = {}
    for name, server in (("operator.node3", node3), ("operator.replica2", replica2)):
        await cli.c_operator(App(owner), ns(what="create", name=name, server_name=name[9:]))
        gid = json.loads(capsys.readouterr().out)["group"]
        await cli.c_operator(App(owner), ns(what="add-server", channel=gid,
                                            key=oc.make_channel_key(server, gid)))
        capsys.readouterr()
        made[name] = gid
    # one operator on every channel at once (section 3.4), each with its own team key
    await cli.c_operator(App(owner), ns(what="add", key=andreas.identity().key_text,
                                        channels="all"))
    added = json.loads(capsys.readouterr().out)["added"]
    assert set(added) == set(made.values()) and len(set(added.values())) == 2
    for gid in made.values():
        assert owner.manifest_data(gid)["operator_channel"] is True
        assert len(owner.manifest_data(gid)["readers"]) == 2      # the server and andreas
    await cli.c_operator(App(owner), ns(what="channels"))
    assert {r["group"] for r in json.loads(capsys.readouterr().out)} == set(made.values())
    # removed from one, kept in the other
    one = made["operator.node3"]
    await cli.c_operator(App(owner), ns(what="remove", key=added[one], channels=one))
    assert json.loads(capsys.readouterr().out)["removed"] == [one]
    assert added[one] not in owner.manifest_data(one)["readers"]
    assert added[made["operator.replica2"]] in owner.manifest_data(made["operator.replica2"])["readers"]
