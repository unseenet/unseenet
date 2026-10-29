"""Mark a whole group read (#625), how far keep=False groups were read survives a restart
(#735), and a Markdown preview from the core (#632)."""
import argparse
import json

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session, SessionError
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def _node():
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def _session(tmp_path, name, node):
    s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity(name, name.title())
    s.add_node(node)
    return s


async def test_mark_a_whole_group_read(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    server, addr = await _node()
    owner, reader = _session(tmp_path, "owner", addr), _session(tmp_path, "reader", addr)
    try:
        gid = await owner.create_group("dk.lang", "open", min_pow=8)
        for i in range(3):
            await owner.post(gid, f"Emne {i}", "Tekst\n")
        reader.subscribe(gid)
        await reader.fetch_group(gid)
        assert reader.unread_count(gid) == 3
        assert reader.mark_group_read(gid) == 3
        assert reader.unread_count(gid) == 0
        assert reader.mark_group_read(gid) == 0

        from unseenet.client.localapi import LocalAPI
        await owner.post(gid, "Ny", "Tekst\n")
        await reader.fetch_group(gid)
        api = LocalAPI(session=reader)
        assert api.mark_read(gid, [], all_=True) == {"ok": True, "marked": 1}
    finally:
        for s in (owner, reader):
            await s.close()
        server.close()


async def test_keep_false_marks_survive_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    server, addr = await _node()
    owner, bot = _session(tmp_path, "owner", addr), _session(tmp_path, "bot", addr)
    try:
        gid = await owner.create_group("dk.watch", "open", min_pow=8)
        await owner.post(gid, "Først", "1\n")
        got = await bot.fetch_group(gid, keep=False)
        assert [m.subject for m in got] == ["Først"]
        marks = bot.read_marks()
        assert marks[gid]["node"] == addr and marks[gid]["high"] > 0
        await bot.close()

        again = Session(Vault.open(tmp_path / "bot.vault", "pw", **KDF), status=lambda *_: None)
        await owner.post(gid, "Så", "2\n")
        got = await again.fetch_group(gid, keep=False)      # only what came since
        assert [m.subject for m in got] == ["Så"]
        await again.close()

        other = _session(tmp_path, "other", addr)               # marks a program kept itself
        other.set_read_marks(marks)
        assert other._high[gid] == marks[gid]["high"] and other.read_marks() == marks
        other.set_read_marks({gid: {"node": "elsewhere:1", "high": 99}})   # another node's
        assert other._high[gid] == marks[gid]["high"]
        await other.close()
    finally:
        await owner.close()
        server.close()


def test_preview_is_the_tree_readers_get(tmp_path):
    s = Session(Vault.open(tmp_path / "p.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    out = s.preview("**Hej** :tada:\n\n-- \nMig")
    assert out["signature"] == "Mig"
    flat = json.dumps(out["tree"], ensure_ascii=False)
    assert '"strong"' in flat and "🎉" in flat
    plain = s.preview("**Hej**", content_type="text/plain; charset=utf-8")
    assert '"strong"' not in json.dumps(plain["tree"])
    with pytest.raises(SessionError):
        s.preview("x", kind="reaction")
    with pytest.raises(SessionError):
        s.preview("x" * (300 * 1024))

    s.add_node("127.0.0.1:9")
    from unseenet.client.localapi import LocalAPI
    api = LocalAPI(session=s)
    assert api.markup({"text": "*kursiv*", "kind": "chat"})["tree"]
    assert '"em"' not in json.dumps(api.markup({"text": "*kursiv*", "markdown": False}))
    with pytest.raises(SessionError):
        api.markup({})


async def test_cli_read_all(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    from unseenet import cli
    monkeypatch.setattr(cli, "DEFAULT_POW", 8)
    server, addr = await _node()
    owner = _session(tmp_path, "owner", addr)
    try:
        gid = await owner.create_group("dk.cli", "open", min_pow=8)
        await owner.post(gid, "Emne", "Tekst\n")
        app = cli.App(Vault.open(tmp_path / "me.vault", "pw", **KDF))
        app.data["nodes"].append(addr)
        await cli.c_id_new(app, argparse.Namespace(name="me", display=None))
        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))
        await cli.c_read(app, argparse.Namespace(identity=None, json=True, group=gid, all=True))
        assert json.loads(printed[-1]) == {"group": gid, "marked": 1}
        if app._session is not None:
            await app._session.close()
    finally:
        await owner.close()
        server.close()
