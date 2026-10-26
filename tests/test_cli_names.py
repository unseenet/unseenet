"""#578: names from the command line - give a name under yours, see it, choose it."""
import json
from argparse import Namespace

import pytest

from unseenet import cli
from unseenet import names as nm
from unseenet.core import crypto
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(cli, "DEFAULT_POW", BITS)
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", BITS)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    address = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    apps = []

    async def app(name):
        a = cli.App(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF))
        a.data["nodes"].append(address)
        await cli.c_id_new(a, Namespace(name=name, display=None))
        apps.append(a)
        return a

    yield app
    for a in apps:
        if a._session is not None:
            await a._session.close()
    server.close()


def _store(app, reg, certs):
    app.data["naming"] = {"names": {"registrars": [reg.key_text], "revoked": [],
                                    "certs": [c.to_json() for c in certs]}}


def _json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _a(**kw):
    return Namespace(identity=None, json=True, **kw)


async def test_give_see_and_choose_a_name(setup, capsys):
    andreas, sonia = await setup("andreas"), await setup("sonia")
    reg = crypto.Identity.generate()
    held = nm.make_certificate(reg, "lorensen", andreas.identity().key_text, 1)
    for a in (andreas, sonia):
        _store(a, reg, [held])

    await cli.c_names(andreas, _a())
    out = _json(capsys)
    assert [n["name"] for n in out["names"]] == ["lorensen"] and out["shown"] == "lorensen"

    await cli.c_names(sonia, _a())                       # makes her inbox
    capsys.readouterr()
    await cli.c_name_give(andreas, _a(name="sonia@lorensen", key=sonia.identity().key_text, years=5))
    given = _json(capsys)
    assert given["delivered"] and given["key"] == sonia.identity().key_text

    await cli.c_names(sonia, _a())
    out = _json(capsys)
    assert [n["name"] for n in out["names"]] == ["sonia@lorensen"]

    await cli.c_names(andreas, _a())
    assert [g["name"] for g in _json(capsys)["given"]] == ["sonia@lorensen"]

    with pytest.raises(SystemExit):                      # not one of hers
        await cli.c_name_primary(sonia, _a(name="lorensen"))
    with pytest.raises(SystemExit):                      # she holds no parent
        await cli.c_name_give(sonia, _a(name="x@sonia", key=andreas.identity().key_text, years=1))
