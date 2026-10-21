"""A new identity's key-bound groups live 60 days until it is in use (#270,
UN-RFC 0029 section 4)."""

from datetime import date, datetime, timedelta, timezone

from unseenet.client.session import Session
from unseenet.core.vault import Vault
from unseenet.core import crypto
from unseenet.core.article import parse_date
from unseenet.core.groups import Manifest, make_manifest, personal_inbox_id

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}


def _session(tmp_path):
    s = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me")
    posted = []

    async def fake_post(art, node=None):
        posted.append(art)
        return art.message_id

    async def no_pow(_gid):
        return BITS

    async def nothing_there(fn, node=None):
        return False                           # the node has no inbox for us yet

    s._post_article, s.required_pow, s._call = fake_post, no_pow, nothing_there
    return s, posted


def _days_left(art, now=None):
    m = Manifest.from_article(art)
    return (m.expires - (now or parse_date(art["Date"]))).days


async def test_a_visitors_inbox_lives_60_days(tmp_path):
    s, posted = _session(tmp_path)
    gid = await s.ensure_inbox()
    assert gid == personal_inbox_id(s.identity().public_key)
    assert len(posted) == 1 and 59 <= _days_left(posted[0]) <= 60
    assert not s.in_use()
    await s.ensure_inbox()                     # again the same day: still one day, no repost
    assert s.data["identities"]["me"]["days_opened"] == [datetime.now(timezone.utc).date().isoformat()]


async def test_third_day_makes_it_in_use_and_renews_for_730_days(tmp_path):
    s, posted = _session(tmp_path)
    await s.ensure_inbox()
    now = datetime.now(timezone.utc)
    s.note_opened(now.date() + timedelta(days=5))
    assert not s.in_use()
    later = now + timedelta(days=12)
    renewed = await s.renew_key_bound(now=later)        # the third day
    assert s.in_use() and renewed == [personal_inbox_id(s.identity().public_key)]
    assert _days_left(posted[-1]) >= 729
    assert "days_opened" not in s.data["identities"]["me"]


async def test_until_in_use_renewal_gives_60_days_again(tmp_path):
    s, posted = _session(tmp_path)
    await s.ensure_inbox()
    now = datetime.now(timezone.utc)
    assert await s.renew_key_bound(now=now + timedelta(days=20)) == []   # 40 left: not yet
    s.data["identities"]["me"]["days_opened"] = []                      # keep it a visitor
    then = now + timedelta(days=35)
    renewed = await s.renew_key_bound(now=then)                         # 25 left
    assert renewed and 59 <= _days_left(posted[-1]) <= 60 and not s.in_use(now=then)


async def test_writing_or_a_contact_makes_it_in_use(tmp_path):
    s, posted = _session(tmp_path)
    await s.ensure_inbox()
    s.add_contact(crypto.Identity.generate().key_text, "Sonia")
    assert s.in_use()
    renewed = await s.renew_key_bound()                 # a short lifetime: renewed at once
    assert renewed and _days_left(posted[-1]) >= 729


def test_an_identity_with_a_long_inbox_is_in_use(tmp_path):
    s, _ = _session(tmp_path)
    me = s.identity()
    s.group_entry(personal_inbox_id(me.public_key)).update({"owner": True, "manifest": Manifest.from_article(
        make_manifest(me, "inbox", "inbox", pow_bits=BITS)).raw})
    assert s.in_use()


def test_note_opened_counts_different_days_only(tmp_path):
    s, _ = _session(tmp_path)
    d = date(2026, 10, 1)
    for day in (d, d, d + timedelta(days=1)):
        s.note_opened(day)
    assert not s.in_use() and len(s.data["identities"]["me"]["days_opened"]) == 2
    s.note_opened(d + timedelta(days=9))
    assert s.in_use()
