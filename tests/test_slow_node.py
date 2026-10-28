"""#704: one node that does not answer must not hold up the others - the groups of the
nodes that answered at once, the slow one awaited in the background and listed when it
answers, and its groups not fetched from it meanwhile."""
import asyncio

import unseenet.client.session as sess
from unseenet.client import events as ev
from unseenet.client import runtime as rtmod
from unseenet.client.runtime import ClientRuntime

from test_runtime import _node, _session


async def test_a_slow_node_does_not_hold_up_the_others(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    fast_server, fast = await _node()
    slow_server, slow = await _node()
    a = _session(tmp_path, "andreas", fast)
    g = await a.create_group("dk.snak", "open", min_pow=10)
    a.add_node(slow)
    b = _session(tmp_path, "sonia", fast)
    b.add_node(slow)
    b.subscribe(g)
    real_connect = type(b)._connect
    hold = asyncio.Event()

    async def connect(self, address, *args, **kw):
        if address == slow:
            await hold.wait()                   # its Tor has trouble with its guards
        return await real_connect(self, address, *args, **kw)
    monkeypatch.setattr(type(b), "_connect", connect)

    got = []
    b.on(got.append)
    groups = await asyncio.wait_for(b.list_groups(budget=0.2), 5)
    assert g in {x.group_id for x in groups}        # the fast node's, at once
    assert b.is_slow(slow) and slow not in b.unreachable
    try:                                            # nobody else waits behind it
        await asyncio.wait_for(b._call(lambda c: c, slow), 1)
        raise AssertionError("a call to the slow node should not wait")
    except sess.SessionError as exc:
        assert "not answering yet" in str(exc)

    monkeypatch.setattr(rtmod, "FIRST_ANSWER", 0.2)
    rt = ClientRuntime(b)
    done = await asyncio.wait_for(rt.refresh(), 10)   # not 100 s
    assert done.slow == (slow,) and done.error is None
    assert done.to_dict()["slow"] == [slow]

    got.clear()
    hold.set()                                      # it answers after all
    for _ in range(50):
        if not b.is_slow(slow) and any(isinstance(e, ev.Refreshed) for e in got):
            break
        await asyncio.sleep(0.1)
    assert not b.is_slow(slow)
    assert any(isinstance(e, ev.NodeState) and e.address == slow and e.up for e in got)
    assert any(isinstance(e, ev.Refreshed) and not e.slow for e in got)   # listed again
    for s in (a, b):
        await s.close()
    fast_server.close()
    slow_server.close()
