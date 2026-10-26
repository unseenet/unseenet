"""Recovery words (UN-RFC 0050 section 4): an identity's seed as 24 words.

The words encode the 32-octet Ed25519 seed itself (UN-RFC 0003) with BIP39's
encoding of entropy - 256 bits, an 8-bit checksum from SHA-256, 24 numbers of 11
bits, each a word from the BIP39 English list - but not BIP39's PBKDF2 seed
derivation: the words are the seed. So every identity, old or new, has words and
nothing about keys changes. They are "Unseenet recovery words", not a wallet phrase.

Reading is forgiving (section 4.1): any case, extra spaces and line breaks, and the
first four letters of a word are enough. A wrong checksum is a typing mistake and is
said so before anything else happens.

Nothing here saves or sends the words; that is for the clients, under section 4.3.

The word list (data/bip39-english.txt) is BIP39's english.txt from
github.com/bitcoin/bips, bip-0039, unchanged; its SHA-256 is checked when it is read.
"""

from __future__ import annotations

import hashlib
import unicodedata
from functools import lru_cache
from importlib import resources

WORDS = 24
SEED_BYTES = 32
WORDLIST_SHA256 = "2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda"
NAME = "Unseenet recovery words"
NOT_A_WALLET = ("These are Unseenet recovery words, not a cryptocurrency wallet phrase: "
                "never type them into a wallet.")


class RecoveryError(ValueError):
    """The words cannot be read. ``kind`` says why: "count" (not 24 words), "word" (one
    is not on the list; ``position`` and ``word`` say which), "checksum" (a typing
    mistake somewhere) or "seed" (not a 32-octet seed)."""

    def __init__(self, kind: str, message: str, position: int | None = None,
                 word: str | None = None):
        super().__init__(message)
        self.kind, self.position, self.word = kind, position, word


@lru_cache(maxsize=1)
def wordlist() -> tuple[str, ...]:
    """The BIP39 English word list, checked against its well-known SHA-256."""
    raw = resources.files("unseenet.core").joinpath("data/bip39-english.txt").read_bytes()
    if hashlib.sha256(raw).hexdigest() != WORDLIST_SHA256:
        raise RuntimeError("the BIP39 word list is not the expected one")
    words = tuple(raw.decode().split())
    assert len(words) == 2048
    return words


@lru_cache(maxsize=1)
def _index() -> dict[str, int]:
    """Every word, and its first four letters (unique in BIP39), to its number."""
    out: dict[str, int] = {}
    for i, w in enumerate(wordlist()):
        out[w] = i
        out.setdefault(w[:4], i)
    return out


def words_from_seed(seed: bytes) -> list[str]:
    """The 24 recovery words of a 32-octet seed (section 4.1)."""
    if len(seed) != SEED_BYTES:
        raise RecoveryError("seed", "a seed is 32 octets")
    check = hashlib.sha256(seed).digest()[0]
    bits = (int.from_bytes(seed, "big") << 8) | check
    wl = wordlist()
    return [wl[(bits >> (11 * (WORDS - 1 - i))) & 0x7FF] for i in range(WORDS)]


def split_words(text: str) -> list[str]:
    """The words as typed: lower case, accents of a typing keyboard removed, split on
    any spaces, line breaks, commas or numbering such as ``1.`` or ``12)``."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    for ch in ",;.:)(-":
        text = text.replace(ch, " ")
    return [w for w in text.split() if not w.isdigit()]


def seed_from_words(text: str | list[str]) -> bytes:
    """The seed the words encode. Raises ``RecoveryError`` with a message a person
    can act on: which word is unknown, or that the checksum shows a typing mistake."""
    words = split_words(text) if isinstance(text, str) else split_words(" ".join(text))
    if len(words) != WORDS:
        raise RecoveryError("count", f"Recovery words are {WORDS} words; these are {len(words)}.")
    index = _index()
    bits = 0
    for pos, w in enumerate(words, 1):
        n = index.get(w)
        if n is None and len(w) >= 4:
            n = index.get(w[:4])
        if n is None:
            raise RecoveryError("word", f"Word {pos}, \"{w}\", is not a recovery word. "
                                        "Check the spelling.", position=pos, word=w)
        bits = (bits << 11) | n
    seed = (bits >> 8).to_bytes(SEED_BYTES, "big")
    if hashlib.sha256(seed).digest()[0] != bits & 0xFF:
        raise RecoveryError("checksum", "The words do not fit together: one of them is "
                                        "probably mistyped or in the wrong place.")
    return seed


def normalised(text: str | list[str]) -> list[str]:
    """The full words, as they should be written down, from what was typed (four
    letters are enough); raises ``RecoveryError`` like ``seed_from_words``."""
    return words_from_seed(seed_from_words(text))


def check_positions(count: int = 3, rng=None) -> list[int]:
    """Which words (1-24) to ask back after showing them (section 4.2), in order."""
    import secrets
    pick = rng.sample if rng is not None else secrets.SystemRandom().sample
    return sorted(pick(range(1, WORDS + 1), count))


def text_page(name: str, fingerprint: str, words: list[str]) -> str:
    """The plain text for *Save as file* or *Print* (section 4.3): the identity's name,
    fingerprint, the 24 words numbered, and how to restore, with what does not come
    back. The client decides whether and where; this only makes the text."""
    rows = "\n".join(f"{i:2}. {words[i - 1]:<10}  {i + 12:2}. {words[i + 11]}"
                     for i in range(1, 13))
    return (f"{NAME}\n{'=' * len(NAME)}\n\n"
            f"Identity:    {name}\nFingerprint: {fingerprint}\n\n{rows}\n\n"
            "Whoever has these words IS this identity: they can read its private posts\n"
            "and post in its name. Keep this page safe, away from the vault.\n\n"
            "To restore: in an Unseenet client choose \"Restore from recovery words\" and\n"
            "type the words. Your subscriptions, contacts and settings come back from the\n"
            "network. Closed groups do NOT come back: their owners must invite you again.\n\n"
            f"{NOT_A_WALLET}\n")
