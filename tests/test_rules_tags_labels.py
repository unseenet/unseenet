"""#658, UN-RFC 0051 as amended: rules with ``tagged`` and ``labelled``, and ``blur``."""

import pytest

from unseenet.client import scoring as sc


def _score(text, **post):
    rules = sc.parse(text)
    assert not rules.problems, rules.problems
    return sc.score(rules, sc.Post("x", group=post.pop("group", "dk.snak"), **post), sc.Context())


def test_tagged_any_and_all():
    tags = frozenset({"politik", "danmark"})
    assert _score("+10 if tagged politics linux", tags=tags).score == 0
    assert _score("+10 if tagged politik linux", tags=tags).score == 10       # any of them
    assert _score("+20 if tagged all politik danmark", tags=tags).score == 20  # every one
    assert _score("+20 if tagged all politik sport", tags=tags).score == 0
    assert _score("+10 if tagged politik danmark", tags=tags).score == 10     # once, not per word
    assert _score("+5 if tagged politik and group is dk.*", tags=tags).score == 5
    assert _score("+5 if not tagged sport", tags=tags).score == 5
    assert _score("+5 if (tagged sport or tagged danmark) and group is dk.*", tags=tags).score == 5


def test_labelled_and_blur():
    r = _score("blur if labelled spoiler\nhide if labelled sexual nudity gore",
               labels=frozenset({"spoiler"}))
    assert r.actions == {"blur"} and r.shown
    r = _score("hide if labelled sexual nudity gore", labels=frozenset({"gore"}))
    assert not r.shown
    # labelled never sees the author's own tags, tagged never the labels
    assert _score("hide if labelled spoiler", tags=frozenset({"spoiler"})).shown
    assert _score("+1 if tagged spoiler", labels=frozenset({"spoiler"})).score == 0
    # blur is for the feed too, unlike fold
    assert not sc.parse("[feed]\nblur if labelled spoiler").problems
    assert sc.parse("[feed]\nfold if labelled spoiler").problems


def test_mistakes_say_so():
    rs = sc.parse("+10 if tagged\n+5 if taged linux")
    assert len(rs.problems) == 2
    assert "which tags" in str(rs.problems[0]) and "tagged" in str(rs.problems[1])


async def test_in_the_session(tmp_path, monkeypatch):
    """The author's tags and the group's count for tagged; a labeller's labels for
    labelled; the reader's rule blurs."""
    import unseenet.client.session as sess
    from unseenet.client.session import Session
    from unseenet.core.store import Store
    from unseenet.core.vault import Vault
    from unseenet.node.server import Node, NodeConfig
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    people = []
    for name in ("owner", "labeller", "me"):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", ops=1, mem=8192 * 1024), status=lambda *_: None)
        p.new_identity(name, name.title())
        p.add_node(addr)
        people.append(p)
    owner, labeller, me = people
    try:
        gid = await owner.create_group("dk.politik", "open", min_pow=8, extra={"tags": ["politik"]})
        a = await owner.post(gid, "Valg", "x\n", tags=["danmark"])
        b = await owner.post(gid, "Finale", "y\n")
        await labeller.start_labels(topics=True)
        await labeller.publish_labels([(b, gid, ["spoiler", "sport"])])
        me.subscribe(gid)
        me.follow_labeller(labeller.identity().key_text, topics=True)
        await me.fetch_group(gid)
        await me.refresh_labels()
        me.set_feed_rules("+20 if tagged all politik danmark\n+5 if labelled sport\nblur if labelled spoiler")
        got = {m.message_id: r for m, r in me.scored_group(gid)} if hasattr(me, "scored_group") else None
        msgs = {m.message_id: m for m in me.visible(me.cache[gid].values())}
        ra = sc.score(me.rule_set(), me.post_facts(msgs[a]), me.scoring_context(), "groups")
        rb = sc.score(me.rule_set(), me.post_facts(msgs[b]), me.scoring_context(), "groups")
        assert ra.score == 20 and not ra.actions
        assert rb.score == 5 and rb.actions == {"blur"}
        assert got is None or got[b].actions == {"blur"}
    finally:
        for p in people:
            await p.close()
        server.close()
