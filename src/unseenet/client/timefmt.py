"""How long ago, as feeds say it - the same words in every client (unseenet-tui#34,
unseenet-gui#143): ``now``, ``5 min``, ``2 h``, ``Yesterday 14:20``, ``3 days``, then the
date, with the year when it is another year. Local time; the exact time belongs in a
tooltip or a message's head."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def ago(when: datetime | None, now: datetime | None = None) -> str:
    """``when`` as feeds show it, seen from ``now`` (default: this moment). Both are
    compared in local time; a naive datetime is taken as UTC."""
    if when is None:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    d, n = when.astimezone(), now.astimezone()
    s = (n - d).total_seconds()
    if s < 45:
        return "now"
    if s < 3600:
        return f"{max(1, round(s / 60))} min"
    if d.date() == n.date():
        return f"{round(s / 3600)} h"
    if d.date() == (n - timedelta(days=1)).date():
        return f"Yesterday {d:%H:%M}"
    days = int(s // 86400)
    if days < 7:
        return f"{max(2, days)} days"
    day = f"{d.day} {_MONTHS[d.month - 1]}"
    return day if d.year == n.year else f"{day} {d.year}"
