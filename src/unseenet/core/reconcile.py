"""Range-based set reconciliation of key-bound state (UN-RFC 0040 section 4).

Two nodes compare the key-bound manifests they hold without listing them: they
exchange fingerprints of ranges of the key space and split only the ranges that
differ, until those are small enough to list. The cost follows the number of
differences, not the number of items.

An *item* is (key, value): key = SHA-256(Group ID), value = SHA-256(Message-ID
of the current manifest), the Message-ID as written, angle brackets included.
Keys are ordered as unsigned 256-bit numbers; a range is lower <= key < upper,
with FULL standing for the written upper bound ``end``.

This module is the protocol only. The node answers with :func:`answer` over its
store (``Store.kb_count_sum`` and ``Store.kb_items``); a node or a checker drives
an exchange with :func:`reconcile`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

FULL = 1 << 256                 # the upper bound written "end"
MOD = 1 << 256
SPLIT = 16                      # a differing range is split into this many parts
LIST_MAX = 64                   # at most this many items: list them instead
MAX_RANGES = 4096               # range lines per message
MAX_ROUNDS = 64                 # rounds per exchange
MAX_LISTED = MAX_RANGES * LIST_MAX   # item lines per message


class ReconcileError(ValueError):
    """A malformed or oversized message."""


# ---------------------------------------------------------------------------
# items and fingerprints (section 4.2)
# ---------------------------------------------------------------------------
def item_key(group_id: str) -> bytes:
    return hashlib.sha256(group_id.encode("utf-8")).digest()


def item_value(message_id: str) -> bytes:
    return hashlib.sha256(message_id.encode("utf-8")).digest()


def item_hash(key: bytes, value: bytes) -> int:
    """SHA-256(key || value) as an unsigned 256-bit number: what a range sums."""
    return int.from_bytes(hashlib.sha256(key + value).digest(), "big")


def fingerprint(count: int, total: int) -> str:
    """First 16 octets of SHA-256(count as u64 BE || sum mod 2^256 as 32 octets BE)."""
    data = count.to_bytes(8, "big") + (total % MOD).to_bytes(32, "big")
    return hashlib.sha256(data).digest()[:16].hex()


def fmt_bound(n: int) -> str:
    return "end" if n == FULL else f"{n:064x}"


def parse_bound(s: str) -> int:
    if s == "end":
        return FULL
    if len(s) != 64 or s != s.lower():
        raise ReconcileError(f"bad bound {s[:70]!r}")
    try:
        return int(s, 16)
    except ValueError:
        raise ReconcileError(f"bad bound {s[:70]!r}") from None


def split(lo: int, hi: int) -> list[tuple[int, int]]:
    """``lo``..``hi`` in SPLIT equal parts by key (fewer if the range is narrower)."""
    bounds = sorted({lo + (hi - lo) * i // SPLIT for i in range(SPLIT)} | {hi})
    return list(zip(bounds, bounds[1:]))


# ---------------------------------------------------------------------------
# messages (section 4.3)
# ---------------------------------------------------------------------------
@dataclass
class Range:
    lo: int
    hi: int
    kind: str                                   # "F", "L" or "="
    fp: str = ""
    count: int = 0
    items: list[tuple[bytes, str]] = field(default_factory=list)   # (key, Message-ID)


def format_message(ranges: list[Range]) -> list[str]:
    out = []
    for r in ranges:
        head = f"{fmt_bound(r.lo)} {fmt_bound(r.hi)}"
        if r.kind == "F":
            out.append(f"{head} F {r.fp} {r.count}")
        elif r.kind == "L":
            out.append(f"{head} L {len(r.items)}")
            out += [f"{k.hex()} {m}" for k, m in r.items]
        else:
            out.append(f"{head} =")
    return out


def parse_message(lines: list[str], answer: bool = False) -> list[Range]:
    """Range lines, checked: ascending, not overlapping, within the limits.
    ``=`` lines are allowed only in an answer."""
    out: list[Range] = []
    listed = 0
    it = iter(lines)
    for line in it:
        parts = line.split()
        if len(parts) < 3:
            raise ReconcileError(f"bad range line {line[:80]!r}")
        lo, hi, kind = parse_bound(parts[0]), parse_bound(parts[1]), parts[2]
        if lo >= hi:
            raise ReconcileError("empty range")
        if out and lo < out[-1].hi:
            raise ReconcileError("ranges not ascending or overlapping")
        if kind == "F" and len(parts) == 5:
            fp, count = parts[3], parts[4]
            if len(fp) != 32 or not count.isdigit():
                raise ReconcileError(f"bad F line {line[:80]!r}")
            int(fp, 16)
            out.append(Range(lo, hi, "F", fp.lower(), int(count)))
        elif kind == "L" and len(parts) == 4 and parts[3].isdigit():
            n = int(parts[3])
            listed += n
            if listed > MAX_LISTED:
                raise ReconcileError("too many items")
            r = Range(lo, hi, "L")
            for _ in range(n):
                item = next(it, None)
                if item is None:
                    raise ReconcileError("fewer items than announced")
                k, _, msgid = item.partition(" ")
                if len(k) != 64 or not msgid.startswith("<"):
                    raise ReconcileError(f"bad item {item[:80]!r}")
                key = bytes.fromhex(k)
                if not lo <= int.from_bytes(key, "big") < hi:
                    raise ReconcileError("item outside its range")
                r.items.append((key, msgid.strip()))
            out.append(r)
        elif kind == "=" and len(parts) == 3 and answer:
            out.append(Range(lo, hi, "="))
        else:
            raise ReconcileError(f"bad range line {line[:80]!r}")
        if len(out) > MAX_RANGES:
            raise ReconcileError(f"more than {MAX_RANGES} ranges")
    return out


# ---------------------------------------------------------------------------
# one side's state
# ---------------------------------------------------------------------------
class Source(Protocol):
    def kb_count_sum(self, lo: int, hi: int) -> tuple[int, int]: ...
    def kb_items(self, lo: int, hi: int) -> list[tuple[bytes, str]]: ...


class MemorySource:
    """Items held in memory: for tests and for checkers that keep no store."""

    def __init__(self, items: dict[str, str] | None = None):
        self.items: dict[bytes, tuple[str, int]] = {}
        for gid, msgid in (items or {}).items():
            self.put(gid, msgid)

    def put(self, group_id: str, message_id: str) -> None:
        key = item_key(group_id)
        self.items[key] = (message_id, item_hash(key, item_value(message_id)))

    def kb_count_sum(self, lo, hi):
        hs = [h for k, (_, h) in self.items.items() if lo <= int.from_bytes(k, "big") < hi]
        return len(hs), sum(hs) % MOD

    def kb_items(self, lo, hi):
        return sorted((k, m) for k, (m, _) in self.items.items()
                      if lo <= int.from_bytes(k, "big") < hi)


def describe(source: Source, lo: int, hi: int) -> Range:
    """Our F line for a range."""
    count, total = source.kb_count_sum(lo, hi)
    return Range(lo, hi, "F", fingerprint(count, total), count)


def _split_or_list(source: Source, lo: int, hi: int) -> list[Range]:
    """The node's rule for a range that differs: list at most LIST_MAX items,
    otherwise SPLIT parts as F lines."""
    count, _ = source.kb_count_sum(lo, hi)
    if count <= LIST_MAX:
        return [Range(lo, hi, "L", items=source.kb_items(lo, hi))]
    return [describe(source, a, b) for a, b in split(lo, hi)]


def answer(source: Source, ranges: list[Range]) -> list[Range]:
    """The node's answer to one message (section 4.3)."""
    out: list[Range] = []
    for r in ranges:
        if r.kind == "L":
            out.append(Range(r.lo, r.hi, "L", items=source.kb_items(r.lo, r.hi)))
            continue
        count, total = source.kb_count_sum(r.lo, r.hi)
        if count == r.count and fingerprint(count, total) == r.fp:
            out.append(Range(r.lo, r.hi, "="))
        else:
            out += _split_or_list(source, r.lo, r.hi)
    return out


# ---------------------------------------------------------------------------
# driving an exchange
# ---------------------------------------------------------------------------
CLIENT_LIST_MAX = 1024          # we list our items only where the peer has at most this many
ANSWER_BUDGET = 16384           # items a message of ours may ask the peer to list back


@dataclass
class Result:
    need: list[str] = field(default_factory=list)      # Message-IDs to fetch from the peer
    offer: list[str] = field(default_factory=list)     # Message-IDs the peer lacks or differs on
    rounds: int = 0
    their_count: int | None = None                     # the peer's items in lo..hi
    complete: bool = True                              # False: stopped at max_rounds
    same: bool = False                                 # complete, and nothing differs


def _compare(result: Result, ours: list[tuple[bytes, str]], theirs: list[tuple[bytes, str]]):
    mine, other = dict(ours), dict(theirs)
    result.need += [m for k, m in theirs if mine.get(k) != m]
    result.offer += [m for k, m in ours if other.get(k) != m]


def _next(source: Source, r: Range) -> list[Range]:
    """What we send for a range the peer answered with an F line that differs.

    The rule of section 4.3, with one restraint: we list our items only where the
    peer, too, has few, since it answers an L line with all of its own. A node far
    behind therefore splits further rather than asking for a big list."""
    mine, _ = source.kb_count_sum(r.lo, r.hi)
    if mine <= LIST_MAX and r.count <= CLIENT_LIST_MAX:
        return [Range(r.lo, r.hi, "L", items=source.kb_items(r.lo, r.hi))]
    return [describe(source, a, b) for a, b in split(r.lo, r.hi)]


def _batches(pending: list[Range], their: dict[tuple[int, int], int]) -> list[list[Range]]:
    """Messages of at most MAX_RANGES ranges, each asking for at most ANSWER_BUDGET
    listed items back (what an L line costs is the peer's count there)."""
    out: list[list[Range]] = []
    cur: list[Range] = []
    budget = 0
    for r in pending:
        cost = their.get((r.lo, r.hi), LIST_MAX) if r.kind == "L" else LIST_MAX
        if cur and (len(cur) >= MAX_RANGES or budget + cost > ANSWER_BUDGET):
            out.append(cur)
            cur, budget = [], 0
        cur.append(r)
        budget += cost
    if cur:
        out.append(cur)
    return out


async def reconcile(send, source: Source, lo: int = 0, hi: int = FULL,
                    max_rounds: int = MAX_ROUNDS) -> Result:
    """Reconcile ``lo``..``hi`` with a peer.

    ``send`` is an async callable that takes a list of range lines and returns
    the peer's answer lines: one ``XUN-RECONCILE`` round, such as
    ``unseenet.nntp.Client.reconcile``. Returns what to fetch and what to offer;
    nothing is fetched or accepted here. A node far behind may need more than
    ``max_rounds``: then the result holds what was found so far, ``complete`` is
    False, and a later exchange (with the fetched items in place) goes further.
    """
    result = Result()
    pending = [describe(source, lo, hi)]
    their: dict[tuple[int, int], int] = {}
    first = True
    while pending:
        batches = _batches(pending, their)
        pending = []
        for sent in batches:
            if result.rounds >= max_rounds:
                result.complete = False
                break
            result.rounds += 1
            got = parse_message(await send(format_message(sent)), answer=True)
            if first:
                # the first answer covers lo..hi: its counts are the peer's whole state
                first = False
                result.their_count = (sent[0].count if len(got) == 1 and got[0].kind == "="
                                      else sum(r.count if r.kind == "F" else len(r.items)
                                               for r in got))
            for r in got:
                if r.kind == "L":
                    _compare(result, source.kb_items(r.lo, r.hi), r.items)
                elif r.kind == "F":
                    mine_count, mine_total = source.kb_count_sum(r.lo, r.hi)
                    if mine_count != r.count or fingerprint(mine_count, mine_total) != r.fp:
                        their[(r.lo, r.hi)] = r.count
                        pending += _next(source, r)
        if not result.complete:
            break
        pending.sort(key=lambda r: r.lo)
    result.same = result.complete and not result.need and not result.offer
    return result
