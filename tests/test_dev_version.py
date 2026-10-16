"""Versions of development builds sort between the releases around them."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import dev_version as dv  # noqa: E402


def test_dev_versions():
    assert dv.dev_version("v0.2.0", 0) == "0.2.0"
    assert dv.dev_version("v0.2.0", 3) == "0.2.1.dev3"
    assert dv.dev_version("v0.2.1a1", 2) == "0.2.1a2.dev2"
    assert dv.dev_version("v1.0.0rc1", 0) == "1.0.0rc1"
    with pytest.raises(ValueError):
        dv.dev_version("dev", 1)


def test_dev_versions_sort_like_pip():
    packaging = pytest.importorskip("packaging.version")
    V = packaging.Version
    order = ["0.2.0", dv.dev_version("v0.2.0", 3), "0.2.1a1",
             dv.dev_version("v0.2.1a1", 2), "0.2.1a2", "0.2.1"]
    assert [V(v) for v in order] == sorted(V(v) for v in order)
