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
VOTE_PURPOSE = "UNSEENET-RELEASE-KEYS-VOTE-1"     # a vote for a list (section 3.1)
SUBJECT = "release-keys"
CHAIN_SUBJECT = "release-keys chain"              # every list from seq 2 (section 3.2)
VOTE_HEAD = "Unseenet key list vote"
MAX_KEYS = 8
_SUBJECT = re.compile(r"^release-keys ([1-9][0-9]{0,8}|chain)$")

# The project's first key list (section 5): the project key and two reserve keys,
# threshold 2, {"dev": 1} - made with tools/project/release_keys.py make on 3 Nov 2026
# and posted in unseenet.releases as release-keys 1. A stable release needs two of the
# three; a later list counts once two of them posted it.
# The project's later lists with their votes (section 3.2), as `chain_text` writes them:
# shipped with the client so that it counts them without the channel, and posted every
# month by CI (tools/announce.py keys). Empty while there is only the first list.
PROJECT_CHAIN: str = ""

PROJECT_FIRST: str | None = (
    '{"channels":{"dev":1},"keys":["ed25519:det5dxevwbk36eds2indrzlazyri3fq3bgdzw6kx4ems3o267sya",'
    '"ed25519:nvisp5te3fezpln7nq576yeq64lfd3jdhtlhxcxmylwgm23omlcq",'
    '"ed25519:et42lnxa66ctqk3aq5cmireslpgzj3hygg7wvo2k6ozrfmp43mcq"],'
    '"seq":1,"threshold":2,"v":1}\n')


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
    for v in votes:
        author, body = (v.author, v.body) if isinstance(v, Vote) else v
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


def votes_in(raws) -> list[Vote]:
    """The votes in the key-list articles among raw articles (``votes_from``), each
    article's signature checked here: a node's word is not taken."""
    from .core.article import Article
    from .nntp import strip_reader_headers
    out = []
    for raw in raws:
        try:
            art = Article.from_bytes(strip_reader_headers(raw))
            art.verify_signature()
        except Exception:  # noqa: BLE001 - not a valid article: no vote
            continue
        out += votes_from(crypto.key_to_text(art.author_key), art.get("Subject", "") or "",
                          art.body)
    return out


@dataclass(frozen=True)
class Vote:
    """A vote for a key list (section 3.1): the signer, the list's body, and its
    signature when it was signed inside a body (None: the signer posted the bare list).
    Carried among the bodies of release posts (``update.from_network``,
    ``service_update``)."""
    author: str
    body: str
    sig: str | None = field(default=None, compare=False)


def _signed(body: str) -> bytes:
    return body.rstrip("\n").encode("utf-8")


def split_signed(text: str) -> tuple[str, list[tuple[str, str]]]:
    """A signed list (section 3.1): the list's body (first line) and its (key, signature)
    blocks. A bare list has none."""
    text = (text or "").replace("\r\n", "\n").strip("\n")
    first_line, _, rest = text.partition("\n")
    blocks = []
    for block in re.split(r"\n\s*\n", rest):
        lines = [x for x in block.splitlines() if x.strip()]
        if not lines or lines[0].strip() != VOTE_HEAD:
            continue
        f = dict(x.split(": ", 1) for x in lines[1:] if ": " in x)
        if f.get("key") and f.get("signature"):
            blocks.append((f["key"].strip(), f["signature"].strip()))
    return first_line + "\n", blocks


def signed_text(body: str, blocks) -> str:
    """A list and its votes, as a ``release-keys <seq>`` article's body (section 3.1)."""
    out = body.rstrip("\n") + "\n"
    for key, sig in blocks:
        out += f"\n{VOTE_HEAD}\nkey: {key}\nsignature: {sig}\n"
    return out


def add_vote(text: str, identity: crypto.Identity) -> str:
    """``text`` (a bare or signed list) with this key's vote added, once."""
    body, blocks = split_signed(text)
    body = parse(body).body
    if not any(k == identity.key_text for k, _ in blocks):
        blocks = blocks + [(identity.key_text, identity.sign_text(VOTE_PURPOSE, _signed(body)))]
    return signed_text(body, blocks)


def _check(key: str, sig: str, body: str) -> bool:
    try:
        return crypto.verify(crypto.key_from_text(key), VOTE_PURPOSE, _signed(body),
                             crypto.sig_from_text(sig))
    except Exception:  # noqa: BLE001 - not a key or not a signature: no vote
        return False


def votes_from(author: str | None, subject: str, text: str) -> list[Vote]:
    """The votes an article carries (sections 3.1, 3.2): each signature inside it that
    checks out, whoever posted it, and - for a bare list - its author's own vote."""
    m = _SUBJECT.match((subject or "").strip())
    if not m:
        return []
    chain = m.group(1) == "chain"
    parts = re.split(r"\n--\n", (text or "").replace("\r\n", "\n")) if chain else [text]
    out = []
    for part in parts:
        body, blocks = split_signed(part)
        try:
            body = parse(body).body
        except KeyListProblem:
            continue
        if not blocks and author and not chain:
            out.append(Vote(author, body))
        out += [Vote(k, body, sig) for k, sig in blocks if _check(k, sig, body)]
    return out


def counted_chain(start: KeyList, votes) -> list[KeyList]:
    """The lists after ``start`` that count, oldest first (it stops before a fork)."""
    by_body: dict[str, set[str]] = {}
    for v in votes:
        a, b = (v.author, v.body) if isinstance(v, Vote) else v
        try:
            by_body.setdefault(parse(b).body, set()).add(a)
        except KeyListProblem:
            continue
    out, cur = [], start
    while cur.seq:
        nxt = [kl for kl in (parse(b) for b in by_body)
               if kl.seq == cur.seq + 1 and kl.prev == cur.hash
               and len(by_body[kl.body] & set(cur.keys)) >= cur.threshold]
        if len(nxt) != 1:
            return out
        cur = nxt[0]
        out.append(cur)
    return out


def chain_text(votes, start: KeyList | None = None) -> str:
    """The body of a ``release-keys chain`` post (section 3.2): every list counted after
    the first, oldest first, each with the votes signed inside a body; "" when there is
    none. A vote that was only an article by its signer cannot be carried."""
    start = start or first()
    sigs: dict[str, dict[str, str]] = {}
    for v in votes:
        if isinstance(v, Vote) and v.sig:
            sigs.setdefault(v.body, {}).setdefault(v.author, v.sig)
    parts = [signed_text(kl.body, sorted(sigs.get(kl.body, {}).items())).rstrip("\n")
             for kl in counted_chain(start, votes)]
    return ("\n--\n".join(parts) + "\n") if parts else ""


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
    return votes_in(raws)


def votes_of(bodies) -> list[Vote]:
    """The votes among what a reader returned (bodies and votes mixed)."""
    return [b for b in bodies if isinstance(b, Vote)]


def newest(votes, kept: str | None = None, start: KeyList | None = None) -> tuple[KeyList, bool]:
    """The list to go by: counted from the newest list kept (counted before), else from
    the pinned first one - the project's, or ``start``, another publisher's (UN-RFC 0062
    section 6). A kept list that does not parse, or is older than the pinned one, is not
    used."""
    votes = list(votes)
    if start is None and PROJECT_CHAIN:           # the project's chain, shipped (3.2)
        votes += votes_from(None, CHAIN_SUBJECT, PROJECT_CHAIN)
    start = start or first()
    if kept:
        try:
            k = parse(kept)
            if start.seq and k.seq >= start.seq:
                start = k
        except KeyListProblem:
            pass
    return count(start, [(v.author, v.body) if isinstance(v, Vote) else v for v in votes])
