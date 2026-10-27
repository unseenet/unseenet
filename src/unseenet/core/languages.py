"""The list of languages a client offers when the author chooses what they write in
(UN-RFC 0052 section 5a) - one list for every client and program, so they all say the
same (asked for by the maintainer, 27 Oct 2026).

Each language: its code (a primary BCP 47 subtag, as in ``Content-Language``), its own
name (``Dansk``, ``Svenska``) and its English name. The nine that ``core.language`` can
tell from a text come first, then the most used others. **No flags**: a flag is a
country, not a language - English and Spanish are spoken in many, Switzerland has four
languages - and a pseudonymous network should not pick among disputed ones. Clients
show the code in a small badge and the language's own name.

Not here: telling a text's language (``core.language``), the header (``core.tags``).
"""

from __future__ import annotations

# (code, its own name, its English name); the first nine are the ones core.language knows
LANGUAGES: tuple[tuple[str, str, str], ...] = (
    ("da", "Dansk", "Danish"),
    ("no", "Norsk", "Norwegian"),
    ("sv", "Svenska", "Swedish"),
    ("de", "Deutsch", "German"),
    ("nl", "Nederlands", "Dutch"),
    ("en", "English", "English"),
    ("fr", "Français", "French"),
    ("es", "Español", "Spanish"),
    ("it", "Italiano", "Italian"),
    ("fi", "Suomi", "Finnish"),
    ("is", "Íslenska", "Icelandic"),
    ("fo", "Føroyskt", "Faroese"),
    ("kl", "Kalaallisut", "Greenlandic"),
    ("se", "Davvisámegiella", "Northern Sami"),
    ("et", "Eesti", "Estonian"),
    ("lv", "Latviešu", "Latvian"),
    ("lt", "Lietuvių", "Lithuanian"),
    ("pl", "Polski", "Polish"),
    ("cs", "Čeština", "Czech"),
    ("sk", "Slovenčina", "Slovak"),
    ("hu", "Magyar", "Hungarian"),
    ("ro", "Română", "Romanian"),
    ("bg", "Български", "Bulgarian"),
    ("el", "Ελληνικά", "Greek"),
    ("pt", "Português", "Portuguese"),
    ("ca", "Català", "Catalan"),
    ("eu", "Euskara", "Basque"),
    ("ga", "Gaeilge", "Irish"),
    ("cy", "Cymraeg", "Welsh"),
    ("hr", "Hrvatski", "Croatian"),
    ("sr", "Српски", "Serbian"),
    ("sl", "Slovenščina", "Slovenian"),
    ("uk", "Українська", "Ukrainian"),
    ("ru", "Русский", "Russian"),
    ("be", "Беларуская", "Belarusian"),
    ("tr", "Türkçe", "Turkish"),
    ("ar", "العربية", "Arabic"),
    ("fa", "فارسی", "Persian"),
    ("he", "עברית", "Hebrew"),
    ("ku", "Kurdî", "Kurdish"),
    ("hi", "हिन्दी", "Hindi"),
    ("ur", "اردو", "Urdu"),
    ("bn", "বাংলা", "Bengali"),
    ("ta", "தமிழ்", "Tamil"),
    ("zh", "中文", "Chinese"),
    ("ja", "日本語", "Japanese"),
    ("ko", "한국어", "Korean"),
    ("vi", "Tiếng Việt", "Vietnamese"),
    ("th", "ไทย", "Thai"),
    ("id", "Bahasa Indonesia", "Indonesian"),
    ("ms", "Bahasa Melayu", "Malay"),
    ("tl", "Tagalog", "Tagalog"),
    ("sw", "Kiswahili", "Swahili"),
    ("am", "አማርኛ", "Amharic"),
    ("so", "Soomaali", "Somali"),
    ("eo", "Esperanto", "Esperanto"),
    ("la", "Latina", "Latin"),
)
BY_CODE = {code: (own, english) for code, own, english in LANGUAGES}


def name(code: str) -> str:
    """A language's own name, or its code when it is not on the list."""
    return BY_CODE.get(code, (code, code))[0]


def as_list() -> list[dict]:
    """The list as clients take it: ``[{"code", "name", "english", "recognised"}]`` -
    ``recognised`` for the languages ``core.language`` can tell from a text."""
    from .language import LANGS
    return [{"code": c, "name": own, "english": en, "recognised": c in LANGS}
            for c, own, en in LANGUAGES]


def search(query: str) -> list[str]:
    """Codes whose code, own name or English name begins with ``query`` - "da", "dansk"
    and "danish" all find Danish; the code first."""
    q = (query or "").strip().casefold()
    if not q:
        return [c for c, _, _ in LANGUAGES]
    exact = [c for c, _, _ in LANGUAGES if c == q]
    rest = [c for c, own, en in LANGUAGES if c != q and (
        c.startswith(q) or own.casefold().startswith(q) or en.casefold().startswith(q))]
    return exact + rest
