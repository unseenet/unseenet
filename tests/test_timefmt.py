"""unseenet.client.timefmt.ago: the words every client uses for how long ago (tui#34)."""

from datetime import datetime, timedelta

from unseenet.client.timefmt import ago


def test_how_long_ago():
    now = datetime(2026, 10, 28, 14, 30).astimezone()
    assert ago(None, now) == ""
    assert ago(now - timedelta(seconds=20), now) == "now"
    assert ago(now - timedelta(minutes=5), now) == "5 min"
    assert ago(now - timedelta(seconds=50), now) == "1 min"
    assert ago(now - timedelta(hours=2), now) == "2 h"
    assert ago(now.replace(hour=20, minute=5) - timedelta(days=1), now) == "Yesterday 20:05"
    assert ago(now - timedelta(days=3), now) == "3 days"
    assert ago(now - timedelta(days=10), now) == "18 Oct"
    assert ago(now.replace(year=2025, month=3, day=2), now) == "2 Mar 2025"
