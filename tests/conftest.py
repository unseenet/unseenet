"""Shared test setup."""
import pytest

from unseenet.core import ripening


@pytest.fixture(autouse=True)
def fast_ripening():
    """Key ripening (UN-RFC 0025) for tests of other things: thresholds divided by
    2^16 (level 0 at 1024 iterations), and no surcharge, floor or requirement, so
    articles built by hand with little postage still go through. Clients still
    ripen and publish ripe@ before they post."""
    ripening.scale_for_tests(16, rules=False)
    yield
    ripening.scale_for_tests(0)


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
