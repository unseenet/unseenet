"""Shared test setup."""
import pytest

from unseenet.core import ripening


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
    """Keys' state files (core/poster.py) go to the test's own folder, never ~/.unseenet."""
    monkeypatch.setenv("UNSEENET_STATE_DIR", str(tmp_path / "keys"))


@pytest.fixture(autouse=True)
def fast_ripening():
    """Key ripening (UN-RFC 0025) for tests of other things: thresholds divided by
    2^16 (level 0 at 1024 iterations), and no surcharge, floor or requirement, so
    articles built by hand with little postage still go through. Clients still
    ripen and publish ripe@ before they post."""
    ripening.scale_for_tests(16, rules=False)
    yield
    ripening.scale_for_tests(0)


@pytest.fixture(autouse=True)
def no_pinned_key_list(monkeypatch):
    """Releases in tests are signed by test keys (``update.TRUSTED`` patched), so the
    project's pinned key list (UN-RFC 0062 section 5) is set aside; tests of key lists
    pin their own. ``test_the_project_key_list_is_pinned`` checks the real one."""
    from unseenet import release_keys
    monkeypatch.setattr(release_keys, "PROJECT_FIRST", None)


@pytest.fixture
def ripening_rules():
    """The real rules (surcharges, floor, nodes requiring level 0), fast thresholds."""
    ripening.scale_for_tests(16)
    yield


@pytest.fixture
def real_ripening():
    """The real thresholds and rules, for tests of the numbers themselves."""
    ripening.scale_for_tests(0)
    yield
