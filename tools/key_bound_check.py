"""Completeness of key-bound state between two nodes (UN-RFC 0040 section 7).

Used by node_health.py. The checker holds no copy of the network: it has both
nodes describe the same ranges of the key space with XUN-RECONCILE and compares
the answers itself, splitting only where they differ. To have a node describe a
range, the checker sends it an F line with a fingerprint that cannot match; the
node then answers with its own items there (at most 64) or with the range in 16
parts as F lines (UN-RFC 0040 section 4.3).

What a node lacks is counted against one reference node, the listed node with
the most items. An item counts only if it was lacking in the previous day's
check too (at least 6 hours apart, section 7), so a node a little behind is not
called incomplete; node_health.py keeps the lacking keys between days.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from unseenet.core import reconcile as rc  # noqa: E402
from unseenet.nntp import NNTPError  # noqa: E402

NO_MATCH = "0" * 32            # a fingerprint no range has: makes a node describe it
PER_MESSAGE = 256              # ranges per message: answers stay under ~2 MB
MAX_PENDING = 2048             # differing ranges followed at once; beyond: "too many"
MAX_ROUNDS = 48                # per node and comparison, under the node's 64 for readers
KEEP_KEYS = 2000               # lacking keys kept for the next day's check


def allowance(reference_count: int) -> int:
    """0.1% of the reference node's items, or 100, whichever is more."""
    return max(reference_count // 1000, 100)


@dataclass
class Description:
    """How one node describes one range: its items, or the range in parts."""
    items: dict[bytes, str] | None = None                   # key -> Message-ID
    parts: list[rc.Range] = field(default_factory=list)     # F lines

    @property
    def count(self) -> int:
        return len(self.items) if self.items is not None else sum(p.count for p in self.parts)


class Side:
    """One node, asked to describe ranges; counts the rounds it used."""

    def __init__(self, client):
        self.client, self.rounds = client, 0

    async def describe(self, ranges: list[tuple[int, int]]) -> dict[tuple[int, int], Description]:
        out: dict[tuple[int, int], Description] = {}
        for i in range(0, len(ranges), PER_MESSAGE):
            chunk = ranges[i:i + PER_MESSAGE]
            self.rounds += 1
            if self.rounds > MAX_ROUNDS:
                raise rc.ReconcileError("too many rounds")
            lines = rc.format_message([rc.Range(lo, hi, "F", NO_MATCH, 0) for lo, hi in chunk])
            got = rc.parse_message(await self.client.reconcile(lines), answer=True)
            for lo, hi in chunk:
                inside = [r for r in got if lo <= r.lo and r.hi <= hi]
                if len(inside) == 1 and inside[0].kind == "L" and (inside[0].lo, inside[0].hi) == (lo, hi):
                    out[(lo, hi)] = Description(items=dict(inside[0].items))
                elif inside and all(r.kind == "F" for r in inside):
                    out[(lo, hi)] = Description(parts=inside)
                else:
                    raise rc.ReconcileError(f"unexpected answer for {rc.fmt_bound(lo)[:8]}")
        return out


@dataclass
class Comparison:
    reference_count: int = 0
    node_count: int = 0
    lacking: dict[str, str] = field(default_factory=dict)  # key hex -> reference's Message-ID
    at_least: int = 0          # when not followed to the end: lacking at least this many
    finished: bool = True
    error: str = ""

    @property
    def lacking_count(self) -> int:
        return len(self.lacking) if self.finished else max(len(self.lacking), self.at_least)


def _fp(items: dict[bytes, str], lo: int, hi: int) -> tuple[int, str]:
    """Count and fingerprint of known items within lo..hi."""
    hs = [rc.item_hash(k, rc.item_value(m)) for k, m in items.items()
          if lo <= int.from_bytes(k, "big") < hi]
    return len(hs), rc.fingerprint(len(hs), sum(hs))


async def compare(node, reference) -> Comparison:
    """What ``node`` lacks of ``reference``'s key-bound items. Both are connected
    Clients (``reconcile`` method)."""
    a, b = Side(node), Side(reference)
    result = Comparison()
    pending: dict[tuple[int, int], tuple[int, int]] = {(0, rc.FULL): (0, 0)}  # -> (ref, node) counts
    first = True
    try:
        while pending:
            if len(pending) > MAX_PENDING:
                raise rc.ReconcileError(f"differs in more than {MAX_PENDING} ranges")
            ranges = sorted(pending)
            mine, theirs = await a.describe(ranges), await b.describe(ranges)
            if first:
                result.node_count = mine[ranges[0]].count
                result.reference_count = theirs[ranges[0]].count
                first = False
            following: dict[tuple[int, int], tuple[int, int]] = {}
            for rng in ranges:
                following.update(_step(mine[rng], theirs[rng], result.lacking))
            pending = following
    except (rc.ReconcileError, NNTPError, ValueError) as exc:
        result.finished = False
        result.error = str(exc)
        # in what was left to follow, the reference has at least this many more
        result.at_least = len(result.lacking) + sum(max(0, r - n) for r, n in pending.values())
    return result


def _step(mine: Description, theirs: Description,
          lacking: dict[str, str]) -> dict[tuple[int, int], tuple[int, int]]:
    """Compare one range: note what the node lacks where both listed their items,
    and return the parts that differ, with (reference, node) counts there."""
    if theirs.count == 0:
        return {}                                       # nothing the node could lack here
    if mine.items is not None and theirs.items is not None:
        for k, m in theirs.items.items():
            if mine.items.get(k) != m:
                lacking[k.hex()] = m
        return {}
    follow = {}
    if mine.items is not None:                          # few here, the reference many
        for p in theirs.parts:
            count, fp = _fp(mine.items, p.lo, p.hi)
            if p.count and (count, fp) != (p.count, p.fp):
                follow[(p.lo, p.hi)] = (p.count, count)
    elif theirs.items is not None:                      # the reference few, the node many
        for p in mine.parts:
            count, fp = _fp(theirs.items, p.lo, p.hi)
            if count and (count, fp) != (p.count, p.fp):
                follow[(p.lo, p.hi)] = (count, p.count)
    else:
        for x, y in zip(mine.parts, theirs.parts):      # both split the range the same way
            if y.count and (x.count, x.fp) != (y.count, y.fp):
                follow[(x.lo, x.hi)] = (y.count, x.count)
    return follow


def verdict(ref_name: str, today: Comparison, yesterday: dict | None) -> str | None:
    """A problem for the day, or None. An item counts only if it was lacking in the
    previous check too (section 7); ``yesterday`` is that check's ``record``."""
    if today.reference_count == 0 or yesterday is None:
        return None                                    # once is not enough
    before = set(yesterday.get("lacking", []))
    if yesterday.get("over"):
        # yesterday lacked more than was kept: whatever lacks today lacked then too
        n, keys = today.lacking_count, set(today.lacking)
    else:
        keys = set(today.lacking) & before
        n = len(keys)
    limit = allowance(today.reference_count)
    if n <= limit:
        return None
    where = sorted({k[:2] for k in keys})[:8]
    return (f"lacks {n} of the {today.reference_count} key-bound groups of {ref_name} "
            f"in two checks running (allowed: {limit}"
            + (f"; keys starting {', '.join(where)}" if where else "") + ")")


def record(today: Comparison, reference: str, day: str) -> dict:
    """What to keep for tomorrow: the lacking keys (at most KEEP_KEYS)."""
    over = (not today.finished) or len(today.lacking) > KEEP_KEYS
    return {"date": day, "reference": reference, "over": over,
            "lacking": sorted(today.lacking)[:KEEP_KEYS]}
