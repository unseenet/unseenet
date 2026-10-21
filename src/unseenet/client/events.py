"""What a session reports, as typed events (unseenet #139).

A client gets them with ``Session.on(callback)``. ``Status`` is the old
one-line callback; the others say *what* happened, so a graphical client can
redraw just that: a group, the group list, a progress bar, a dot for a node.
Every event has ``to_dict()`` with its name in ``"event"``, for a local API.

Callbacks run on the session's event loop, also for postage progress, which
is computed in a worker thread.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Event:
    name = "event"

    def to_dict(self) -> dict:
        return {"event": self.name, **asdict(self)}


@dataclass(frozen=True)
class Status(Event):
    """A line for the status bar, as the old ``status`` callback had."""
    text: str
    name = "status"


@dataclass(frozen=True)
class GroupUpdated(Event):
    """New posts were fetched into a group's cache: redraw it, update its counts."""
    group_id: str
    new: int = 0
    name = "group-updated"


@dataclass(frozen=True)
class GroupsChanged(Event):
    """You followed, left or removed a group: redraw the group list."""
    name = "groups-changed"


@dataclass(frozen=True)
class PowProgress(Event):
    """Postage being computed (UN-RFC 0006). ``expected`` is the average number of
    attempts for the bits asked for; the real number varies a lot, so draw
    ``fraction`` rather than attempts / expected."""
    attempts: int
    expected: int
    done: bool = False
    name = "pow-progress"

    @property
    def fraction(self) -> float:
        """The chance it would be done by now: 1 when done, never 1 before."""
        if self.done:
            return 1.0
        return min(0.99, 1 - math.exp(-self.attempts / max(1, self.expected)))

    def to_dict(self) -> dict:
        return {**super().to_dict(), "fraction": self.fraction}


@dataclass(frozen=True)
class NodeState(Event):
    """A connection to a node opened (``up``) or failed."""
    address: str
    up: bool
    error: str | None = None
    name = "node-state"


@dataclass(frozen=True)
class TorState(Event):
    """Tor starting: bootstrap progress 0-100, for the unlock screen."""
    progress: int
    summary: str = ""
    name = "tor-state"
