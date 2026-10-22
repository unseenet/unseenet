"""A random, growing wait before connecting again (UN-RFC 0043 section 4.4, #297).

When a node or a web entrance restarts, every client loses its connections at
the same moment. If they all came back after the same fixed pause, the node and
its Tor would get them all in the same few seconds; opening circuits is what
costs Tor CPU. A random first wait spreads them out, and doubling it keeps a
client from knocking on a node that is down.
"""

from __future__ import annotations

import random
import time

FIRST = (1.0, 30.0)          # seconds: the first wait, at random in this range
CAP = 300.0                  # never longer than five minutes
RESET_AFTER = 60.0           # a connection up this long starts the waits over


class Backoff:
    """``next()`` gives the wait before the next attempt: random in ``first`` the
    first time, then in twice that range, and so on, at most ``cap``. ``up()``
    when a connection opened; ``down()`` when it went away: if it had been up
    for ``reset_after`` seconds, the waits start over."""

    def __init__(self, first: tuple[float, float] = FIRST, cap: float = CAP,
                 reset_after: float = RESET_AFTER, rand=random.uniform, clock=time.monotonic):
        self.first, self.cap, self.reset_after = first, cap, reset_after
        self._rand, self._clock = rand, clock
        self.failures = 0
        self._up_since: float | None = None

    def next(self) -> float:
        lo, hi = self.first
        f = 2 ** self.failures
        self.failures += 1
        return min(self.cap, self._rand(lo * f, hi * f))

    def reset(self) -> None:
        self.failures = 0

    def up(self) -> None:
        self._up_since = self._clock()

    def down(self) -> None:
        if self._up_since is not None and self._clock() - self._up_since >= self.reset_after:
            self.reset()
        self._up_since = None
