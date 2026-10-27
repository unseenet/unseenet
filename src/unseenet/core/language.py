"""The language of a text, told locally (#686, UN-RFC 0052 section 5a) - for a client to
suggest what a post, a comment or a chat line is written in, and for labellers such as
unseenet-watchman to decide it for themselves.

**A suggestion, never trusted.** The ``Content-Language`` header is the author's own
statement; moderation and labels never rely on it - one can say Danish and swear in
English - and decide the language from the text, with this.

**Small words first.** Each of nine languages - Danish, Norwegian, Swedish, German,
Dutch, English, French, Spanish, Italian - has a list of small words that are *not*
common in its neighbours, so Danish, Norwegian and Swedish are not confused, nor German
and Dutch, nor the Romance languages. A text is in a language when at least 2 of that
language's own small words are in it and at least twice as many as for the next best;
otherwise it is not known. A few KB, under 0.1 ms a post, also in the browser (Pyodide).

**Lingua afterwards, when installed** (``pip install "unseenet[language]"``, as Emkay
and the watchman use): asked only when the small words cannot tell, and taken only when
it is at least 80 % sure. About 170 MB - for the desktop clients, not the browser.

Measured on 1999 Usenet posts whose group says the language: small words 78 % right,
21 % "don't know", 0.7 % wrong; with Lingua after them 89 % right, 1.2 % wrong. Under
15 words the small words are right 43 % of the time and otherwise say they don't know -
they rarely guess wrong. Better none than a wrong one.

Moved here from unseenet-watchman's ``labels.py`` (which imports it from now on).
"""

from __future__ import annotations

import re

LANGS = ("da", "no", "sv", "de", "nl", "en", "fr", "es", "it")

# Small words that tell the languages apart. Only words that are NOT common in a
# neighbour (Danish, Norwegian and Swedish share many, and so do German and Dutch,
# French, Spanish and Italian), so that a shared word never decides between them.
STOPWORDS = {
    "da": "af noget nogen nogle meget mere hvad hvor bliver havde end ud jer lidt måske "
          "uden mellem hende siger sige gør gøre vores jeres tak",
    "no": "av meg deg seg noe noen mye mer hva ble blir enn hadde litt kanskje uten "
          "mellom sier si gjør gjøre vårt våre takk ikkje eg kva sånn veldig",
    "sv": "och jag inte att är för till också mycket något någon några vad hur hade än "
          "lite kanske utan mellan säger säga gör göra tack ska väl bara hon sedan då",
    "de": "und ich das ist nicht sie zu ein eine einen auch wie von bei nur noch nach "
          "wenn aber oder wir ihr wird werden kann haben sind mir mich dich dir uns euch "
          "schon sehr immer doch dass weil diese dieser kein keine nichts über unter "
          "gegen ohne durch heute jetzt warum",
    "nl": "het een van ik niet dat zijn op voor maar ook wel nog naar heb hebben zo wat "
          "hoe waar omdat deze geen niets wij jullie uit bij veel worden wordt werd zou "
          "moet heel toch alleen gewoon eigenlijk",
    "en": "the and is are was were be been to of that this it you he she we they not "
          "with on by from have has had do does did but or if what which who would could "
          "should will can just about there their them my your our very really because "
          "when then than these those some any into out up",
    "fr": "le les des une est pas je il elle nous vous ils qui dans pour avec mais ce "
          "cette ces très tout tous bien aussi comme être avoir fait peu sans parce quand "
          "alors rien chez moi toi lui leur aux",           # not du, plus, sur, ton, au: Danish
    "es": "el los las una es por para pero más muy también como del al su sus yo este "
          "esta esto eso ese hay está están ser estar tiene tengo hace cuando porque nada "
          "todo siempre ahora aquí bueno pues sí",
    "it": "il gli di è che non per anche come sono essere ho hai abbiamo questo questa "
          "quello perché quando molto tutto sempre ancora già dove cosa niente nel nella "
          "della delle degli dei sul sua mio tuo suo ci",
}
STOPWORDS = {lang: frozenset(ws.split()) for lang, ws in STOPWORDS.items()}
# Letters and digits, and the @ $ * of spellings like "@$$" and "f*ck"; no other
# punctuation, so "lort," is "lort".
_WORD = re.compile(r"[\w@$*]+(?:['’-][\w@$*]+)*")

SHORT = 8                     # a chat line shorter than this keeps the conversation's language


def looks_encoded(line: str) -> bool:
    """A line of encoded data (base64, uuencode, yEnc) rather than text: long, and
    without the spaces and the word lengths of a language. Its letter salad would
    otherwise be read as words (found on Usenet)."""
    s = line.strip()
    if len(s) < 40:
        return False
    if " " not in s:
        return True
    ws = s.split()
    return sum(len(w) for w in ws) / len(ws) > 12 or sum(len(w) <= 2 for w in ws) / len(ws) > 0.6


def words(text: str) -> list[str]:
    """The words of a post, lower case, without quoted lines, encoded data and the
    signature."""
    keep = []
    for line in (text or "").splitlines():
        if line.rstrip() == "--":
            break
        if not line.lstrip().startswith(">") and not looks_encoded(line):
            keep.append(line)
    return [w.lower() for w in _WORD.findall("\n".join(keep))]


def language(ws: list[str], min_hits: int = 2) -> str | None:
    """The language among LANGS, or None when it cannot be told: the language with most
    of its own small words, at least ``min_hits`` and twice the next one's."""
    counts = sorted(((sum(w in STOPWORDS[lang] for w in ws), lang) for lang in LANGS), reverse=True)
    (best, lang), (second, _) = counts[0], counts[1]
    return lang if best >= min_hits and best >= 2 * second else None


# Lingua (lingua-language-detector, offline), when installed: asked only when the small
# words cannot tell, and only taken when it is sure.
LINGUA_CODES = {"da": "DA", "no": "NB", "sv": "SV", "de": "DE", "nl": "NL", "en": "EN",
                "fr": "FR", "es": "ES", "it": "IT"}
LINGUA_SURE = 0.8
_lingua = None


def _lingua_detector():
    """The Lingua detector for LANGS, built once; False when Lingua is not installed."""
    global _lingua
    if _lingua is None:
        try:
            from lingua import IsoCode639_1, LanguageDetectorBuilder
            _lingua = LanguageDetectorBuilder.from_iso_codes_639_1(
                *[getattr(IsoCode639_1, c) for c in LINGUA_CODES.values()]).build()
        except ImportError:
            _lingua = False
    return _lingua


def lingua_language(ws: list[str]) -> str | None:
    """Lingua's answer when it is at least LINGUA_SURE sure; None otherwise, or when
    Lingua is not installed."""
    det = _lingua_detector()
    if not det:
        return None
    conf = det.compute_language_confidence_values(" ".join(ws))
    if not conf or conf[0].value < LINGUA_SURE:
        return None
    code = conf[0].language.iso_code_639_1.name.upper()
    return next((lang for lang, c in LINGUA_CODES.items() if c == code), None)


def detect(ws: list[str]) -> str | None:
    """The language of the words: their small words first, which are seldom wrong;
    Lingua when they cannot tell (if installed); None when neither is sure."""
    return language(ws) or lingua_language(ws)


def guess(text: str) -> str | None:
    """The language of a text, or None when it cannot be told (``detect(words(text))``)."""
    return detect(words(text))


def lingua_available() -> bool:
    """Whether Lingua is installed here (the desktop clients; not the browser build)."""
    return bool(_lingua_detector())
