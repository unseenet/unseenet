"""Reactions (UN-RFC 0048): one emoji under an article, as an article of its own.

Belongs here: what an emoji is (section 3.2), a group's reaction set from its manifest
(section 4), checking and building reaction articles (section 3), and counting them,
one per key (sections 5 and 7.1).

Not here: the node's rules (node/server: groups.check_permitted calls ``check_reaction``),
the store's index of reactions (core/store/reactions.py), the Session's react/count
(client/session/reactions.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

from .article import Article, ArticleError, new_article

KIND_REACTION = "reaction"
HEADER = "Reaction"
DEFAULT_SET = ("👍", "👎", "❤️", "😂", "😮", "😢")   # section 4.2
MAX_SET = 12                                         # section 4.1
ANY = "any"
VS16 = "\ufe0f"
SKIN_TONES = {chr(c) for c in range(0x1F3FB, 0x1F400)}
# views whose groups take the default set when the manifest says nothing (section 4.2)
DEFAULT_VIEWS = ("feed", "chat")


def _strip(text: str) -> str:
    return text.replace(VS16, "")


@lru_cache(maxsize=1)
def _known() -> frozenset[str]:
    """Every emoji of the gemoji table the implementations ship (UN-RFC 0031 section
    5.2), without VS16. gemoji 4.1.0 covers Unicode 15; skin tones are added in
    ``is_emoji``."""
    from .markup import emoji_table
    return frozenset(_strip(e) for e in emoji_table().values())


def is_emoji(text: str) -> bool:
    """One emoji as UN-RFC 0048 section 3.2 says: a sequence of the table, compared
    without VS16, optionally with one skin-tone modifier after a code point."""
    s = _strip(text)
    if not s or s.isascii():
        return False
    if s in _known():
        return True
    tones = [i for i, ch in enumerate(s) if ch in SKIN_TONES]
    if len(tones) == 1 or (len(tones) > 1 and "\u200d" in s):
        return "".join(ch for ch in s if ch not in SKIN_TONES) in _known()
    return False


def same_emoji(a: str, b: str) -> bool:
    """Whether two spellings are the same emoji (compared without VS16)."""
    return _strip(a) == _strip(b)


# --- the group's reaction set (section 4) -----------------------------------

def check_field(data: dict) -> None:
    """ValueError unless a manifest's ``reactions`` is as section 4.1 says."""
    if "reactions" not in data:
        return
    value = data["reactions"]
    if data.get("view") == "data":
        raise ValueError("a data group takes no reactions")
    if value == ANY:
        return
    if not isinstance(value, list) or len(value) > MAX_SET:
        raise ValueError(f'reactions is "any" or a list of at most {MAX_SET} emoji')
    if any(not isinstance(e, str) or not is_emoji(e) for e in value):
        raise ValueError("reactions lists one emoji per entry")
    if len({_strip(e) for e in value}) != len(value):
        raise ValueError("reactions names an emoji twice")


@dataclass(frozen=True)
class ReactionSet:
    """What a group takes: ``any``, or the emoji in ``emoji`` (none if empty)."""
    emoji: tuple[str, ...] = ()
    any: bool = False

    def takes(self, e: str) -> bool:
        """Whether the group takes ``e`` as a reaction."""
        if not is_emoji(e):
            return False
        return self.any or any(same_emoji(e, x) for x in self.emoji)

    @property
    def offered(self) -> tuple[str, ...]:
        """What a client offers first, in order (section 7.3)."""
        return DEFAULT_SET if self.any else self.emoji

    def __bool__(self) -> bool:
        return self.any or bool(self.emoji)


NONE = ReactionSet()


def reaction_set(data: dict) -> ReactionSet:
    """A group's reaction set from its manifest's JSON (section 4); inboxes take
    any emoji (section 4.3)."""
    if data.get("type") == "inbox":
        return ReactionSet(any=True)
    if "reactions" not in data:
        return ReactionSet(DEFAULT_SET) if data.get("view") in DEFAULT_VIEWS else NONE
    value = data["reactions"]
    if value == ANY:
        return ReactionSet(any=True)
    return ReactionSet(tuple(value))


# --- reaction articles (section 3) ------------------------------------------

def is_reaction(art: Article) -> bool:
    """A plain (or decrypted inner) article of kind reaction."""
    return (art.control is None
            and (art.get("Message-Kind") or "").strip().lower() == KIND_REACTION)


def target(art: Article) -> str | None:
    """The Message-ID a reaction is about: the last of its References."""
    refs = (art.get("References") or "").split()
    return refs[-1] if refs else None


def check_form(art: Article) -> str:
    """Section 3.1: raise ArticleError('syntax') unless the reaction is well formed.
    Answers its emoji."""
    e = (art.get(HEADER) or "").strip()
    if not is_emoji(e):
        raise ArticleError("syntax", "Reaction must hold exactly one emoji")
    if (art.get("Subject") or "").strip():
        raise ArticleError("syntax", "a reaction has no subject")
    if target(art) is None:
        raise ArticleError("syntax", "a reaction names its article in References")
    if not same_emoji(art.body.strip(), e):
        raise ArticleError("syntax", "a reaction's body is its emoji")
    ctype = (art.get("Content-Type") or "text/plain").split(";")[0].strip().lower()
    if ctype != "text/plain" or art.get("Blobs") is not None:
        raise ArticleError("syntax", "a reaction is plain text without files")
    return e


def headers(emoji: str) -> list[tuple[str, str]]:
    """The headers that make an article a reaction (with an empty Subject)."""
    return [("Content-Type", "text/plain; charset=utf-8"),
            ("Message-Kind", KIND_REACTION), (HEADER, emoji)]


def build(group: str, target_refs: list[str], target_id: str, emoji: str, *,
          from_name: str | None = None,
          supersedes: str | None = None) -> Article:
    """An unsigned reaction to ``target_id``, whose own References are
    ``target_refs`` (section 3.1). ``supersedes``: the key's earlier reaction to the
    same article, which this one replaces (section 5)."""
    if not is_emoji(emoji):
        raise ValueError("a reaction is one emoji")
    extra = headers(emoji)
    if supersedes:
        extra.append(("Supersedes", supersedes))
    return new_article(group, "", emoji + "\n", from_name=from_name,
                       references=[*target_refs, target_id], extra=extra)


# --- counting (sections 5 and 7.1) ------------------------------------------

@dataclass
class Counts:
    """The reactions to one article: per emoji the keys that gave it, and each
    key's reaction (its Message-ID) so it can be changed or taken back."""
    by_emoji: dict[str, list[str]] = field(default_factory=dict)
    by_key: dict[str, tuple[str, str]] = field(default_factory=dict)   # key -> (emoji, id)

    def count(self, emoji: str) -> int:
        """How many keys gave ``emoji``."""
        return next((len(v) for e, v in self.by_emoji.items() if same_emoji(e, emoji)), 0)

    def total(self) -> int:
        """How many keys reacted at all."""
        return len(self.by_key)

    def of(self, key: str) -> str | None:
        """The emoji this key gave, or None."""
        mine = self.by_key.get(key)
        return mine[0] if mine else None


def count(items: Iterable[tuple[str, str, int, str, str]]) -> dict[str, Counts]:
    """Count reactions, one per key per target (section 5): ``items`` are
    ``(message_id, author_key, date, target, emoji)``. A key with several counts
    only the latest by date, and among equal dates the greatest Message-ID.
    Answers {target: Counts}, emoji in the order they were first given."""
    latest: dict[tuple[str, str], tuple[int, str, str]] = {}
    order: dict[str, list[str]] = {}
    for mid, key, date, tgt, e in items:
        if not is_emoji(e):
            continue
        e = _canonical(e)
        order.setdefault(tgt, [])
        if e not in order[tgt]:
            order[tgt].append(e)
        cur = latest.get((tgt, key))
        if cur is None or (date, mid) > (cur[0], cur[1]):
            latest[(tgt, key)] = (date, mid, e)
    out: dict[str, Counts] = {}
    for (tgt, key), (_, mid, e) in latest.items():
        c = out.setdefault(tgt, Counts())
        c.by_key[key] = (e, mid)
    for tgt, c in out.items():
        for e in order[tgt]:
            keys = [k for k, (x, _) in c.by_key.items() if x == e]
            if keys:
                c.by_emoji[e] = keys
    return out


def _canonical(e: str) -> str:
    """One spelling per emoji: the table's (with VS16 where it has one)."""
    s = _strip(e)
    for x in DEFAULT_SET:
        if _strip(x) == s:
            return x
    return _table_spelling().get(s, e)


@lru_cache(maxsize=1)
def _table_spelling() -> dict[str, str]:
    from .markup import emoji_table
    return {_strip(v): v for v in emoji_table().values()}
