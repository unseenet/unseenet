"""A node that does not answer: Tor's timeout is a ConnectionError like any node away,
and reading manifests asks your other nodes (found running tools/project/team_contact.py,
27 Oct 2026)."""

import pytest
from python_socks import ProxyTimeoutError

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core import tor
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def test_a_tor_timeout_is_a_connection_error(monkeypatch):
    calls = []

    class Slow:
        async def connect(self, **kw):
            calls.append(kw)
            raise ProxyTimeoutError("Proxy connection timed out: 60")

    monkeypatch.setattr(tor.Proxy, "from_url", staticmethod(lambda *a, **k: Slow()))
    monkeypatch.setattr(tor, "ONION_RETRY_PAUSES", (0.0,))
    with pytest.raises(ConnectionError, match="in time"):
        await tor.open_connection("abcdefghijklmnop.onion:119", 9050)
    assert len(calls) == 2                                    # tried again once


async def test_manifests_are_read_from_another_node(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    good = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    try:
        s.add_node(good)
        gid = await s.create_group("alt.snak", "open", min_pow=8)
        s.add_node("127.0.0.1:9")                             # nothing listens there
        s.data["nodes"].remove("127.0.0.1:9")
        s.data["nodes"].insert(0, "127.0.0.1:9")              # ... and it is the default
        s.data["groups"][gid].pop("node", None)
        assert s.node_for(gid) == "127.0.0.1:9"
        m = await s.fetch_manifest(gid)
        assert m is not None and m.group_id == gid
        with pytest.raises(OSError):                          # a named node is asked alone
            await s.fetch_manifest(gid, node="127.0.0.1:9")
    finally:
        await s.close()
        server.close()
