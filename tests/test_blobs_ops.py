"""#148 step 3d: what operators see and set for blobs (UN-RFC 0027 section 8)."""
import os
import time
from pathlib import Path

import pytest

from test_blobs import _manifest, _with_blobs
from unseenet.cli import load_node_config
from unseenet.core import blobs as bl
from unseenet.core import crypto
from unseenet.core.store import Store
from unseenet.monitor import blob_line
from unseenet.node.server import Node, NodeConfig

BITS = 8


def _toml(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "node.toml"
    p.write_text(text)
    return p


def test_blobs_are_off_unless_turned_on(tmp_path):
    assert load_node_config(_toml(tmp_path, "[node]\nname='x'\n")).blobs is None
    assert load_node_config(_toml(tmp_path, "[blobs]\nenabled=false\n")).blobs is None
    cfg = load_node_config(_toml(tmp_path, "[blobs]\nenabled=true\n")).blobs
    assert cfg["max_size"] == bl.MIN_NODE_BLOB and cfg["retention_days"] == 30
    assert cfg["encrypted"] is False and cfg["refusal_keys"] == []
    assert cfg["daily_per_key"] == bl.DAILY_PER_KEY and cfg["daily_per_group"] == bl.DAILY_PER_GROUP
    for bad in ("max_size = 100", "max_size = 5000000", "retention_days = 0",
                "refusal_keys = ['nonsense']", "daily_per_key = -1"):
        with pytest.raises(SystemExit):
            load_node_config(_toml(tmp_path, f"[blobs]\nenabled=true\n{bad}\n"))


def test_node_info_says_whether_and_how():
    off = Node(Store(), NodeConfig(min_pow=BITS))
    assert "blobs" not in off.node_info()["policy"]
    key = crypto.Identity.generate().key_text
    on = Node(Store(), NodeConfig(min_pow=BITS, blobs={"max_size": 2097152, "retention_days": 14,
                                                       "refusal_keys": [key]}))
    assert on.node_info()["policy"]["blobs"] == {
        "max_size": 2097152, "retention_days": 14, "encrypted": False, "refusal_lists": True,
        "daily_per_key": bl.DAILY_PER_KEY, "daily_per_group": bl.DAILY_PER_GROUP}


async def test_the_monitor_shows_files():
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), blobs={"max_size": 1048576}))
    owner = crypto.Identity.generate()
    node.accept(_manifest(owner, {"max_size": 1048576}).to_bytes())
    data = b"\x89PNG" + os.urandom(2000)
    node.accept(_with_blobs(owner, _manifest(owner).group, [data]).to_bytes(),
                staged={bl.blob_id(data): (data, time.monotonic())})
    snap = await node.stats.snapshot(node)
    b = snap["blobs"]
    assert b["count"] == 1 and b["bytes"] == len(data) and b["today"] == len(data) and b["refused"] == 0
    assert blob_line(b).startswith("Files  1 (")
    assert blob_line(None) == "Files  off (blobs not carried)"
    off = Node(Store(), NodeConfig(min_pow=BITS))
    assert (await off.stats.snapshot(off))["blobs"] is None
