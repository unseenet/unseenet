"""Level 4 by choice (#740, UN-RFC 0025 section 7): the level a key is ripened to on this
device, the time left at this device's speed, the runtime following the choice, one
setting for services, the local API and the CLI."""
import argparse
import json

import pytest

import unseenet.client.session as sess
from unseenet.client import runtime as rtmod
from unseenet.client.runtime import ClientRuntime, service_ripen_to
from unseenet.client.session import Session, SessionError
from unseenet.core import crypto
from unseenet.core import ripening as rp
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def _node():
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    return node, server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def _session(tmp_path, name="me"):
    s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity(name, name.title())
    return s


def test_the_target_is_this_devices_and_3_or_4(tmp_path):
    s = _session(tmp_path)
    assert s.ripening_target() is None                      # the program's default
    s.set_ripening_target(4)
    assert s.ripening_target() == 4
    again = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    assert again.ripening_target() == 4                     # kept with the key's chain
    for bad in (2, 5):
        with pytest.raises(SessionError):
            s.set_ripening_target(bad)


def test_time_left_at_this_devices_speed(tmp_path):
    s = _session(tmp_path)
    assert s.ripening_speed() is None and s.ripening_seconds_left(3) is None
    s._note_speed(None, 100_000, 1.0)
    s._note_speed(None, 300_000, 1.0)                       # the newest weighs half
    assert s.ripening_speed() == 200_000
    th = next(t for lv, t, _ in rp.LEVELS if lv == 4)
    assert s.ripening_seconds_left(4) == pytest.approx(th / 200_000)


def test_one_setting_for_services(monkeypatch):
    monkeypatch.delenv(rtmod.RIPEN_TO_ENV, raising=False)
    assert service_ripen_to() == rtmod.SERVICE_RIPEN_TO
    monkeypatch.setenv(rtmod.RIPEN_TO_ENV, "4")
    assert service_ripen_to() == 4
    assert service_ripen_to(2) == 2                         # its own configuration wins
    monkeypatch.setenv(rtmod.RIPEN_TO_ENV, "9")
    with pytest.raises(ValueError):
        service_ripen_to()


@pytest.mark.usefixtures("ripening_rules")
async def test_the_runtime_follows_the_choice(tmp_path, monkeypatch):
    pytest.importorskip("chiavdf")
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node, server, addr = await _node()
    s = Session.from_key(crypto.Identity.generate(), tmp_path / "bot.json", status=lambda *_: None)
    s.add_node(addr)
    rt = ClientRuntime(s, ripen_to=1)
    assert rt.ripening_to() == 1
    await rt.ripen()
    assert s.ripening().level == 1
    s.set_ripening_target(3)                                # chosen: over the program's own
    assert rt.ripening_to() == 3
    await rt.ripen()
    assert s.ripening().level == 3 and s.published_level() == 3
    assert s.ripening_speed() is not None                    # measured while proving
    await s.close()
    server.close()


async def test_local_api_and_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    from unseenet.client.localapi import LocalAPI
    s = _session(tmp_path)
    s.add_node("127.0.0.1:9")                               # set up: a node, never asked
    api = LocalAPI(session=s)
    r = api.state()["ripening"]
    assert r["target"] == 3 and r["chosen"] is None
    r = await api.set_ripening_to(4)
    assert r["target"] == 4 and r["chosen"] == 4
    with pytest.raises(SessionError):
        await api.set_ripening_to(5)
    s.save()

    from unseenet import cli
    app = cli.App(Vault.open(tmp_path / "me.vault", "pw", **KDF))
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))
    await cli.c_ripening(app, argparse.Namespace(identity=None, json=True, to=3))
    out = json.loads(printed[-1])
    assert out["target"] == 3 and out["chosen"] == 3 and out["estimated"] is True
    assert out["seconds_left"] > 0
