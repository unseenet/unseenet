"""Content labels (UN-RFC 0053, #656): labels describe, never sanction. Warnings are
blurred or hidden as the reader chose; topics count only by the reader's own choice;
nodes never act on labels."""

from datetime import datetime, timedelta, timezone

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core import crypto, labels as lb
from unseenet.core.vault import Vault
from unseenet.core.article import ArticleError
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    made = []

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title())
        p.add_node(addr)
        made.append(p)
        return p
    yield person
    for p in made:
        await p.close()
    server.close()


def test_label_articles():
    me = crypto.Identity.generate()
    gid = lb.labels_group(me.public_key)
    body = lb.label_body([("<a@x>", "dk.film@ab", ["spoiler"]), ("<b@x>", "alt.snak@cd", ["profanity", "politics"])],
                         note="Sæson 2")
    s = lb.read_labels("<l1@x>", gid, me.key_text, NOW, body)
    assert [(p.id, p.labels) for p in s.posts] == [("<a@x>", ("spoiler",)), ("<b@x>", ("profanity", "politics"))]
    for bad in ([("<a@x>", "inbox@ab", ["spoiler"])], [("<a@x>", "dk.film@ab", ["Spoiler"])],
                [("<a@x>", "dk.film@ab", ["x"] * 9)]):
        with pytest.raises(lb.LabelError):
            lb.label_body(bad)
    other = crypto.Identity.generate()
    with pytest.raises(lb.LabelError, match="own key"):
        lb.read_labels("<l2@x>", gid, other.key_text, NOW, body)
    # a malformed entry is left out, the rest counts
    raw = '{"v":1,"posts":[{"id":"<a@x>","group":"g@x","labels":["BAD"]},{"id":"<c@x>","group":"g@x","labels":["gore"]}]}'
    assert [p.id for p in lb.read_labels("<l3@x>", gid, me.key_text, NOW, raw).posts] == ["<c@x>"]
    # the newest article of a labeller about a post counts; [] takes it back
    book = lb.Book()
    book.add(lb.read_labels("<l1@x>", gid, me.key_text, NOW, body))
    assert book.labels("<a@x>") == {me.key_text: ("spoiler",)}
    book.add(lb.read_labels("<l4@x>", gid, me.key_text, NOW + timedelta(hours=1),
                            lb.label_body([("<a@x>", "dk.film@ab", [])])))
    assert book.labels("<a@x>") == {}


def test_nodes_check_the_channel_and_never_act():
    owner, labeller = crypto.Identity.generate(), crypto.Identity.generate()
    n = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), min_ripe=None))
    n.accept(make_manifest(labeller, "labels", "channel", pow_bits=16, extra={"topics": True}).to_bytes())
    with pytest.raises(ArticleError, match="channel"):
        n.accept(make_manifest(owner, "labels", "open", pow_bits=16).to_bytes())
    m = make_manifest(owner, "alt.snak", "open", pow_bits=16, extra={"labellers": [labeller.key_text]})
    n.accept(m.to_bytes())
    for bad in ([], [labeller.key_text, labeller.key_text], ["nonsense"]):
        with pytest.raises((ValueError, crypto.CryptoError)):
            make_manifest(owner, "alt.x", "open", pow_bits=16, extra={"labellers": bad})
    with pytest.raises(ValueError):
        make_manifest(owner, "alt.y", "open", pow_bits=16, extra={"topics": False})


async def test_what_the_reader_sees(net):
    """A group's owner names a labeller: its warnings count, its topics do not; the
    reader's own choice per warning; own posts never blurred; a labeller followed for
    topics gives topics."""
    owner, labeller, author, me = net("owner"), net("labeller"), net("author"), net("me")
    await labeller.start_labels(policy="Spoilers", topics=True)
    lkey = labeller.identity().key_text
    gid = await owner.create_group("alt.film", "open", min_pow=8, extra={"labellers": [lkey]})
    for s in (author, me):
        s.subscribe(gid)
        await s.fetch_group(gid)
    tagged = await author.post(gid, "Slutningen", "han dør\n", tags=["spoiler"])
    plain = await author.post(gid, "Trailer", "se den\n")
    mine = await me.post(gid, "Min", "x\n", tags=["gore"])
    [p] = [m for m in await labeller.fetch_group(gid) if m.message_id == plain]
    await labeller.publish_labels([(plain, gid, ["violence", "politics"])])

    await me.refresh_labels()
    rows = {m.message_id: m for m in me.visible(await me.fetch_group(gid))}
    assert rows[tagged].labels["action"] == "blur"                         # blurred by default
    assert rows[tagged].labels["warnings"][0]["by"] == ["author"]
    assert rows[plain].labels["warnings"][0]["warning"] == "violence"
    assert rows[plain].labels["topics"] == []                              # topics: not by default
    assert rows[mine].labels["action"] == "show"                           # never your own
    me.set_warning_choice("spoiler", "hide")
    assert me.post_labels(rows[tagged])["action"] == "hide"
    me.follow_labeller(lkey, "Filmfolk", topics=True)                      # your own choice
    await me.refresh_labels()
    assert me.post_labels(rows[plain])["topics"] == ["politics"]
    assert me.post_labels(rows[plain])["warnings"][0]["by"] == ["Filmfolk"]
    me.unfollow_labeller(lkey)                                              # also the group's
    assert me.post_labels(rows[plain]) is None
    [entry] = me.labellers()
    assert entry["groups"] == [gid] and entry["on"] is False


async def test_the_local_api(net):
    """UN-RFC 0046 section 4.23: labellers, warning choices, publishing as a job, and a
    row's labels."""
    import asyncio
    from unseenet.client.localapi import LocalAPI
    owner, labeller, me = net("owner"), net("labeller"), net("me")
    gid = await owner.create_group("alt.film", "open", min_pow=8)
    post = await owner.post(gid, "Slut", "x\n")
    lapi, api = LocalAPI(session=labeller), LocalAPI(session=me)
    assert (await lapi.start_labels({"policy": "Spoilers"}))["mine"]["policy"] == "Spoilers"
    job = (await lapi.publish_labels({"posts": [{"id": post, "group": gid, "labels": ["spoiler"]}]}))["job"]
    assert job
    for _ in range(100):
        if labeller.cache.get(labeller.my_labels_group()):
            break
        await asyncio.sleep(0.05)
    me.subscribe(gid)
    await me.fetch_group(gid)
    got = await api.follow_labeller({"key": labeller.identity().key_text, "label": "Film"})
    assert got["labellers"][0]["label"] == "Film" and got["labellers"][0]["yours"]
    await me.refresh_labels()
    row = next(r for r in api.group(gid)["rows"] if r["message"]["id"] == post)
    assert row["message"]["labels"]["action"] == "blur"
    assert api.warning_choice({"warning": "spoiler", "choice": "show"})["warnings"][-1]["choice"] == "show"
    row = next(r for r in api.group(gid)["rows"] if r["message"]["id"] == post)
    assert row["message"]["labels"]["action"] == "show"
