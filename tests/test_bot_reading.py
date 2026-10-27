"""#669: a program that follows every group - start from now, skip by headers, keep
nothing but how far it has read."""

import pytest

import unseenet.client.session as sess
import unseenet.nntp as nntp
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
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


async def test_start_from_now_skip_and_keep_nothing(net, monkeypatch):
    owner, bot = net("owner"), net("bot")
    gid = await owner.create_group("alt.snak", "open", min_pow=8)
    for i in range(3):
        await owner.post(gid, f"Gammel {i}", "x\n")              # before the bot came
    await bot.skip_to_now(gid)
    assert bot.manifest_data(gid).get("name") == "alt.snak"      # its settings are known

    await owner.post(gid, "Ny", "spam spam\n")
    await owner.post(gid, "Re: Ny", "svar\n")
    asked = []
    orig = nntp.Client.article

    async def article(self, ident):
        asked.append(ident)
        return await orig(self, ident)
    monkeypatch.setattr(nntp.Client, "article", article)
    got = await bot.fetch_group(gid, skip=lambda h: h["Subject"].startswith("Re:"), keep=False)
    assert [m.subject for m in got] == ["Ny"]                     # nothing old, the reply skipped
    assert len(asked) == 1                                          # fetched: only that one
    assert bot.cache.get(gid, {}) == {}                             # nothing kept ...
    assert await bot.fetch_group(gid, keep=False) == []             # ... but how far it read

    # a manifest is never skipped: the group's settings follow
    await owner.update_group(gid, title="Snak om alt")
    await bot.fetch_group(gid, skip=lambda h: True, keep=False)
    assert bot.manifest_data(gid).get("title") == "Snak om alt"
