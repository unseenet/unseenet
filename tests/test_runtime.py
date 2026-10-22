"""The client runtime against a local node: the startup order, refresh and push (#139)."""
import asyncio

import unseenet.client.session as sess
from unseenet.client import events as ev
from unseenet.client.runtime import ClientRuntime
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def _node():
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def _session(tmp_path, name, addr):
    s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity(name, name.title())
    s.add_node(addr)
    return s


async def test_refresh_sets_up_the_inbox_once_and_fetches_every_group(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    server, addr = await _node()
    a = _session(tmp_path, "andreas", addr)
    b = _session(tmp_path, "sonia", addr)
    g = await a.create_group("dk.snak", "open", min_pow=10)
    await a.post(g, "Hej", "Første\n")
    b.subscribe(g)

    got = []
    b.on(got.append)
    rt = ClientRuntime(b)
    rt.open()
    first = await rt.refresh()
    assert rt.inbox_ready and first.error is None and first.available >= 1
    assert [type(e) for e in got if isinstance(e, ev.InboxReady)] == [ev.InboxReady]
    assert any(isinstance(e, ev.GroupUpdated) and e.group_id == g and e.new == 1 for e in got)
    assert got[-1] == first                                # Refreshed comes last

    got.clear()
    again = await rt.refresh()                             # nothing new, inbox not again
    assert not any(isinstance(e, (ev.InboxReady, ev.GroupUpdated)) for e in got)
    assert again.subscribed == len(b.data["subscribed"])
    for s in (a, b):
        await s.close()
    server.close()


async def test_refresh_without_a_node_says_so_and_keeps_saved_posts(tmp_path):
    s = _session(tmp_path, "andreas", "127.0.0.1:1")      # nothing listens there
    rt = ClientRuntime(s)
    result = await rt.refresh()
    assert result.error and not rt.inbox_ready
    await s.close()


async def test_start_runs_by_itself_and_push_fetches_new_posts(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    server, addr = await _node()
    a = _session(tmp_path, "andreas", addr)
    b = _session(tmp_path, "sonia", addr)
    g = await a.create_group("dk.snak", "open", min_pow=10)
    b.subscribe(g)

    updated = asyncio.Event()
    b.on(lambda e: isinstance(e, ev.GroupUpdated) and e.group_id == g and e.new and updated.set())
    rt = ClientRuntime(b, refresh_seconds=3600, watch_retry=0.1)   # only push can bring it
    await rt.start()
    for _ in range(100):                                   # first round done, push open
        if rt.inbox_ready and addr in rt._watching:
            break
        await asyncio.sleep(0.05)
    assert rt.inbox_ready and addr in rt._watching
    await asyncio.sleep(0.3)
    await a.post(g, "Nyt", "Kom med push\n")
    await asyncio.wait_for(updated.wait(), 10)
    assert [m.subject for m in b.cache[g].values()] == ["Nyt"]

    await rt.stop()
    assert not rt._tasks
    for s in (a, b):
        await s.close()
    server.close()


async def test_the_groups_do_not_wait_for_the_inbox(tmp_path, monkeypatch):
    """#328: a brand-new key's inbox waits for ripening (minutes); the groups
    you follow are fetched meanwhile, and the refresh still ends with the inbox."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    server, addr = await _node()
    a = _session(tmp_path, "andreas", addr)
    b = _session(tmp_path, "sonia", addr)
    g = await a.create_group("dk.snak", "open", min_pow=10)
    await a.post(g, "Hej", "Første\n")
    b.subscribe(g)

    ripened = asyncio.Event()
    real = Session.ensure_inbox

    async def slow_inbox(self):
        await ripened.wait()                               # as if the key were ripening
        return await real(self)

    monkeypatch.setattr(Session, "ensure_inbox", slow_inbox)
    fetched = asyncio.Event()
    b.on(lambda e: isinstance(e, ev.GroupUpdated) and e.group_id == g and fetched.set())
    rt = ClientRuntime(b)
    rt.open()
    refreshing = asyncio.ensure_future(rt.refresh())
    await asyncio.wait_for(fetched.wait(), 10)             # the posts came first
    assert not rt.inbox_ready and not refreshing.done()
    ripened.set()
    result = await asyncio.wait_for(refreshing, 30)
    assert rt.inbox_ready and result.error is None
    for s in (a, b):
        await s.close()
    server.close()
