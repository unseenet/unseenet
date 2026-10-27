"""Tags (UN-RFC 0052): the author's own words on a post - its topics and content warnings.

Belongs here: what a tag is and the ``Tags`` header's form (section 3), the fixed set of
warnings shared with content labels (section 4), and a manifest's group tags (section 5).
Nodes check the form only and never act on tags (section 6); clients show them, blur
warnings as the reader chose, and let rules use them (UN-RFC 0051).

Not here: labels others attach (UN-RFC 0053), what a client draws.
"""

from __future__ import annotations

import re
import unicodedata

HEADER = "Tags"
MAX_TAGS = 8                          # section 3, and a manifest's tags (section 5)
MAX_LENGTH = 32
# section 4: what a post shows - shared with content labels (UN-RFC 0053)
WARNINGS = ("profanity", "sexual", "nudity", "violence", "gore", "spoiler")
WARNING_LABELS = {"profanity": "Profanity", "sexual": "Sexual content", "nudity": "Nudity",
                  "violence": "Violence", "gore": "Gore", "spoiler": "Spoiler"}
_FIRST = re.compile(r"^[^\W_]")       # a letter or a digit, any script
# '#word' in a text (section 3): a tag the author's client takes into the header when the
# post is written. Not inside a word, a URL fragment or an address; '# heading' (with a
# space) is Markdown; it must have a letter, so '#170' stays an issue number.
TAG_REF_RE = re.compile(r"(?<![\w@#!/&.+-])#([^\W_](?:[\w-]*[^\W_])?)(?![\w-])")


class TagError(ValueError):
    """A tag or a Tags header that is not as UN-RFC 0052 section 3 says."""


def is_tag(word: str) -> bool:
    """1-32 characters in NFC: lower-case letters (any script), digits, ``-``, beginning
    with a letter or a digit."""
    if not isinstance(word, str) or not 1 <= len(word) <= MAX_LENGTH:
        return False
    if unicodedata.normalize("NFC", word) != word or word != word.lower():
        return False
    if not _FIRST.match(word):
        return False
    return all(c == "-" or c.isdigit() or (c.isalpha() and not c.isupper()) for c in word)


def normalize(words) -> list[str]:
    """What an author typed, as tags: lower-cased, NFC, ``#`` and spaces trimmed, what
    cannot be a tag dropped, each once, at most 8 (section 3) - for a compose box."""
    out: list[str] = []
    for w in words:
        t = unicodedata.normalize("NFC", str(w)).strip().lstrip("#").strip().lower()
        if is_tag(t) and t not in out:
            out.append(t)
    return out[:MAX_TAGS]


def in_text(text: str) -> list[str]:
    """The tags a text names with ``#word``, normalised, each once, in order - for the
    author's client to put in the header (section 3); never read from others' posts."""
    words = [m.group(1) for m in TAG_REF_RE.finditer(text or "")
             if any(c.isalpha() for c in m.group(1))]
    return normalize(words)


def parse(value: str | None) -> tuple[str, ...]:
    """The tags of a ``Tags`` header; () for none. TagError if it is malformed."""
    if value is None or not value.strip():
        return ()
    tags = [t.strip() for t in value.split(",")]
    if not 1 <= len(tags) <= MAX_TAGS:
        raise TagError(f"a post has 1 to {MAX_TAGS} tags")
    for t in tags:
        if not is_tag(t):
            raise TagError(f"not a tag: {t!r} (lower-case letters, digits and -, at most {MAX_LENGTH})")
    if len(set(tags)) != len(tags):
        raise TagError("a tag is given twice")
    return tuple(tags)


def header(tags) -> tuple[str, str] | None:
    """The header for these tags, checked; None for none."""
    tags = list(tags or [])
    if not tags:
        return None
    value = ", ".join(tags)
    parse(value)
    return HEADER, value


def of_article(art) -> tuple[str, ...]:
    """The tags an article carries; () if none or malformed (a client shows nothing)."""
    try:
        return parse(art.get(HEADER))
    except TagError:
        return ()


def check_group_tags(data: dict) -> None:
    """ValueError if a manifest's ``tags`` are not 1 to 8 tags, each once (section 5)."""
    if "tags" not in data:
        return
    tags = data["tags"]
    if not isinstance(tags, list) or not tags or not all(isinstance(t, str) for t in tags):
        raise ValueError(f"tags is a list of 1 to {MAX_TAGS} tags")
    parse(", ".join(tags))


def warnings(tags) -> tuple[str, ...]:
    """The warnings among tags (section 4), in the set's order."""
    have = set(tags or ())
    return tuple(w for w in WARNINGS if w in have)



# --- the language of a post (section 5a) ----------------------------------------
LANG_HEADER = "Content-Language"
MAX_LANGUAGES = 4
_LANG = re.compile(r"^[a-z]{2,3}$")


def is_language(code: str) -> bool:
    """A primary language subtag of BCP 47: 2 or 3 lower-case letters."""
    return isinstance(code, str) and bool(_LANG.match(code))


def normalize_languages(codes) -> list[str]:
    """Language codes as an author's client takes them: lower-cased, a region dropped
    (``da-DK`` is ``da``), what is not one dropped, each once, at most 4."""
    out: list[str] = []
    for c in codes or []:
        c = str(c).strip().lower().replace("_", "-").split("-")[0]
        if is_language(c) and c not in out:
            out.append(c)
    return out[:MAX_LANGUAGES]


def parse_languages(value: str | None) -> tuple[str, ...]:
    """The codes of a ``Content-Language`` header; () for none. TagError if malformed."""
    if value is None or not value.strip():
        return ()
    codes = [c.strip() for c in value.split(",")]
    if not 1 <= len(codes) <= MAX_LANGUAGES or not all(is_language(c) for c in codes) \
            or len(set(codes)) != len(codes):
        raise TagError(f"Content-Language: 1 to {MAX_LANGUAGES} language codes such as da, en, each once")
    return tuple(codes)


def languages_of(art) -> tuple[str, ...]:
    """The languages an article says it is in; () if none or malformed."""
    try:
        return parse_languages(art.get(LANG_HEADER))
    except TagError:
        return ()


def check_group_languages(data: dict) -> None:
    """ValueError if a manifest's ``languages`` are not 1 to 4 codes, each once."""
    if "languages" not in data:
        return
    codes = data["languages"]
    if not isinstance(codes, list) or not codes:
        raise ValueError(f"languages is a list of 1 to {MAX_LANGUAGES} codes")
    parse_languages(", ".join(str(c) for c in codes))
