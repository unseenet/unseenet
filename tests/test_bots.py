"""Bots marked and hidden (unseenet #163, UN-RFC 0022 section 4, UN-RFC 0030 section 6)."""

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI
from unseenet.client.runtime import ClientRuntime
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def test_a_bot_is_marked_and_can_be_hidden(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    bot, person, reader = session("vejret"), session("sonia"), session("andreas")
    g = await person.create_group("dk.snak", "open", min_pow=8)
    bot.subscribe(g)
    await bot.fetch_group(g)
    await bot.publish_profile({"v": 1, "about": "Vejret hver morgen", "bot": True})
    await bot.post(g, "Vejret", "Sol\n")
    await person.post(g, "Hej", "Fra et menneske\n")

    reader.subscribe(g)
    await reader.fetch_group(g)
    assert not reader.is_bot(bot.identity().key_text)        # not read yet: no mark, no guess
    rt = ClientRuntime(reader)
    assert await rt.read_profiles() >= 2                       # both authors, in one batch
    assert reader.is_bot(bot.identity().key_text)
    assert not reader.is_bot(person.identity().key_text)
    assert await rt.read_profiles() == 0                       # cached for a day

    api = LocalAPI(session=reader)
    rows = {r["message"]["subject"]: r for r in api.group(g)["rows"]}
    assert rows["Vejret"]["bot"] is True and rows["Hej"]["bot"] is False

    api.set_settings({"hide_bots": True})
    assert api.settings()["hide_bots"] is True
    assert [r["message"]["subject"] for r in api.group(g)["rows"]] == ["Hej"]
    reader.set_hide_bots(False)
    assert len(api.group(g)["rows"]) == 2
    for s in (bot, person, reader):
        await s.close()
    server.close()
