"""What new has landed in For you, for clients to tell (unseenet-gui#126, unseenet-tui#4)."""
from datetime import timedelta

import pytest

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI
from unseenet.client.session import Session, SessionError
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def two(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = "127.0.0.1:%d" % server.sockets[0].getsockname()[1]
    made = []

    def person(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        made.append(s)
        return s
    yield person
    for s in made:
        await s.close()
    server.close()


def test_the_choice(tmp_path):
    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    assert s.notification_settings() == {"on": None, "content": False}       # ask, hidden
    assert s.set_notification_settings(on=True) == {"on": True, "content": False}
    assert s.set_notification_settings(content=True)["on"] is True
    with pytest.raises(SessionError):
        s.set_notification_settings(on="yes")
    from unseenet.client.session.state import SETTINGS
    assert "notifications" in SETTINGS                                       # follows you


async def test_new_private_lines_once_and_never_old_ones(two):
    me, sonia = two("me"), two("sonia")
    await me.ensure_inbox()
    await sonia.ensure_inbox()
    await sonia.send_chat("contact:" + me.identity().key_text, "Gammel")
    await me.fetch_group(me.my_inbox)
    assert me.notifications()["count"] == 0                 # the first time: a baseline
    first = await sonia.send_chat("contact:" + me.identity().key_text, "Hej")
    await me.fetch_group(me.my_inbox)
    got = me.notifications()
    assert got["count"] == 1 and got["items"][0]["id"] == first
    assert got["items"][0]["why"] == "private" and got["items"][0]["chat"] is True
    assert "text" not in got["items"][0] and "who" not in got["items"][0]     # hidden by default
    assert me.notifications()["count"] == 0                 # told once
    me.set_notification_settings(content=True)
    await sonia.send_chat("contact:" + me.identity().key_text, "Er du der?")
    await me.fetch_group(me.my_inbox)
    item = me.notifications()["items"][0]
    assert item["text"] == "Er du der?" and "Sonia" in item["who"]
    await me.send_chat("contact:" + sonia.identity().key_text, "Ja")      # my own: nothing
    await sonia.fetch_group(sonia.my_inbox)
    sonia.notifications()                                    # her baseline
    await me.send_chat("contact:" + sonia.identity().key_text, "Igen")
    await sonia.fetch_group(sonia.my_inbox)
    assert [i["why"] for i in sonia.notifications()["items"]] == ["private"]


async def test_the_local_api(two):
    me = two("me")
    await me.ensure_inbox()
    api = LocalAPI(session=me)
    assert api.notifications()["count"] == 0
    assert api.settings()["notifications"] == {"on": None, "content": False}
    api.set_settings({"notifications": {"on": False}})
    assert api.settings()["notifications"]["on"] is False
