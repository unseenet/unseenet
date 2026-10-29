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


def test_main_counts_on_from_a_fix_released_on_a_release_branch():
    """v0.6.1 is tagged on release/0.6, so main's describe still names v0.6.0: its
    development builds must be 0.6.2.devN, not 0.6.1.devN, which sorts below 0.6.1 and
    broke the nightly builds of clients that need 0.6.1 (29 Oct 2026)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import dev_version as d
    assert d.newest_of_series("v0.6.0", ["v0.5.9", "v0.6.0", "v0.6.1", "v0.7.0"]) == "v0.6.1"
    assert d.newest_of_series("v0.6.0", ["v0.6.1rc1"]) == "v0.6.0"       # not a test release
    assert d.newest_of_series("v0.6.1a1", ["v0.6.1"]) == "v0.6.1a1"     # after an alpha: as before
    assert d.dev_version(d.newest_of_series("v0.6.0", ["v0.6.1"]), 3) == "0.6.2.dev3"
