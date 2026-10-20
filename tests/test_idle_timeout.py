"""An idle connection is closed quietly, without an unhandled-exception traceback."""

import asyncio
import logging

from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig, Session


async def test_idle_connection_closes_quietly(monkeypatch, caplog):
    monkeypatch.setattr(Session, "IDLE_SECONDS", 0.2)
    node = Node(Store(), NodeConfig(min_pow=8))
    server = await node.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    caplog.set_level(logging.ERROR, logger="asyncio")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await reader.readline()                                  # greeting
        assert await asyncio.wait_for(reader.read(), 5) == b""   # closed by the node
        writer.close()
        await asyncio.sleep(0.1)
    finally:
        server.close()
    assert not [r for r in caplog.records if "Unhandled exception" in r.getMessage()]
