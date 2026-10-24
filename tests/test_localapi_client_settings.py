"""#442, unseenet-gui#84: a client's own settings and where your state is kept, in the
local client API (UN-RFC 0046 section 4.8, UN-RFC 0044 sections 4.2 and 7.4)."""

import pytest

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI
from unseenet.client.localapi import server as srv
from unseenet.client.session import Session, SessionError
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def api(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    yield LocalAPI(session=s)
    await s.close()
    server.close()


async def test_a_clients_own_settings(api):
    assert api.client_settings("gui") == {"client": "gui", "settings": {}}
    got = api.set_client_settings("gui", {"theme": "dark", "font-size": 15})
    assert got["settings"] == {"theme": "dark", "font-size": 15}
    assert api.session.client_setting("gui", "theme") == "dark"     # kept with your state
    assert api.client_settings("tui")["settings"] == {}              # each client its own
    assert api.set_client_settings("gui", {"theme": None})["settings"] == {"font-size": 15}
    for client, data, match in [("GUI", {}, "lowercase"), ("gui", {"Theme": "x"}, "lowercase"),
                                ("gui", {"theme": ["x"]}, "a string"),
                                ("gui", {"theme": "x" * 257}, "at most 256")]:
        with pytest.raises(SessionError, match=match):
            api.set_client_settings(client, data)
    with pytest.raises(SessionError):                                # nothing half changed
        api.set_client_settings("gui", {"layout": "wide", "bad": {}})
    assert "layout" not in api.client_settings("gui")["settings"]
    routes = {(m, p) for m, p, _ in srv.ROUTES}
    assert {("GET", "/api/settings/clients/{client}"),
            ("POST", "/api/settings/clients/{client}")} <= routes


async def test_where_your_state_is_kept(api):
    assert api.settings()["state_local"] is False                    # in the network
    assert (await api.change_settings({"state_local": True, "hide_bots": True}))["state_local"]
    assert api.session.state_kept_local() and api.settings()["hide_bots"]
    assert (await api.change_settings({"state_local": False}))["state_local"] is False
    with pytest.raises(SessionError, match="true or false"):
        await api.change_settings({"state_local": "yes"})
    with pytest.raises(SessionError, match="unknown setting"):
        await api.change_settings({"state_local": True, "nope": 1})
    assert not api.session.state_kept_local()                       # refused as a whole
