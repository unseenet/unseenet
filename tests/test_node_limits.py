"""A full node refuses new clients with 400 but still lets peers in (#296, UN-RFC 0005 6)."""
import pytest

from unseenet.core import crypto
from unseenet.core.store import Store
from unseenet.nntp import Client, NNTPError
from unseenet.node.peering import authenticate_with_key
from unseenet.node.server import Node, NodeConfig, PeerConfig, auto_max_clients


async def test_a_full_node_refuses_clients_but_not_peers():
    peer_key = crypto.Identity.generate()
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), max_clients=2,
                                    peers=[PeerConfig(name="friend", address="x.onion",
                                                      key=peer_key.key_text)]))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    first, second = await Client.connect(addr), await Client.connect(addr)
    await first.command("DATE", (111,))

    third = await Client.connect(addr)              # greeted: a peer would authenticate now
    await third.fetch_capabilities()                # allowed while full
    with pytest.raises(NNTPError) as refused:
        await third.command("LIST", (215,))
    assert refused.value.code == 400 and "try another node" in str(refused.value)
    assert node.stats.refused == 1

    peer = await Client.connect(addr)               # a peer gets in, full or not
    await peer.fetch_capabilities()
    await authenticate_with_key(peer, peer_key, node.key.public_key)
    await peer.command("DATE", (111,))
    snap = await node.stats.snapshot(node)
    assert snap["connections"]["max_clients"] == 2 and snap["connections"]["refused"] == 1

    await first.quit()                              # room again: a new client is served
    for c in (second, peer):
        await c.quit()
    again = await Client.connect(addr)
    await again.command("DATE", (111,))
    await again.quit()
    server.close()


def test_auto_is_a_ceiling_not_rationing():
    assert auto_max_clients() >= 16
    assert NodeConfig(max_clients=500).client_limit() == 500
