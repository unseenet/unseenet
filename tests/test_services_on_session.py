"""Services (gateways, bots, registrars) post through Session too (UN-RFC 0025, #139)."""
import argparse
import asyncio
import json

import pytest

import unseenet.client.session as sess
from unseenet.client.runtime import ClientRuntime
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core import ripening as rp
from unseenet.core.article import new_article
from unseenet.core.groups import make_group_id, manifest_article
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig

pytest.importorskip("chiavdf")
pytestmark = pytest.mark.usefixtures("ripening_rules")


async def _node():
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    return node, server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def test_the_state_file_never_holds_the_key(tmp_path):
    ident = crypto.Identity.generate()
    state = tmp_path / "gw.state.json"
    s = Session.from_key(ident, state, name="gateway", status=lambda *_: None)
    s.add_node("127.0.0.1:1")
    s.save()
    text = state.read_text()
    assert ident.seed.hex() not in text and "identities" not in text
    assert json.loads(text)["data"]["nodes"] == ["127.0.0.1:1"]
    again = Session.from_key(ident, state, status=lambda *_: None)   # comes back
    assert again.nodes == ["127.0.0.1:1"] and again.identity().key_text == ident.key_text
    with pytest.raises(ValueError, match="another key"):
        Session.from_key(crypto.Identity.generate(), state)


async def test_an_article_built_elsewhere_is_posted_with_ripening(tmp_path, monkeypatch):
    """What a gateway does: build and sign its own article, let Session post it."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, server, addr = await _node()
    ident = crypto.Identity.generate()
    s = Session.from_key(ident, tmp_path / "gw.json", status=lambda *_: None)
    s.add_node(addr)
    gid = make_group_id("usenet.test", ident.public_key)
    data = {"v": 1, "name": "usenet.test", "type": "open", "owner": ident.key_text,
            "serial": 1, "min_pow": 0}
    await s.post_article(manifest_article(ident, gid, data, 20))      # ripens first
    art = new_article(gid, "From Usenet", "imported\n", from_name="Gateway",
                      extra=[("X-Gateway", "usenet")])
    art.finalize(ident, 20)
    msgid = await s.post_article(art)
    stored = node.store.get(msgid).decode()
    assert "Key-Ripening: vdf-cg1" in stored and "X-Gateway: usenet" in stored
    assert s.ripening().level == 0
    # the chain survives a restart: the state file has it, so no ripening again
    await s.close()
    again = Session.from_key(ident, tmp_path / "gw.json", status=lambda *_: None)
    assert again.ripening().t == s.ripening().t and again.published_level() == 0
    server.close()


async def test_the_runtime_ripens_on_and_publishes_each_level(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, server, addr = await _node()
    ident = crypto.Identity.generate()
    s = Session.from_key(ident, tmp_path / "bot.json", status=lambda *_: None)
    s.add_node(addr)
    rt = ClientRuntime(s, ripen_to=2)
    await rt.ripen()
    assert s.ripening().level == 2 and s.published_level() == 2
    m = node.store.manifest(s.ripe_group())
    assert rp.Chain.from_manifest(m.raw["ripening"]).level == 2
    await s.close()
    server.close()


async def test_stopping_ends_a_segment_at_once(tmp_path):
    ident = crypto.Identity.generate()
    s = Session.from_key(ident, tmp_path / "bot.json", status=lambda *_: None)
    rp.scale_for_tests(0)                     # real thresholds: a segment of minutes
    rt = ClientRuntime(s, ripen_to=0)
    task = asyncio.create_task(rt.ripen())
    await asyncio.sleep(0.5)
    rt.stop_ripening()
    await asyncio.wait_for(task, 5)           # back within seconds, not minutes
    assert s.ripening().t == 0
    rp.scale_for_tests(16)


async def test_the_ripen_command(tmp_path, monkeypatch, capsys):
    from unseenet.cli import ripen_command
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, server, addr = await _node()
    ident = crypto.Identity.generate()
    key = tmp_path / "bot.key"
    key.write_text(ident.seed.hex())
    args = argparse.Namespace(to=1, key_file=str(key), state=None, node=[addr], publish=True,
                              public_key=None,
                              identity=None, vault=None)
    await ripen_command(args)
    out = capsys.readouterr().out
    assert "level 1" in out and "published ripe@" in out
    assert node.store.manifest(make_group_id(rp.GROUP_NAME, ident.public_key)) is not None
    assert (tmp_path / "bot.key.state.json").exists()
    server.close()


async def test_ripening_from_the_public_key_alone(tmp_path, monkeypatch, capsys):
    """Computed on another machine without the secret; the service picks it up."""
    from unseenet.cli import ripen_command
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    ident = crypto.Identity.generate()
    state = tmp_path / "gw.state.json"
    args = argparse.Namespace(to=0, public_key=ident.key_text, state=str(state), key_file=None,
                              node=None, publish=False, identity=None, vault=None)
    await ripen_command(args)
    assert ident.seed.hex() not in state.read_text()
    s = Session.from_key(ident, state, status=lambda *_: None)
    assert s.ripening().level == 0 and s.published_level() is None   # computed, not published
    node, server, addr = await _node()
    s.add_node(addr)
    await s.ensure_ripe()                                            # nothing to compute: publish
    assert node.store.manifest(s.ripe_group()) is not None
    await s.close()
    server.close()
