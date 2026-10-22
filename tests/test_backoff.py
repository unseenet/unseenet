"""Reconnecting with a random, growing wait (#297, UN-RFC 0043 section 4.4)."""
import asyncio

import pytest

from unseenet.client.session import Session, SessionError
from unseenet.core.backoff import Backoff
from unseenet.core.vault import Vault

KDF = {"ops": 1, "mem": 8192 * 1024}


def test_waits_are_random_double_cap_and_start_over():
    now = [0.0]
    b = Backoff(rand=lambda lo, hi: hi, clock=lambda: now[0])      # always the top of the range
    assert [b.next() for _ in range(6)] == [30, 60, 120, 240, 300, 300]
    b.up()
    now[0] += 10
    b.down()                                    # up only 10 s: keeps growing
    assert b.next() == 300
    b.up()
    now[0] += 61
    b.down()                                    # up a minute: starts over
    assert b.next() == 30
    low = Backoff(rand=lambda lo, hi: lo)
    assert low.next() == 1 and low.next() == 2
    spread = {round(Backoff().next(), 3) for _ in range(50)}
    assert len(spread) > 40 and all(1 <= w <= 30 for w in spread)


async def _full_node():
    """A node that greets and then answers every command with 400, as a full one does."""
    async def handle(reader, writer):
        writer.write(b"200 ready\r\n")
        while await reader.readline():
            writer.write(b"400 too many connections, try another node\r\n")
            await writer.drain()
            break
        writer.close()
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def test_a_refusal_or_a_failure_backs_off(tmp_path):
    server, addr = await _full_node()
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(addr)

    async def date(c):
        return await c.command("DATE", (111,))
    with pytest.raises(SessionError, match="is full; trying again in"):
        await s._call(date)
    assert 1 <= s.retry_in(addr) <= 30
    with pytest.raises(ConnectionError, match="trying again in"):   # not before its time
        await s._call(date)
    s.add_node(addr, default=True)              # chosen on purpose: at once
    assert s.retry_in(addr) == 0

    dead = "127.0.0.1:1"                        # nothing listens: a failure backs off too
    with pytest.raises((OSError, ConnectionError)):
        await s._call(date, node=dead)
    assert s.retry_in(dead) > 0
    await s.close()
    server.close()


async def test_a_real_full_node_is_left_for_later(tmp_path):
    """Against the node's own limit (#296): refused after CAPABILITIES, then backed off."""
    from unseenet.core.store import Store
    from unseenet.nntp import Client
    from unseenet.node.server import Node, NodeConfig
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), max_clients=1))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    holder = await Client.connect(addr)                     # the one place there is
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(addr)
    with pytest.raises(SessionError, match="is full"):
        await s.list_groups()
    assert s.retry_in(addr) > 0 and node.stats.refused == 1
    await holder.quit()
    await s.close()
    server.close()
