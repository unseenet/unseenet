"""#424: your registered names are renewed by themselves, as key-bound groups are."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from unseenet.client import naming


def _cert(name, kind, days):
    return SimpleNamespace(name=name, kind=kind,
                           expires=datetime.now(timezone.utc) + timedelta(days=days))


async def test_a_registered_name_running_out_is_renewed_once(monkeypatch):
    s = type("S", (), {})()
    names = [_cert("lorensen", "registered", 10),        # runs out soon: renewed
             _cert("andlo", "registered", 200),          # not yet
             _cert("lorensen.dk", "domain", 5),          # the registrar renews these
             _cert("sonia@lorensen", "sub", 3)]          # given by you: renew_given
    sent = []
    monkeypatch.setattr(naming, "my_names", lambda _s: names)
    monkeypatch.setattr(naming, "pending", lambda _s: [])
    async def claim(_s, name, action="claim", to=None):
        sent.append((name, action))
        return "<claim@x>"
    monkeypatch.setattr(naming, "claim", claim)
    assert await naming.renew_held(s) == ["lorensen"]
    assert sent == [("lorensen", "renew")]
    assert await naming.renew_held(s) == []               # once per run
    assert sent == [("lorensen", "renew")]


async def test_not_while_a_renew_is_on_its_way(monkeypatch):
    s = type("S", (), {})()
    monkeypatch.setattr(naming, "my_names", lambda _s: [_cert("lorensen", "registered", 10)])
    monkeypatch.setattr(naming, "pending", lambda _s: [["lorensen", "renew", "2026-10-24T10:00:00Z"]])
    async def claim(*a, **k):
        raise AssertionError("not again")
    monkeypatch.setattr(naming, "claim", claim)
    assert await naming.renew_held(s) == []
