"""The "Add my node" issue form: parsing and validation (no network)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("node_request", ROOT / "tools" / "node_request.py")
nr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nr)

ADDRESS = "a" * 56 + ".onion"
BODY = f"""### Node name

mynode

### Onion address

{ADDRESS}

### Node key

ed25519:gh7y6uk2fe2zlzvai5qriq7m6jsgk57aoi3jfkhookv7v4pd7hka

### Operator key (optional)

_No response_

### Description

Small node in Aarhus

### As the operator

- [X] I run this node
"""


def test_parse_and_validate():
    f = nr.parse_issue(BODY)
    assert f == {"name": "mynode", "address": ADDRESS,
                 "node_key": "ed25519:gh7y6uk2fe2zlzvai5qriq7m6jsgk57aoi3jfkhookv7v4pd7hka",
                 "operator": "", "description": "Small node in Aarhus"}
    assert nr.validate(f) == []
    bad = dict(f, address="example.com", node_key="nope", name="my node!")
    errors = " ".join(nr.validate(bad))
    assert "Onion address" in errors and "Node key" in errors and "Node name" in errors


def test_already_listed():
    from unseenet.known_nodes import KNOWN_NODES
    assert nr.listed(KNOWN_NODES[0].address) == KNOWN_NODES[0].name
    assert nr.listed(ADDRESS) is None


def test_ownership_challenge(tmp_path, monkeypatch, capsys):
    """Only a signature made on the node, over this issue's challenge, proves it."""
    from unseenet.cli import node_main
    from unseenet.core import crypto
    monkeypatch.setenv("UNSEENET_NODE_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    node_main(["--data", str(tmp_path), "--show-key"])
    node_key = capsys.readouterr().out.strip()

    challenge = nr.new_challenge("unseenet/unseenet", 7)
    bot = {"user": {"login": nr.BOT}, "body": "Check ...\n" + nr.how_to_prove(challenge)}
    assert nr.find_challenge([bot], "unseenet/unseenet", 7) == challenge
    assert nr.find_challenge([bot], "unseenet/unseenet", 8) is None             # another issue
    fake = {"user": {"login": "someone"}, "body": "unseenet-node-claim unseenet/unseenet#7 " + "0" * 32}
    assert nr.find_challenge([fake], "unseenet/unseenet", 7) is None             # only the bot's counts

    node_main(["--data", str(tmp_path), "--sign", challenge])
    sig = capsys.readouterr().out.strip()
    reply = {"user": {"login": "operator"}, "body": f"Here you go:\n\n{sig}\n"}
    assert nr.proven([bot, reply], challenge, node_key)
    assert not nr.proven([bot, reply], nr.new_challenge("unseenet/unseenet", 7), node_key)   # other challenge
    other = crypto.Identity.generate().key_text
    assert not nr.proven([bot, reply], challenge, other)                  # someone else's node


def test_sign_refuses_without_a_node_key(tmp_path):
    import pytest
    from unseenet.cli import node_main
    with pytest.raises(SystemExit):
        node_main(["--data", str(tmp_path / "nothing"), "--sign", "x"])


def test_health(tmp_path, monkeypatch):
    import json
    from datetime import date
    spec2 = importlib.util.spec_from_file_location("node_health", ROOT / "tools" / "node_health.py")
    nh = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(nh)
    nodes, health = tmp_path / "nodes.json", tmp_path / "health.json"
    a, b = "a" * 56 + ".onion", "b" * 56 + ".onion"
    nodes.write_text(json.dumps({"v": 1, "updated": "x", "nodes": [
        {"name": "na", "address": a}, {"name": "nb", "address": b}]}))
    health.write_text(json.dumps({"nodes": {b: {"issue": 12, "requested_by": "op"}}}))
    monkeypatch.setattr(nh, "NODES", nodes)
    monkeypatch.setattr(nh, "HEALTH", health)
    down = {a: [], b: ["Could not reach the node over Tor: gone"]}

    act = nh.update(down, date(2026, 10, 1))
    assert act["changed"] and not act["comments"]                     # first day: noted only
    assert json.loads(health.read_text())["nodes"][b]["first_failed"] == "2026-10-01"
    act = nh.update(down, date(2026, 10, 4))
    assert act["comments"] and "@op" in act["comments"][0]["body"] and act["comments"][0]["issue"] == 12
    assert not nh.update(down, date(2026, 10, 5))["comments"]        # warned once
    act = nh.update(down, date(2026, 10, 11))
    assert act["announce"] and "taken off" in act["comments"][0]["body"]
    assert [n["address"] for n in json.loads(nodes.read_text())["nodes"]] == [a]

    # every node failing is our problem, not theirs
    act = nh.update({a: ["x"]}, date(2026, 10, 12))
    assert not act["changed"] and "nothing counted" in act["summary"][0]
