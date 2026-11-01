"""Transport addresses (UN-RFC 0064, #836): onion: and test:, bare onion addresses as
before, unknown schemes left out without error, several addresses per node."""

import json

import pytest

import unseenet.known_nodes as kn
from unseenet.core import transport as tr

ONION = "a" * 56 + ".onion"


def test_reading_and_writing_addresses():
    a = tr.parse(ONION)
    assert a == tr.parse("onion:" + ONION) == tr.parse("onion:" + ONION + ":119")
    assert a.text() == "onion:" + ONION and a.plain() == ONION
    assert tr.parse(ONION + ":1119").text() == f"onion:{ONION}:1119"
    t = tr.parse("test:127.0.0.1:1119")
    assert t == tr.parse("127.0.0.1:1119") and t.text() == "test:127.0.0.1:1119"
    assert tr.parse("localhost:1119").scheme == "test"
    assert tr.parse("i2p:somewhere") is None and tr.parse("rns:abc") is None    # reserved
    assert tr.parse("carrierpigeon:coop 7") is None                           # unknown: no error
    for bad in ("onion:short.onion", "test:nohost", "not a node!", "", ONION + ":0"):
        with pytest.raises(tr.AddressProblem):
            tr.parse(bad)
    assert tr.connect_target("onion:" + ONION) == ONION


def test_usable_addresses_onion_first(monkeypatch):
    monkeypatch.delenv("UNSEENET_TEST_ADDRESSES", raising=False)
    got = tr.usable(["test:10.0.0.1:1", "i2p:x", "onion:" + ONION, "garbage"])
    assert [a.text() for a in got] == ["onion:" + ONION]               # test: only when allowed
    got = tr.usable(["test:10.0.0.1:1", "onion:" + ONION], allow_test=True)
    assert [a.scheme for a in got] == ["onion", "test"]


def test_node_lists_take_transport_addresses(monkeypatch):
    other = "b" * 56 + ".onion"
    text = json.dumps({"v": 1, "updated": "x", "nodes": [
        {"name": "one", "address": "onion:" + ONION, "addresses": ["i2p:abc", other]},
        {"name": "far", "address": "rns:abc"},                         # nothing usable: left out
        {"name": "lab", "address": "test:127.0.0.1:1119"}]})
    monkeypatch.delenv("UNSEENET_TEST_ADDRESSES", raising=False)
    _, nodes = kn.parse_node_list(text)
    assert [(n.name, n.address, n.addresses) for n in nodes] == [("one", ONION, (other,))]
    monkeypatch.setenv("UNSEENET_TEST_ADDRESSES", "1")
    _, nodes = kn.parse_node_list(text)
    assert [n.address for n in nodes] == [ONION, "127.0.0.1:1119"]


async def test_a_connection_to_a_transport_address():
    import asyncio
    from unseenet.core.tor import open_connection

    async def hello(reader, writer):
        writer.write(b"200 hi\r\n")
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(hello, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await open_connection(f"test:127.0.0.1:{port}", None)
    assert (await reader.readline()).startswith(b"200")
    writer.close()
    server.close()
