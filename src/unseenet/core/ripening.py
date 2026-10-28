"""Key ripening (UN-RFC 0025): a VDF over a key's own public key, in segments.

A key ripens by a Wesolowski VDF over class groups, computed in segments so
the work survives a restart (section 3.2). The chain of segments is
published in the manifest of ``ripe@<fp>`` (3.3); articles carry the
``Key-Ripening`` header naming one point on it (3.4). The level of that
point lowers or raises the postage the key pays (sections 4, 5).

``chiavdf`` does the arithmetic. It is imported when first needed, so the
rest of Unseenet works where it is missing; ``available()`` says whether
this machine can ripen and verify.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .encoding import DS, H, b64, b64decode

ALG = "vdf-cg1"
DISC_BITS = 1024
FORM_SIZE = 100                                   # compressed form, octets
GENERATOR = bytes([0x08]) + bytes(FORM_SIZE - 1)  # the form (2, 1, c), as chiavdf encodes it
MAX_SEGMENTS = 64                                 # section 3.3
FIRST_SEGMENT = 1 << 24                           # section 3.2: until level 0
MAX_SEGMENT = 1 << 32
GROUP_NAME = "ripe"                               # ripe@<fp>, a key-bound group (UN-RFC 0029)

# level: iterations at least, postage surcharge in bits (section 4)
LEVELS = ((0, 1 << 26, 6), (1, 1 << 29, 4), (2, 1 << 32, 2), (3, 1 << 35, 0), (4, 1 << 37, -2))
TOP = LEVELS[-1][1]
_REAL_LEVELS = LEVELS
FLOOR_POW = _REAL_FLOOR = 12                      # section 5
DEFAULT_MIN_RIPE: int | None = 0                  # a node's UNSEENET-MINRIPE unless configured

_HEADER_RE = re.compile(r"^vdf-cg1;\s*t=(\d+);\s*y=([A-Za-z0-9_-]+)$")


class RipeningError(ValueError):
    """A chain or header that is not valid."""


class RipeningUnavailable(RuntimeError):
    """chiavdf is not installed here (UN-RFC 0025 section 10)."""


def _vdf():
    try:
        import chiavdf
    except ImportError as exc:      # pragma: no cover - depends on the platform
        why = "" if isinstance(exc, ModuleNotFoundError) else f": {exc}"   # e.g. a DLL missing
        raise RipeningUnavailable(f"key ripening needs chiavdf (pip install chiavdf){why}") from exc
    return chiavdf


def available() -> bool:
    try:
        _vdf()
        return True
    except RipeningUnavailable:
        return False


def self_check() -> str | None:
    """Prove and check a very short segment with a throwaway key: None when key
    ripening works in this build, else what is wrong. For self-tests: a build
    without a working chiavdf can read, but cannot post on 0.4 nodes."""
    try:
        from . import crypto
        pk = crypto.Identity.generate().public_key
        seg = prove_segment(pk, GENERATOR, 1000)
        if seg is None or verify(pk, Chain([seg])) != 1:
            return "a short proof could not be made"
        return None
    except (RipeningUnavailable, RipeningError, RuntimeError, ValueError, OSError) as exc:
        return str(exc) or type(exc).__name__


def seed(public_key: bytes) -> bytes:
    """The challenge for a key: a proof belongs to this key only (section 3.1)."""
    return H(DS("UNSEENET-RIPEN-1") + public_key)


def discriminant(public_key: bytes) -> str:
    return _vdf().create_discriminant(seed(public_key), DISC_BITS)


# --- levels and postage (sections 4, 5) ---
def scale_for_tests(shift: int, rules: bool = True) -> None:
    """For tests only: divide every threshold by 2^shift, so keys ripen in
    milliseconds. Without ``rules``, ripening costs and requires nothing (no
    surcharge, no floor, nodes default to "-"), for tests of other things."""
    global LEVELS, TOP, FIRST_SEGMENT, FLOOR_POW, DEFAULT_MIN_RIPE
    LEVELS = tuple((lv, max(1, th >> shift), s if rules else 0) for lv, th, s in _REAL_LEVELS)
    TOP = LEVELS[-1][1]
    FIRST_SEGMENT = max(1, (1 << 24) >> shift)
    FLOOR_POW = _REAL_FLOOR if rules else 0
    DEFAULT_MIN_RIPE = 0 if rules else None


def level(t: int) -> int | None:
    """The level of *t* iterations; None is level "-" (below level 0)."""
    found = None
    for lv, threshold, _ in LEVELS:
        if t >= threshold:
            found = lv
    return found


def surcharge(lv: int | None) -> int | None:
    """Extra postage bits for a level; None when the level is not accepted at all."""
    if lv is None:
        return None
    return next(s for v, _, s in LEVELS if v == lv)


def next_threshold(t: int) -> int | None:
    """Iterations at which the next level starts, None at the top."""
    return next((th for _, th, _ in LEVELS if th > t), None)


def meets(lv: int | None, minimum: int | None) -> bool:
    """Does a key at level ``lv`` meet a minimum (None is "-": everything)?"""
    if minimum is None:
        return True
    return lv is not None and lv >= minimum


def required_pow(node_min_pow: int, group_min_pow: int, lv: int | None,
                 allow_unripe: bool = False) -> int | None:
    """The postage a key at level ``lv`` pays (section 5); None if not accepted.

    ``allow_unripe`` is a minimum level of "-" (a closed group, section 5):
    an unripe key then pays the level 0 surcharge."""
    s = surcharge(lv)
    if s is None:
        if not allow_unripe:
            return None
        s = surcharge(0)
    return max(FLOOR_POW, max(node_min_pow, group_min_pow) + s)


def parse_min(value) -> int | None:
    """A ``min_ripe`` / ``UNSEENET-MINRIPE`` value: an integer level or "-" (None)."""
    if value in ("-", None):
        return None if value == "-" else 0
    lv = int(value)
    if not 0 <= lv <= LEVELS[-1][0]:
        raise RipeningError(f"no ripening level {value!r}")
    return lv


# --- segments (section 3.2) ---
# chiavdf's ``prove_low_memory`` (1.2.1, #444) proves a segment in nearly constant
# memory, at about twice the time. Its older ``prove`` keeps intermediate forms for
# the Wesolowski proof, about 0.7 octets an iteration (#440): still the model where
# only that one exists - an older chiavdf, or a browser build without it.
MEMORY_PER_ITERATION = 0.75
MEMORY_BASE = 64 << 20
MIN_SEGMENT = 1 << 20


def low_memory() -> bool:
    """True when this machine's chiavdf proves in constant memory (#444)."""
    try:
        return hasattr(_vdf(), "prove_low_memory")
    except RipeningUnavailable:
        return False


def memory_for(length: int, low: bool | None = None) -> int:
    """About how many octets proving a segment of ``length`` iterations takes:
    ``MEMORY_BASE`` with the low-memory prover (``low`` None: whichever this machine
    has), else growing with the length."""
    if low is None:
        low = low_memory()
    return MEMORY_BASE if low else int(MEMORY_BASE + MEMORY_PER_ITERATION * length)


def fitting_segment_length(t: int, segments: int, budget: int | None,
                           low: bool | None = None) -> int:
    """The next segment's length on a machine with ``budget`` octets for ripening
    (section 3.2): the usual length when it fits, else the longest power of two that
    does - as long as the next level can still be reached within the 64 segments.
    0 when it cannot: at the top, or as far as this machine can go. ``segments`` is
    how many the chain has; ``budget`` None means no limit. With the low-memory
    prover (``low``, see ``memory_for``) every length fits that fits at all."""
    if low is None:
        low = low_memory()
    length = next_segment_length(t)
    if not length or budget is None or memory_for(length, low) <= budget:
        return length
    if low:
        return 0                     # not even the constant part fits
    cap = 1 << max(0, int((budget - MEMORY_BASE) / MEMORY_PER_ITERATION)).bit_length() - 1 \
        if budget > MEMORY_BASE else 0
    if cap < MIN_SEGMENT:
        return 0
    nxt = next_threshold(t)
    if nxt is not None and (MAX_SEGMENTS - segments) * cap < nxt - t:
        return 0                     # the next level is out of this machine's reach
    return min(cap, length)


def reachable_level(t: int, segments: int, budget: int | None,
                    low: bool | None = None) -> int | None:
    """The highest level a chain can reach on this machine, going on from here."""
    if low is None:
        low = low_memory()
    while True:
        length = fitting_segment_length(t, segments, budget, low)
        if not length or segments >= MAX_SEGMENTS:
            return level(t)
        t, segments = t + length, segments + 1


def next_segment_length(t: int) -> int:
    """How long the next segment should be after *t* iterations: 2^24 until level
    0, then half the work so far (a power of two), at most 2^32, never past the
    next level. 0 at the top: nothing more to gain."""
    nxt = next_threshold(t)
    if nxt is None:
        return 0
    if t < LEVELS[0][1]:
        length = FIRST_SEGMENT
    else:
        length = min(1 << ((t // 2).bit_length() - 1), MAX_SEGMENT)
    return min(length, nxt - t)


@dataclass(frozen=True)
class Segment:
    t: int          # iterations in this segment
    y: bytes        # its end form
    pi: bytes       # the Wesolowski proof

    def to_dict(self) -> dict:
        return {"t": self.t, "y": b64(self.y), "pi": b64(self.pi)}

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        try:
            seg = cls(int(d["t"]), b64decode(d["y"]), b64decode(d["pi"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RipeningError(f"bad segment: {exc}") from exc
        if seg.t <= 0 or len(seg.y) != FORM_SIZE or len(seg.pi) != FORM_SIZE:
            raise RipeningError("bad segment: wrong size")
        return seg


@dataclass
class Chain:
    """A key's segments, the first from the generator (section 3.2)."""
    segments: list[Segment] = field(default_factory=list)

    @property
    def t(self) -> int:
        return sum(s.t for s in self.segments)

    @property
    def level(self) -> int | None:
        return level(self.t)

    @property
    def end(self) -> bytes:
        """Where the next segment starts."""
        return self.segments[-1].y if self.segments else GENERATOR

    def points(self) -> dict[int, bytes]:
        """Every segment end, as (t so far, y): what a header may name."""
        out, t = {}, 0
        for s in self.segments:
            t += s.t
            out[t] = s.y
        return out

    def extends(self, other: "Chain") -> bool:
        """Does this chain keep ``other`` as its beginning (section 3.3)?"""
        return self.segments[:len(other.segments)] == other.segments

    def header(self) -> str:
        """The ``Key-Ripening`` value for the end of this chain (section 3.4)."""
        if not self.segments:
            raise RipeningError("an empty chain names no point")
        return format_header(self.t, self.end)

    def to_manifest(self) -> dict:
        """The ``ripening`` object of the ``ripe@`` manifest (section 3.3)."""
        return {"alg": ALG, "segments": [s.to_dict() for s in self.segments]}

    @classmethod
    def from_manifest(cls, obj) -> "Chain":
        if not isinstance(obj, dict) or obj.get("alg") != ALG:
            raise RipeningError("not a vdf-cg1 ripening object")
        segs = obj.get("segments")
        if not isinstance(segs, list) or not segs:
            raise RipeningError("no segments")
        if len(segs) > MAX_SEGMENTS:
            raise RipeningError(f"more than {MAX_SEGMENTS} segments")
        return cls([Segment.from_dict(s) for s in segs])


def format_header(t: int, y: bytes) -> str:
    return f"{ALG}; t={t}; y={b64(y)}"


def parse_header(value: str) -> tuple[int, bytes]:
    """(t, y) from a ``Key-Ripening`` header."""
    m = _HEADER_RE.match(value.strip())
    if not m:
        raise RipeningError("malformed Key-Ripening header")
    y = b64decode(m.group(2))
    if len(y) != FORM_SIZE:
        raise RipeningError("Key-Ripening: wrong form size")
    return int(m.group(1)), y


# --- proving and verifying ---
def prove_segment(public_key: bytes, start: bytes, t: int,
                  run_file=None) -> Segment | None:
    """Compute one segment of ``t`` iterations from ``start`` (slow: t / ~100,000 s).

    With ``run_file`` (a path that exists), the computation runs only while that
    file exists: delete it to stop within a fraction of a second, e.g. when the
    client closes. A stopped segment returns None and is started again later
    from ``start`` (section 3.2). Without it, the call cannot be interrupted.

    Uses chiavdf's low-memory prover where it has one (#444): the same bytes as
    ``prove``, in constant memory, at about twice the time."""
    vdf = _vdf()
    prove = getattr(vdf, "prove_low_memory", None) or vdf.prove
    result = prove(seed(public_key), start, DISC_BITS, t, str(run_file or ""))
    if not result:
        return None
    return Segment(t, bytes(result[:FORM_SIZE]), bytes(result[FORM_SIZE:]))


def verify(public_key: bytes, chain: Chain, already: int = 0) -> int:
    """Check every segment from number ``already`` on (those before were checked
    earlier, section 3.4). Returns how many segments are now known good; raises
    RipeningError at the first bad one."""
    vdf = _vdf()
    disc = discriminant(public_key)
    x = chain.segments[already - 1].y if already else GENERATOR
    for i in range(already, len(chain.segments)):
        s = chain.segments[i]
        try:
            ok = vdf.verify_wesolowski(disc, x, s.y, s.pi, s.t)
        except (RuntimeError, ValueError):     # a form that is not of this key's group
            ok = False
        if not ok:
            raise RipeningError(f"segment {i + 1} does not verify")
        x = s.y
    return len(chain.segments)
