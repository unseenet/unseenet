"""A publisher's key list: who signs its releases, and how many must (UN-RFC 0062 3-4).

A release is valid when a threshold of the publisher's keys signed its
``SHA256SUMS.txt`` - two of three for the project, so that one stolen key sends nothing
and one lost key stops nothing. The keys are a chain of key lists in the publisher's
releases channel (``Subject: release-keys <seq>``): the first is pinned in the client,
each later one counts when the threshold of the keys before it each posted it - the
old keys vote the new ones in. Two counting lists with one ``seq`` are a fork: no
update from that publisher until the user acts.

Belongs here: the list's body, counting the chain, the votes read from a channel, and
which list to go by. Not here: checking a release's signatures against it
(``update.check_signature``), making and posting lists (``tools/project/release_keys.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .core import crypto
from .core.encoding import DS, H, b64
from .core.groups import canonical_json, parse_canonical_json
from .known_nodes import PROJECT_KEY

DOMAIN = "UNSEENET-RELEASE-KEYS-1"
SUBJECT = "release-keys"
MAX_KEYS = 8
_SUBJECT = re.compile(r"^release-keys ([1-9][0-9]{0,8})$")

# The project's first key list (section 5): the project key and two reserve keys,
# threshold 2, {"dev": 1}. Pinned here once the maintainer made the reserve keys
# (tools/project/release_keys.py make); until then releases are checked as before -
# the project key alone, and the development keys for development builds.
PROJECT_FIRST: str | None = None


class KeyListProblem(ValueError):
    pass


@dataclass(frozen=True)
class KeyList:
    seq: int
    keys: tuple[str, ...]
    threshold: int
    channels: dict = field(default_factory=dict, compare=False)
    prev: str | None = None
    body: str = ""

    def threshold_for(self, channel: str) -> int:
        return int(self.channels.get(channel, self.threshold))

    @property
    def hash(self) -> str:
        return list_hash(self.body)


def list_hash(body: str) -> str:
    """``H(DS("UNSEENET-RELEASE-KEYS-1") || body)``, as a later list's ``prev``."""
    return b64(H(DS(DOMAIN) + body.rstrip("\n").encode("utf-8")))


def make_body(seq: int, keys: list[str], threshold: int, channels: dict | None = None,
              prev: KeyList | None = None) -> str:
    """The canonical body of a key list. ``prev``: the list it follows (from ``seq`` 2)."""
    d: dict = {"v": 1, "seq": seq, "keys": list(dict.fromkeys(keys)), "threshold": threshold}
    if channels:
        d["channels"] = dict(sorted(channels.items()))
    if prev is not None:
        d["prev"] = prev.hash
    body = canonical_json(d) + "\n"
    parse(body)                                   # never make one that would not parse
    return body


def parse(body: str) -> KeyList:
    try:
        d = parse_canonical_json(body.rstrip("\n"))
    except Exception as exc:  # noqa: BLE001
        raise KeyListProblem("not canonical JSON") from exc
    if not isinstance(d, dict) or d.get("v") != 1:
        raise KeyListProblem("not a version 1 key list")
    seq, keys, threshold = d.get("seq"), d.get("keys"), d.get("threshold")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise KeyListProblem("seq is a number from 1")
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_KEYS or len(set(keys)) != len(keys):
        raise KeyListProblem(f"keys are 1 to {MAX_KEYS} different keys")
    for k in keys:
        try:
            crypto.key_from_text(k)
        except Exception as exc:  # noqa: BLE001
            raise KeyListProblem(f"not a key: {k!r}") from exc

    def count_ok(n) -> bool:
        return isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(keys)
    if not count_ok(threshold):
        raise KeyListProblem("threshold is 1 to the number of keys")
    channels = d.get("channels", {})
    if not isinstance(channels, dict) or not all(
            isinstance(c, str) and re.match(r"^[a-z][a-z0-9-]{0,15}$", c) and count_ok(n)
            for c, n in channels.items()):
        raise KeyListProblem("channels map channel names to thresholds")
    prev = d.get("prev")
    if (seq == 1) != (prev is None) or (prev is not None and not isinstance(prev, str)):
        raise KeyListProblem("prev is there from seq 2 on, and only then")
    return KeyList(seq, tuple(keys), threshold, dict(channels), prev,
                   body.rstrip("\n") + "\n")


def legacy() -> KeyList:
    """How releases were checked before key lists: the project key alone (seq 0, never
    followed by a list in the channel)."""
    return KeyList(0, (PROJECT_KEY,), 1, {}, None, "")


def first() -> KeyList:
    """The project's pinned first list, or the legacy one while there is none."""
    return parse(PROJECT_FIRST) if PROJECT_FIRST else legacy()


def count(start: KeyList, votes) -> tuple[KeyList, bool]:
    """The newest list that counts, from ``start`` (the pinned list, or one counted
    before), and whether there is a fork. ``votes``: (author key, body) of the
    ``release-keys`` articles in the channel, their signatures checked."""
    if start.seq == 0:                            # nothing pinned: nothing to follow
        return start, False
    by_body: dict[str, set[str]] = {}
    for author, body in votes:
        try:
            kl = parse(body)
        except KeyListProblem:
            continue
        by_body.setdefault(kl.body, set()).add(author)
    cur = start
    while True:
        nxt = []
        for body, authors in by_body.items():
            kl = parse(body)
            if (kl.seq == cur.seq + 1 and kl.prev == cur.hash
                    and len(authors & set(cur.keys)) >= cur.threshold):
                nxt.append(kl)
        if len(nxt) > 1:
            return cur, True
        if not nxt:
            return cur, False
        cur = nxt[0]


def votes_in(raws) -> list[tuple[str, str]]:
    """(author key, body) of the key-list articles among raw articles, each signature
    checked here: a node's word is not taken."""
    from .core.article import Article
    from .nntp import strip_reader_headers
    out = []
    for raw in raws:
        try:
            art = Article.from_bytes(strip_reader_headers(raw))
            art.verify_signature()
        except Exception:  # noqa: BLE001 - not a valid article: no vote
            continue
        if _SUBJECT.match(art.get("Subject", "") or ""):
            out.append((crypto.key_to_text(art.author_key), art.body))
    return out


@dataclass(frozen=True)
class Vote:
    """A key-list article read from a channel, its signature checked: carried among
    the bodies of release posts (``update.from_network``, ``service_update``)."""
    author: str
    body: str


async def read_votes(c, group: str, scan: int = 400, limit: int = 50) -> list[Vote]:
    """The key-list articles in ``group`` through one node (``c``, an nntp Client),
    found with HDR Subject over the last ``scan`` articles, each signature checked."""
    try:
        _, low, high = await c.group(group)
    except Exception:  # noqa: BLE001 - the node does not carry it
        return []
    if high < low:
        return []
    numbers = []
    for line in await c.multiline(f"HDR Subject {max(low, high - scan + 1)}-{high}", 225):
        number, _, subject = line.partition(" ")
        if _SUBJECT.match(subject.strip()):
            numbers.append(number)
    raws = [r for r in [await c.article(n) for n in numbers[-limit:]] if r]
    return [Vote(a, b) for a, b in votes_in(raws)]


def votes_of(bodies) -> list[Vote]:
    """The votes among what a reader returned (bodies and votes mixed)."""
    return [b for b in bodies if isinstance(b, Vote)]


def newest(votes, kept: str | None = None, start: KeyList | None = None) -> tuple[KeyList, bool]:
    """The list to go by: counted from the newest list kept (counted before), else from
    the pinned first one - the project's, or ``start``, another publisher's (UN-RFC 0062
    section 6). A kept list that does not parse, or is older than the pinned one, is not
    used."""
    start = start or first()
    if kept:
        try:
            k = parse(kept)
            if start.seq and k.seq >= start.seq:
                start = k
        except KeyListProblem:
            pass
    return count(start, [(v.author, v.body) if isinstance(v, Vote) else v for v in votes])
