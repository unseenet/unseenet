"""tools/project/project_peers.py: the project's nodes peer with each other."""

import importlib.util
import json
import tomllib
from pathlib import Path

import pytest

from unseenet.core import crypto
from unseenet.known_nodes import PROJECT_KEY

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("project_peers", ROOT / "tools" / "project" / "project_peers.py")
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)


def node(name, operator=PROJECT_KEY):
    return {"name": name, "address": name[-1] * 56 + ".onion",
            "node_key": crypto.Identity.generate().key_text, "operator": operator}


def test_mesh():
    nodes = [node("n-a"), node("n-b"), node("n-c"), node("other", operator="")]
    proj = pp.project_nodes(json.dumps({"v": 1, "nodes": nodes}))
    assert [n.name for n in proj] == ["n-a", "n-b", "n-c"]
    want = pp.needed("n-a", proj)
    assert [n.name for n in want] == ["n-b", "n-c"]
    config = "".join(pp.peer_section(n) for n in want)
    peers = tomllib.loads(config)["peer"]
    assert peers[0]["address"].endswith(".onion:119") and peers[0]["accept"] == "*"

    have = pp.peer_section(want[0]) + '[[peer]]\nname = "friend"\naddress = "x:1"\nkey = "%s"\n' % (
        crypto.Identity.generate().key_text)
    lacking, others = pp.missing(want, have)
    assert [n.name for n in lacking] == ["n-c"] and others == ["friend"]
    assert pp.missing(want, config) == ([], [])
    with pytest.raises(SystemExit):
        pp.needed("other", proj)


def test_the_real_list_is_a_mesh():
    proj = pp.project_nodes((ROOT / "src" / "unseenet" / "nodes.json").read_text())
    assert {"unseenet-node1", "unseenet-node2"} <= {n.name for n in proj}
