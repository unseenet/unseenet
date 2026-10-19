"""Clients warn before posting in a group with portals (UN-RFC 0023 section 3.5)."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session, SessionError
from unseenet.core import portals
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}
MATRIX = {"network": "matrix", "source": "#unseenet:unseenet.org", "gateway": ["ed25519:x"]}
NOSTR = {"network": "nostr", "source": "wss://nostr.unseenet.org'test", "gateway": ["ed25519:x"]}


def test_reading_and_wording():
    m = {"portals": [MATRIX, {"network": "matrix"}, "junk", NOSTR]}
    found = portals.portals(m)
    assert found == [("matrix", "#unseenet:unseenet.org"), ("nostr", "wss://nostr.unseenet.org'test")]
    text = portals.warning("unseenet", found)
    assert "Matrix and Nostr" in text and "outside Tor" in text and "#unseenet:unseenet.org" in text
    assert portals.fingerprint(found) == portals.fingerprint(list(reversed(found)))
    assert portals.portals({}) == []


async def test_post_needs_the_user_to_accept_each_set_of_portals(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    s = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("andreas", "Andreas")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    gid = await s.create_group("snak", "open", min_pow=10)
    await s.post(gid, "No portal", "Fine.\n")                    # nothing to accept

    entry = s.group_entry(gid)
    entry["manifest"] = {**entry["manifest"], "portals": [MATRIX]}
    assert "Matrix" in s.portal_warning(gid)
    with pytest.raises(SessionError, match="portal"):
        await s.post(gid, "Hello", "Out there too.\n")
    s.accept_portals(gid)
    assert s.portal_warning(gid) is None
    await s.post(gid, "Hello", "Out there too.\n")

    entry["manifest"] = {**entry["manifest"], "portals": [MATRIX, NOSTR]}   # a new portal
    assert "Nostr" in s.portal_warning(gid)
    server.close()
    await s.close()
