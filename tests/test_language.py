"""#686: a text's language, told locally (core.language, moved from unseenet-watchman),
and what a client suggests from it (UN-RFC 0052 section 5a)."""

import pytest

from unseenet.core import language as lg


@pytest.mark.parametrize("lang,text", [
    ("da", "Jeg har lidt travlt, og det er måske noget vi kan tage op senere hvis I vil"),
    ("no", "Jeg har litt dårlig tid, og det er kanskje noe vi kan ta opp senere hvis dere vil"),
    ("sv", "Jag har lite ont om tid och det är kanske något vi kan ta upp senare om ni vill"),
    ("de", "Ich habe wenig Zeit und das ist vielleicht etwas, das wir später machen können"),
    ("nl", "Ik heb het druk en dat is misschien iets wat we later kunnen doen als jullie willen"),
    ("en", "I am a bit busy, and this is something we could pick up later if you would like"),
    ("fr", "Je suis un peu occupé et c'est peut-être quelque chose que nous ferons plus tard"),
    ("es", "Estoy un poco ocupado y esto es algo que podemos hacer más tarde si queréis"),
    ("it", "Sono un po' occupato e questo è qualcosa che possiamo fare più tardi se volete"),
])
def test_language_from_its_own_small_words(lang, text):
    assert lg.language(lg.words(text)) == lang
    assert lg.guess(text) == lang


def test_what_is_not_text_and_what_cannot_be_told():
    assert lg.looks_encoded("M9V]D;&5S(&]F('1H92!W;W)L9\"!A;F0@=&AE(&9I<G-T(&]F")
    assert not lg.looks_encoded("This is an ordinary line of English text that goes on a while.")
    assert lg.words("Hej\n> citeret tekst\nmere\n--\nsignatur") == ["hej", "mere"]
    assert lg.language(lg.words("ok")) is None and lg.language(lg.words("haha :)")) is None


def test_lingua_only_when_the_small_words_cannot_tell(monkeypatch):
    asked = []

    def fake(ws):
        asked.append(ws)
        return "sv"
    monkeypatch.setattr(lg, "lingua_language", fake)
    assert lg.detect(lg.words("Jeg har lidt travlt, måske noget vi kan tage senere")) == "da"
    assert asked == []                                        # the small words were sure
    assert lg.detect(lg.words("hej hej")) == "sv"             # they were not: Lingua


def test_lingua_when_installed():
    pytest.importorskip("lingua")
    assert lg.lingua_language(lg.words("Thanks for the help, see you tomorrow morning")) == "en"
