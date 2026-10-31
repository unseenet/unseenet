"""Public name claims with commit and reveal (UN-RFC 0054 section 8, #689): the formats
and the order every replica reads them in, and the client's two steps against a local
node with a council registrar."""

from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
import unseenet.client.session.posting as posting
from unseenet import names as nm
from unseenet.client import naming
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}
T0 = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
ALICE = "ed25519:" + "a" * 52
BOB = "ed25519:" + "b" * 52


# --- the formats --------------------------------------------------------------------

def test_commit_and_reveal_fit_together():
    claim = nm.make_claim("claim", "lorensen")
    body, nonce = nm.make_commit(claim)
    c = nm.parse_commit(body)
    assert c == nm.commit_value(nonce, claim) and len(nonce) == 32
    r = nm.parse_reveal(nm.make_reveal(claim, nonce, "inbox@abcdefghijklmnop"))
    assert r.claim_body == claim and r.nonce == nonce and r.reply_inbox == "inbox@abcdefghijklmnop"
    # another nonce, another claim: another c
    assert nm.make_commit(claim)[0] != body
    assert nm.commit_value(nonce, nm.make_claim("claim", "lorenzen")) != c
    with pytest.raises(nm.NameProblem):
        nm.parse_commit('{"commit":"x","extra":1,"v":1}')
    with pytest.raises(nm.NameProblem):
        nm.commit_value(b"short", claim)


def _post(mid, subject, author, date, body):
    return nm.Post(mid, subject, author, date, body)


def _pair(mid, author, date, name, reveal_after=timedelta(hours=2), inbox="inbox@abcdefghijklmnop"):
    claim = nm.make_claim("claim", name)
    body, nonce = nm.make_commit(claim)
    posts = [_post(mid, "commit", author, date, body)]
    if reveal_after is not None:
        posts.append(_post(f"<r{mid}>", nm.reveal_subject(mid), author, date + reveal_after,
                           nm.make_reveal(claim, nonce, inbox)))
    return posts


def test_a_reveal_counts_only_from_its_author_in_its_window():
    claim = nm.make_claim("claim", "lorensen")
    commit, reveal = _pair("<2@x>", ALICE, T0, "lorensen")

    def with_reveal(**kw):
        r = nm.Post(**{**reveal.__dict__, **kw})
        return nm.read_public_claims([commit, r])[0]

    assert with_reveal().claim_body == claim
    assert with_reveal(author=BOB).revealed is None                         # not its author
    assert with_reveal(date=T0 + timedelta(minutes=50)).revealed is None    # too early
    assert with_reveal(date=T0 + timedelta(days=7, minutes=1)).revealed is None   # too late
    assert with_reveal(subject="reveal <other@x>").revealed is None
    tampered = reveal.body.replace("lorensen", "lorenzen")
    assert with_reveal(body=tampered).revealed is None                      # not its c


def test_the_order_waits_for_every_earlier_commit():
    posts = (_pair("<1@x>", ALICE, T0, "aaa", reveal_after=timedelta(hours=3))
             + _pair("<2@x>", BOB, T0 + timedelta(minutes=10), "bbb", reveal_after=None)
             + _pair("<3@x>", ALICE, T0 + timedelta(minutes=20), "ccc"))
    claims = nm.read_public_claims(posts)
    assert [c.id for c in claims] == ["<1@x>", "<2@x>", "<3@x>"]
    ready, gone = nm.ready_claims(claims, T0 + timedelta(days=1))
    assert [c.id for c in ready] == ["<1@x>"] and gone == []        # <2> may still reveal
    ready, gone = nm.ready_claims(claims, T0 + timedelta(days=7, hours=2))
    assert [c.id for c in ready] == ["<1@x>", "<3@x>"] and [c.id for c in gone] == ["<2@x>"]


def test_the_outcome_hash_leaves_reasons_out():
    a = nm.outcome_hash({"refuse": True})
    assert a == nm.outcome_hash({"refuse": True})
    assert a != nm.outcome_hash({"revoke": 3})
    assert nm.outcome_hash({"issue": ["x", ALICE, 1, "2027-01-01T00:00:00Z"]}) != a


# --- the client, against a council registrar on a local node --------------------------------

@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    from unseenet.node import server as node_server
    monkeypatch.setattr(node_server, "POST_PAST", timedelta(days=3650))
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    clock = {"now": datetime.now(timezone.utc) - timedelta(hours=3)}
    real = posting.new_article
    monkeypatch.setattr(posting, "new_article",
                        lambda *a, **k: real(*a, **{**k, "now": k.get("now") or clock["now"]}))
    made = []

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title())
        p.add_node(addr)
        made.append(p)
        return p
    yield person, clock
    for p in made:
        await p.close()
    server.close()


async def council_registrar(members, monkeypatch):
    """A council registrar: the open claims group and the channel registrar group, with
    the same council, each founded by every member posting its genesis."""
    keys = [m.identity().key_text for m in members]
    a = members[0]
    claims, body = a.council_genesis("unseenet.names.claims", "open", keys,
                                     fields={"min_pow": 8, "retention_days": 30})
    for m in members:
        await m.council_sign(claims, body)
    names, body = a.council_genesis("unseenet.names", "channel", keys,
                                    fields={"min_pow": 0, "claims": claims})
    for m in members:
        await m.council_sign(names, body)
    monkeypatch.setattr(nm, "NAMES_GROUP", names)
    return names, claims


async def test_the_client_commits_then_reveals(net, monkeypatch):
    person, clock = net
    r1, r2, alice = person("replica1"), person("replica2"), person("alice")
    names, claims = await council_registrar([r1, r2], monkeypatch)

    await alice.refresh_naming()
    assert naming.claims_are_public(alice)
    assert set(naming._registrars(alice)) == {r1.identity().key_text, r2.identity().key_text}
    real_now = datetime.now(timezone.utc)
    await naming.claim(alice, "lorensen")
    (c,) = naming.commits(alice)
    assert c["state"] == "waiting" and "nonce" not in c
    assert [p[0] for p in naming.pending(alice)] == ["lorensen"]

    posts = [m for m in await r1.fetch_group(claims) if m.subject == "commit"]
    assert [m.author_key for m in posts] == [alice.identity().key_text]
    assert "lorensen" not in posts[0].body                    # nothing to read yet

    assert await naming.reveal_due(alice, now=real_now) == []          # not an hour old
    # here the commit went out with the test's clock; the client keeps its Date
    assert posts[0].date == clock["now"].replace(second=0, microsecond=0,
                                                 minute=clock["now"].minute // 10 * 10)
    naming._store(alice)["commits"][0]["date"] = nm.rfc3339(posts[0].date)
    clock["now"] = datetime.now(timezone.utc)
    assert await naming.reveal_due(alice) == ["lorensen"]
    assert naming.commits(alice)[0]["state"] == "revealed"
    assert await naming.reveal_due(alice) == []                         # once

    got = [nm.Post(m.message_id, m.subject, m.author_key, m.date, m.body)
           for m in await r2.fetch_group(claims)]
    (pc,) = nm.read_public_claims(got)
    assert pc.sender == alice.identity().key_text and pc.reply_inbox == alice.my_inbox
    assert nm.parse_claim(pc.claim_body)["name"] == "lorensen"

    # every replica answers; the first answer from a registrar key is kept
    await r1.send_private(alice.my_inbox, "name lorensen: refused", "the name is taken\n")
    await r2.send_private(alice.my_inbox, "name lorensen: issued", "{}\n")
    stranger = person("stranger")
    await stranger.send_private(alice.my_inbox, "name lorensen: issued", "{}\n")
    await alice.fetch_group(alice.my_inbox)
    assert naming.take_answers(alice) == 1
    (c,) = naming.commits(alice)
    assert c["state"] == "answered" and c["answer"]["outcome"] == "refused"
    assert c["answer"]["from"] == r1.identity().key_text
    assert naming.pending(alice) == []


async def test_a_commit_lapses_without_its_reveal(net, monkeypatch):
    person, _ = net
    r1, r2, alice = person("replica1"), person("replica2"), person("alice")
    await council_registrar([r1, r2], monkeypatch)
    await alice.refresh_naming()
    await naming.claim(alice, "lorensen")
    later = datetime.now(timezone.utc) + timedelta(days=8)
    assert await naming.reveal_due(alice, now=later) == []
    assert naming.commit_state(naming._store(alice)["commits"][0], later) == "lapsed"


async def test_the_command_line_says_claims_are_public(net, monkeypatch, capsys):
    from argparse import Namespace

    from unseenet import cli
    person, _ = net
    r1, r2, alice = person("replica1"), person("replica2"), person("alice")
    await council_registrar([r1, r2], monkeypatch)

    class App:
        session = alice
    await cli.c_name_claim(App(), Namespace(json=False, identity=None, name="@lorensen",
                                            action="claim", to=None, yes=True))
    out = capsys.readouterr().out
    assert "Claims are public" in out and "first step is posted" in out
    await cli.c_names(App(), Namespace(json=True, identity=None))
    import json
    shown = json.loads(capsys.readouterr().out)
    assert [c["state"] for c in shown["public_claims"]] == ["waiting"]
    assert shown["pending"][0]["name"] == "lorensen"
