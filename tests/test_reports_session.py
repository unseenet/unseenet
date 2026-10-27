"""UN-RFC 0045 in the client (#122): issuing reports, following issuers, hidden posts
shown as hidden, and the issuers a hierarchy names."""

import json

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session, SessionError
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

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
    person.node = node
    yield person
    for p in made:
        await p.close()
    server.close()


async def test_an_issuer_reports_and_a_follower_sees_it_hidden(net):
    issuer, owner, spammer, reader = net("issuer"), net("owner"), net("spammer"), net("reader")
    gid = await owner.create_group("alt.snak", "open", min_pow=8)
    for p in (spammer, reader):
        p.subscribe(gid)
    await spammer.post(gid, "Billige ure", "køb nu\n")
    await owner.post(gid, "Velkommen", "hej alle\n")

    with pytest.raises(SessionError, match="start your reports group"):
        await issuer.publish_report(posts=[("<x@y>", gid, "spam")])
    rgid = await issuer.start_reports(policy="Spam in alt.*", contact=issuer.my_inbox)
    assert issuer.is_issuer() and rgid == issuer.my_reports_group()
    issuer.subscribe(gid)
    spam = next(m for m in await issuer.fetch_group(gid) if m.subject == "Billige ure")
    rid = await issuer.publish_report(posts=[(spam.message_id, gid, "spam")], note="ure")
    [mine] = await issuer.my_reports()
    assert mine.message_id == rid and mine.posts[0].id == spam.message_id

    # not followed: nothing is hidden
    msgs = reader.visible(await reader.fetch_group(gid))
    assert all(m.reported is None for m in msgs)

    reader.follow_issuer(issuer.identity().key_text, "Spamjægeren")
    assert await reader.refresh_reports() == 1
    msgs = reader.visible(await reader.fetch_group(gid))
    hidden = {m.subject: m.reported for m in msgs}
    assert hidden["Velkommen"] is None
    assert hidden["Billige ure"]["reason"] == "spam" and hidden["Billige ure"]["kind"] == "post"
    assert hidden["Billige ure"]["issuer"] == issuer.identity().key_text
    assert reader.hidden_by_reports(gid) == [(hidden["Billige ure"]["label"], "spam", 1)]
    assert [i["key"] for i in reader.report_issuers() if i["yours"]] == [issuer.identity().key_text]

    # shown anyway, on this device
    reader.show_reported(spam.message_id)
    assert all(m.reported is None for m in reader.visible(await reader.fetch_group(gid)))

    # the spammer's own client never hides its own posts; a contact's are not hidden
    spammer.follow_issuer(issuer.identity().key_text)
    await spammer.refresh_reports()
    assert all(m.reported is None for m in spammer.visible(await spammer.fetch_group(gid)))
    owner.follow_issuer(issuer.identity().key_text)
    owner.add_contact(spammer.identity().key_text, "Ven")
    await owner.refresh_reports()
    assert all(m.reported is None for m in owner.visible(await owner.fetch_group(gid)))

    # the issuer withdraws its report: nothing hidden any more
    other = net("other")
    other.subscribe(gid)
    other.follow_issuer(issuer.identity().key_text)
    await other.refresh_reports()
    assert any(m.reported for m in other.visible(await other.fetch_group(gid)))
    await issuer.withdraw_report(rid)
    await other.refresh_reports()
    assert all(m.reported is None for m in other.visible(await other.fetch_group(gid)))

    # and stopping to follow an issuer is one action
    other.unfollow_issuer(issuer.identity().key_text)
    assert other.report_issuers() == []


async def test_a_reported_key_hides_all_its_posts_and_reports_reach_the_issuer(net):
    issuer, owner, spammer, reader = net("issuer"), net("owner"), net("spammer"), net("reader")
    gid = await owner.create_group("alt.marked", "open", min_pow=8)
    spammer.subscribe(gid)
    for i in range(3):
        await spammer.post(gid, f"Tilbud {i}", "køb\n")
    await issuer.start_reports()
    await issuer.publish_report(keys=[(spammer.identity().key_text, "flood", None)])
    reader.subscribe(gid)
    reader.follow_issuer(issuer.identity().key_text)
    await reader.refresh_reports()
    msgs = reader.visible(await reader.fetch_group(gid))
    assert len(msgs) == 3 and all(m.reported and m.reported["kind"] == "key" for m in msgs)

    # the report action offers the issuers you follow; the issuer can publish what it got
    targets = await reader.report_targets(msgs[0])
    who = [t for t in targets if t[2] == issuer.identity().key_text]
    assert who and who[0][0].startswith("Report issuer")
    await reader.report(msgs[0], who, note="mere af det samme")
    await issuer.fetch_group(issuer.my_inbox)
    got = [m for m in issuer.private_messages() if issuer.received_report(m)]
    assert got and issuer.received_report(got[0])[:2] == (msgs[0].message_id, gid)
    assert issuer.received_report(got[0])[2] == spammer.identity().key_text


async def test_issuers_named_by_a_hierarchy_apply_there_only(tmp_path, monkeypatch, net):
    import unseenet.hierarchies as hz
    import unseenet.known_nodes as kn
    from unseenet.client import naming
    root_pub, maint, issuer = net("root"), net("maint"), net("issuer")
    root_gid = await root_pub.create_group("unseenet.hierarchies", "channel", min_pow=8)
    list_gid = await maint.create_group("dk.liste", "channel", min_pow=8)
    await root_pub.post(root_gid, "Hierarchies", json.dumps({"v": 1, "hierarchies": [
        {"name": "dk", "policy": "governed", "maintainer": maint.identity().key_text,
         "list": list_gid}]}) + "\n")
    monkeypatch.setattr(hz, "HIERARCHIES_GROUP", root_gid)
    monkeypatch.setattr(kn, "PROJECT_KEY", root_pub.identity().key_text)

    owner, spammer = net("owner"), net("spammer")
    dk_gid = await owner.create_group("dk.snak", "open", min_pow=8)
    alt_gid = await owner.create_group("alt.snak", "open", min_pow=8)
    for g in (dk_gid, alt_gid):
        spammer.subscribe(g)
        await spammer.post(g, "Spam", "køb\n")
    await issuer.start_reports(policy="Spam i dk.*")
    await issuer.publish_report(keys=[(spammer.identity().key_text, "spam", None)])

    maint.subscribe(dk_gid)
    await naming.refresh(maint)
    with pytest.raises(SessionError, match="maintainer"):
        await naming.set_report_issuers(owner, "dk", [issuer.identity().key_text])
    assert await naming.set_report_issuers(maint, "dk", [issuer.identity().key_text]) == "dk"

    reader = net("reader")
    for g in (dk_gid, alt_gid):
        reader.subscribe(g)
    await naming.refresh(reader)
    assert reader.hierarchy_issuers(dk_gid) == {issuer.identity().key_text: "dk"}
    await reader.refresh_reports()
    dk = reader.visible(await reader.fetch_group(dk_gid))
    alt = reader.visible(await reader.fetch_group(alt_gid))
    assert dk[0].reported and alt[0].reported is None          # dk.* only
    [entry] = reader.report_issuers()
    assert entry["hierarchies"] == ["dk"] and entry["on"] and not entry["yours"]

    # the reader turns the hierarchy's issuer off - and on again by following it
    reader.unfollow_issuer(issuer.identity().key_text)
    assert reader.report_issuers()[0]["on"] is False
    assert reader.visible(await reader.fetch_group(dk_gid))[0].reported is None
    reader.follow_issuer(issuer.identity().key_text)
    assert reader.visible(await reader.fetch_group(alt_gid))[0].reported   # now everywhere
    # the choice follows the identity (UN-RFC 0044)
    from unseenet.client.session.state import SETTINGS
    assert "report_issuers" in SETTINGS


async def test_a_groups_owner_names_issuers_for_its_group(net):
    """Section 7.5 (#644): in alt.*, which nobody governs, a group's owner names the
    issuers its readers follow by default - for that group only, and readers can
    turn them off."""
    from unseenet.core import crypto
    from unseenet.core import reports as rpt
    from unseenet.core.groups import make_manifest
    bot, issuer, spammer, reader = net("bot"), net("issuer"), net("spammer"), net("reader")
    await issuer.start_reports()
    key = issuer.identity().key_text
    news = await bot.create_group("alt.space.nasa", "channel", min_pow=8, comments="open",
                                  extra={"report_issuers": [key]})
    other = await bot.create_group("alt.snak", "open", min_pow=8)
    root = await bot.post(news, "Mars", "billede\n")
    for g in (news, other):
        spammer.subscribe(g)
        await spammer.fetch_group(g)
    await spammer.post(news, "Re: Mars", "køb ure\n", references=[root])
    await spammer.post(other, "Ure", "køb ure\n")
    await issuer.publish_report(keys=[(spammer.identity().key_text, "spam", None)])

    for g in (news, other):
        reader.subscribe(g)
        await reader.fetch_group(g)
    assert reader.named_issuers(news) == {key: "group"} and reader.named_issuers(other) == {}
    await reader.refresh_reports()
    hidden = {m.group: bool(m.reported) for g in (news, other)
              for m in reader.visible(await reader.fetch_group(g)) if m.author_key == spammer.identity().key_text}
    assert hidden == {news: True, other: False}                 # for that group only
    [entry] = reader.report_issuers()
    assert entry["groups"] == [news] and entry["hierarchies"] == [] and entry["on"]
    reader.unfollow_issuer(key)                                  # the reader decides
    assert not any(m.reported for m in reader.visible(await reader.fetch_group(news)))

    owner = crypto.Identity.generate()
    for bad, why in (([], "1 to 16"), ([key, key], "twice"), (["nonsense"], "")):
        with pytest.raises((ValueError, crypto.CryptoError)):
            make_manifest(owner, "alt.x", "open", pow_bits=8, extra={"report_issuers": bad})
    with pytest.raises(ValueError, match="inbox"):
        make_manifest(owner, "kontakt", "inbox", pow_bits=8, extra={"report_issuers": [key]})
    assert rpt.group_issuers({"type": "open", "report_issuers": [key]}) == [key]
