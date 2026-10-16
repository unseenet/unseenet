"""The command-line client: listing your own groups and removing them (UN-RFC 0013)."""

from argparse import Namespace

import pytest

from unseenet import cli
from unseenet.core import crypto
from unseenet.core.groups import personal_inbox_id
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DEFAULT_POW", BITS)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    address = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def app(name):
        a = cli.App(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF))
        a.data["nodes"].append(address)
        return a

    yield node, app
    server.close()


async def create(app, name, identity=None):
    await cli.c_group_create(app, Namespace(name=name, type="open", local=False, title="t",
                                            description="", min_pow=BITS, identity=identity))
    return next(g for g in app.data["groups"] if g.startswith(name + "@"))


async def test_groups_mine_lists_only_own_groups(setup, capsys):
    _, app = setup
    me, other = app("me"), app("other")
    await cli.c_id_new(me, Namespace(name="andreas", display=None))
    await cli.c_id_new(me, Namespace(name="second", display=None))
    await cli.c_id_new(other, Namespace(name="someone", display=None))
    mine = await create(me, "dk.test")
    mine2 = await create(me, "dk.prove", identity="second")
    theirs = await create(other, "dk.andet")
    capsys.readouterr()

    await cli.c_groups(me, Namespace(pattern="*", mine=True))
    out = capsys.readouterr().out
    assert mine in out and "[owned by andreas]" in out
    assert mine2 in out and "[owned by second]" in out
    assert theirs not in out


async def test_group_remove_removes_own_groups(setup, capsys):
    node, app = setup
    me = app("me")
    await cli.c_id_new(me, Namespace(name="andreas", display=None))
    a = await create(me, "dk.test")
    b = await create(me, "dk.fejl")
    me.data["subscribed"] = [a]

    await cli.c_group_remove(me, Namespace(group=[a, b], reason="test", yes=True))
    out = capsys.readouterr().out
    assert f"Removed {a}" in out and f"Removed {b}" in out
    assert node.store.tombstone(a) == "owner" and node.store.tombstone(b) == "owner"
    assert a not in me.data["groups"] and a not in me.data["subscribed"]


async def test_group_remove_refuses_what_it_should(setup, monkeypatch):
    node, app = setup
    me, other = app("me"), app("other")
    await cli.c_id_new(me, Namespace(name="andreas", display=None))
    await cli.c_id_new(other, Namespace(name="someone", display=None))
    theirs = await create(other, "dk.andet")
    mine = await create(me, "dk.test")
    inbox = personal_inbox_id(me.identity().public_key)

    for target, msg in [(theirs, "none of the identities"), ("dk.test", "full group ID"),
                        (inbox, "personal inbox")]:
        with pytest.raises(SystemExit) as e:
            await cli.c_group_remove(me, Namespace(group=[target], reason=None, yes=True))
        assert msg in str(e.value)

    # one bad ID stops the whole batch before anything is posted
    with pytest.raises(SystemExit):
        await cli.c_group_remove(me, Namespace(group=[mine, theirs], reason=None, yes=True))
    assert node.store.tombstone(mine) is None

    # without --yes and without a terminal, nothing happens
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit) as e:
        await cli.c_group_remove(me, Namespace(group=[mine], reason=None, yes=False))
    assert "--yes" in str(e.value) and node.store.tombstone(mine) is None

    # a wrong answer at the prompt also does nothing
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    with pytest.raises(SystemExit):
        await cli.c_group_remove(me, Namespace(group=[mine], reason=None, yes=False))
    assert node.store.tombstone(mine) is None

    monkeypatch.setattr("builtins.input", lambda prompt: "remove")
    await cli.c_group_remove(me, Namespace(group=[mine], reason=None, yes=False))
    assert node.store.tombstone(mine) == "owner"


def test_parser_knows_the_new_options(monkeypatch):
    seen = {}

    async def fake(args):
        seen.update(vars(args))
    monkeypatch.setattr(cli, "client_command", fake)
    cli.client_main(["group-remove", "a@aaaaaaaaaaaaaaaa", "b@bbbbbbbbbbbbbbbb", "--yes",
                     "--reason", "typo"])
    assert seen["cmd"] == "group-remove" and seen["yes"] and seen["reason"] == "typo"
    assert seen["group"] == ["a@aaaaaaaaaaaaaaaa", "b@bbbbbbbbbbbbbbbb"]
    cli.client_main(["groups", "--mine"])
    assert seen["mine"]


def test_fingerprint_matches_group_suffix():
    ident = crypto.Identity.generate()
    assert personal_inbox_id(ident.public_key).endswith("@" + crypto.fingerprint(ident.public_key))


async def test_withdraw_own_post(setup, capsys):
    """UN-RFC 0004 section 7 from the command line: read shows the Message-ID,
    withdraw sends the cancel, the node deletes the post."""
    node, app = setup
    me = app("me")
    await cli.c_id_new(me, Namespace(name="andreas", display=None))
    gid = await create(me, "dk.test")
    await cli.c_post(me, Namespace(group=gid, subject="Ups", body="Forkert\n", identity=None))
    capsys.readouterr()
    await cli.c_read(me, Namespace(group=gid, identity=None))
    out = capsys.readouterr().out
    mid = next(line.split("Message-ID: ")[1].strip() for line in out.splitlines()
               if "Message-ID:" in line)
    assert node.store.get(mid) is not None
    await cli.c_withdraw(me, Namespace(group=gid, message_id=mid, yes=True, identity=None))
    assert node.store.get(mid) is None
    assert "Withdrawn" in capsys.readouterr().out
