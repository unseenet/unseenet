"""#568 / #566: UN-RFC 0049 - no posting into the past, origin headers, old on arrival."""
from datetime import datetime, timedelta, timezone

import pytest

from unseenet import cli
from unseenet.client.session import Session, SessionError
from unseenet.client.threads import feed_threaded, threaded
from unseenet.core import crypto, origins
from unseenet.core.article import ArticleError, format_date, new_article
from unseenet.core.groups import approve, make_manifest
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}
NOW = datetime.now(timezone.utc)


# --- the origin headers (section 4) ------------------------------------------------------

def test_origin_dates_and_headers():
    assert origins.parse_origin_date("2026-08-03T14:20:00Z") == datetime(2026, 8, 3, 14, 20, tzinfo=timezone.utc)
    assert origins.parse_origin_date("Mon, 03 Aug 2026 16:20:00 +0200").hour == 14   # as a gateway copies it
    assert origins.parse_origin_date("last summer") is None
    date = datetime(2026, 10, 1, tzinfo=timezone.utc)
    h = {"Origin-Network": "Facebook", "Origin-Date": "2026-08-03T14:20:00Z", "Origin-From": "Andreas"}
    o = origins.origin_of(h.get, date)
    assert (o.network, o.date.month, o.from_) == ("facebook", 8, "Andreas")
    later = {**h, "Origin-Date": "2026-12-24T00:00:00Z"}
    assert origins.origin_of(later.get, date).date is None          # later than Date: ignored
    assert origins.origin_of({}.get, date) is None
    assert origins.origin_headers("mastodon", "2026-08-03T14:20:00Z", from_="@me@example.social") == [
        ("Origin-Network", "mastodon"), ("Origin-Date", "2026-08-03T14:20:00Z"),
        ("Origin-From", "@me@example.social")]
    for bad in (("Face Book", None), ("x", "yesterday"), ("x", NOW + timedelta(days=1))):
        with pytest.raises(origins.OriginError):
            origins.origin_headers(*bad)


def test_old_on_arrival_is_more_than_a_day():
    assert not origins.old_on_arrival(NOW - timedelta(hours=23), NOW)
    assert origins.old_on_arrival(NOW - timedelta(hours=25), NOW)
    assert not origins.old_on_arrival(None, NOW)


# --- the node (sections 3.2, 3.3) -------------------------------------------------------

def _node():
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))


def _post(gid, author, when, extra=None):
    return new_article(gid, "Hej", "hej\n", from_name="A", now=when, extra=extra).finalize(author, BITS)


def test_a_post_more_than_an_hour_old_is_refused_but_not_from_a_peer():
    node, owner = _node(), crypto.Identity.generate()
    m = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    node.accept(m.to_bytes())
    node.accept(_post(m.group, owner, NOW - timedelta(minutes=50)).to_bytes())      # within the hour
    old = _post(m.group, owner, NOW - timedelta(hours=3))
    with pytest.raises(ArticleError) as e:
        node.accept(old.to_bytes())
    assert e.value.reason == "date" and "in the past" in str(e.value)
    node.accept(old.to_bytes(), source="peer", from_peer=True)                    # arrives late: fine


def test_a_moderator_approves_a_days_old_submission_but_a_forged_approval_does_not_count():
    node = _node()
    owner, mod, user = (crypto.Identity.generate() for _ in range(3))
    m = make_manifest(owner, "dk.mod", "moderated", moderators=[mod.key_text], pow_bits=BITS)
    node.accept(m.to_bytes())
    sub = _post(m.group, user, NOW - timedelta(days=3))
    msgid = sub.message_id
    node.accept(approve(sub, mod).to_bytes())                  # Date stays the author's (3.2)
    assert node.store.get(msgid) is not None
    forged = _post(m.group, user, NOW - timedelta(days=2))
    forged.set("Approved-By", mod.key_text)
    forged.set("Approval", user.sign_text(crypto.PURPOSE_APPROVAL, b"x"))
    with pytest.raises(ArticleError) as e:
        node.accept(forged.to_bytes())
    assert e.value.reason == "date"
    o = make_manifest(owner, "dk.open", "open", pow_bits=BITS)
    node.accept(o.to_bytes())
    sneaky = _post(o.group, user, NOW - timedelta(days=2))
    sneaky.set("Approved-By", user.key_text)                   # an approval in an open group
    with pytest.raises(ArticleError):
        node.accept(sneaky.to_bytes())


# --- the session ------------------------------------------------------------------------

@pytest.fixture
async def world(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", BITS)
    node = _node()
    server = await node.serve("127.0.0.1", 0)
    addr = "127.0.0.1:%d" % server.sockets[0].getsockname()[1]
    made = []

    def person(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        made.append(s)
        return s
    yield node, person
    for s in made:
        await s.close()
    server.close()


async def test_an_article_that_waited_is_posted_with_the_time_of_posting(world):
    node, person = world
    me = person("andreas")
    gid = await me.create_group("dk.snak", "open", min_pow=BITS)
    waited = _post(gid, me.identity(), NOW - timedelta(hours=5))
    old_id = waited.message_id
    msgid = await me.post_article(waited)                      # a queue, offline for hours
    assert msgid != old_id and node.store.get(old_id) is None
    posted = node.store.get(msgid).decode()
    assert format_date(NOW)[:16] in posted or format_date(datetime.now(timezone.utc))[:16] in posted


async def test_imports_show_their_origin_and_are_old_on_arrival(world):
    node, person = world
    me, sonia = person("andreas"), person("sonia")
    gid = await me.create_group("dk.snak", "open", min_pow=BITS)
    mine = await me.post(gid, "Today", "today\n")
    await sonia.fetch_group(gid)
    sonia.subscribe(gid)
    reply = await sonia.post(gid, "Re: Today", "an old reply\n", references=[mine],
                             origin={"network": "facebook", "date": NOW - timedelta(days=40)})
    newer = await sonia.post(gid, "Re: Today", "a reply now\n", references=[mine])
    msgs = {m.message_id: m for m in await me.fetch_group(gid)}
    old = msgs[reply]
    assert (old.origin_network, old.old_on_arrival) == ("facebook", True)
    assert old.to_dict()["origin"]["network"] == "facebook" and old.to_dict()["old_on_arrival"]
    assert not msgs[newer].old_on_arrival and msgs[newer].to_dict()["origin"] is None
    me.subscribe(gid)
    assert me.for_me(old) is None and me.for_me(msgs[newer]) == "reply"     # not in For you
    assert me.unread_count(gid) == 1                                        # not new either
    rows = [m.message_id for m, _ in threaded(list(msgs.values()))]
    assert rows.index(reply) < rows.index(newer)                # in the thread: by origin date


async def test_the_timeline_puts_imports_where_they_belong(world):
    node, person = world
    me, sonia = person("andreas"), person("sonia")
    gid = await sonia.create_group("dk.notes", "channel", min_pow=BITS, view="feed")
    now_post = await sonia.post(gid, "Now", "now\n")
    old_post = await sonia.post(gid, "Then", "from August\n",
                                origin={"network": "x", "date": "2026-08-03T14:20:00Z"})
    msgs = await me.fetch_group(gid)
    order = [m.message_id for m, d in feed_threaded(msgs) if d == 0]
    assert order == [now_post, old_post]                        # not on top of everything


async def test_a_bad_origin_is_refused_before_posting(world):
    _, person = world
    me = person("andreas")
    gid = await me.create_group("dk.snak", "open", min_pow=BITS)
    with pytest.raises(SessionError, match="Origin"):
        await me.post(gid, "x", "y\n", origin={"network": "fb", "date": "someday"})
    from unseenet.client.localapi import LocalAPI
    api = LocalAPI(session=me)
    with pytest.raises(SessionError, match="Origin"):
        api.post(gid, {"subject": "x", "body": "y", "origin": {"network": "Not OK"}})


def test_the_cli_has_the_origin_options(capsys):
    with pytest.raises(SystemExit):
        cli.client_main(["post", "--help"])
    out = capsys.readouterr().out
    assert "--origin-network" in out and "--origin-date" in out
