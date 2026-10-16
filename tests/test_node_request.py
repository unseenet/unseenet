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
