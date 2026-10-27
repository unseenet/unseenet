"""#341, UN-RFC 0047: team inboxes - up to 16 readers with team keys, the team box,
nodes' checks, adding a reader by invitation, reading, replying on the inbox's behalf,
and removing a reader. The owner key is needed only to change who reads."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session, SessionError
from unseenet.core import crypto
from unseenet.core.article import ArticleError
from unseenet.core.groups import (TEAM_SLOTS, Manifest, inbox_article, make_manifest, open_inbox_article,
                                  open_team_box, team_box)
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}
BITS = 8


def team_manifest(owner, readers, **kw):
    return make_manifest(owner, "operator", "inbox", pow_bits=BITS,
                         extra={"readers": [r.key_text for r in readers], **kw})


# --- the manifest and the box (sections 3, 4) ------------------------------------------

def test_the_manifest_lists_readers():
    owner, r1, r2 = (crypto.Identity.generate() for _ in range(3))
    m = Manifest.from_article(team_manifest(owner, [r1, r2], team_name="Unseenet (operator)"))
    assert m.raw["readers"] == [r1.key_text, r2.key_text]
    for readers, why in (([], "1 to 16"), ([r1, r1], "twice"), ([owner], "owner"),
                         ([crypto.Identity.generate() for _ in range(17)], "1 to 16")):
        with pytest.raises(ValueError, match=why):
            team_manifest(owner, readers)
    with pytest.raises(ValueError, match="64"):
        team_manifest(owner, [r1], team_name="x" * 65)
    with pytest.raises(ValueError, match="inboxes"):
        make_manifest(owner, "dk.snak", "open", pow_bits=BITS, extra={"readers": [r1.key_text]})


def test_a_team_box_opens_for_each_reader_and_shows_nothing():
    readers = [crypto.Identity.generate() for _ in range(3)]
    other = crypto.Identity.generate()
    box = team_box("operator@x", [r.public_key for r in readers], b"hemmeligt")
    assert len(box) == 1 + TEAM_SLOTS * 80 + 24 + len(b"hemmeligt") + 16      # always 16 slots
    for r in readers:
        assert open_team_box("operator@x", box, r) == b"hemmeligt"
    with pytest.raises(crypto.CryptoError):
        open_team_box("operator@x", box, other)
    with pytest.raises(Exception):                                 # bound to its group
        open_team_box("operator@y", box, readers[0])


def test_an_article_to_a_team_inbox():
    owner, r1, writer = (crypto.Identity.generate() for _ in range(3))
    gid = team_manifest(owner, [r1]).group
    art = inbox_article(gid, owner.public_key, from_name="Sonia", subject="Spam", body="se her\n",
                        sender=writer, readers=[r1.public_key], pow_bits=BITS)
    assert art["Encrypted"] == "teambox"
    inner, sender = open_inbox_article(art, r1)
    assert inner.body == "se her\n" and sender == writer.public_key
    with pytest.raises(ArticleError):
        open_inbox_article(art, owner)                             # the owner is not a reader


def test_nodes_take_team_boxes_in_team_inboxes_only():
    owner, r1, writer = (crypto.Identity.generate() for _ in range(3))
    n = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    m = team_manifest(owner, [r1])
    n.accept(m.to_bytes())
    sealed = inbox_article(m.group, owner.public_key, from_name="x", subject="s", body="b\n",
                           sender=writer, pow_bits=BITS)
    with pytest.raises(ArticleError, match="team boxes only"):      # an outdated client fails
        n.accept(sealed.to_bytes())
    n.accept(inbox_article(m.group, owner.public_key, from_name="x", subject="s", body="b\n",
                           sender=writer, readers=[r1.public_key], pow_bits=BITS).to_bytes())
    plain = make_manifest(owner, "kontakt", "inbox", pow_bits=BITS)
    n.accept(plain.to_bytes())
    with pytest.raises(ArticleError, match="team inbox"):
        n.accept(inbox_article(plain.group, owner.public_key, from_name="x", subject="s", body="b\n",
                               sender=writer, readers=[r1.public_key], pow_bits=BITS).to_bytes())


# --- clients (sections 6-9) ------------------------------------------------------------

@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
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


async def test_a_team_inbox_from_start_to_end(net):
    project, andreas, helper, sonia = net("project"), net("andreas"), net("helper"), net("sonia")
    for p in (andreas, helper, sonia):
        await p.ensure_inbox()
    gid = await project.create_group("operator", "inbox")
    # the owner adds two readers: each gets a team key in their own inbox
    k1 = await project.add_team_reader(gid, andreas.identity().key_text, "Unseenet (operator)")
    await project.add_team_reader(gid, helper.identity().key_text)
    assert project.team_key(gid) is None                            # the owner keeps none
    with pytest.raises(SessionError, match="owner"):
        await andreas.add_team_reader(gid, sonia.identity().key_text)

    await andreas.fetch_group(andreas.my_inbox)
    [inv] = [m for m in andreas.private_messages() if andreas.team_invitation(m)]
    assert f"#{gid}" in inv.body and inv.to_dict()["team_invite"] == {"group": gid}
    assert await andreas.accept_team_invitation(inv) == gid
    assert andreas.team_key(gid).key_text == k1 and gid in andreas.data["subscribed"]
    assert andreas.group_label(gid) == "Unseenet (operator) (team inbox)"
    assert andreas.group_info(gid).to_dict()["team"] == {"name": "Unseenet (operator)", "reader": True}
    await helper.fetch_group(helper.my_inbox)
    await helper.accept_team_invitation(next(m for m in helper.private_messages() if helper.team_invitation(m)))

    # a forged invitation is not accepted
    forged = crypto.Identity.generate()
    import base64
    await sonia.send_private(andreas.my_inbox, "Læs med", f"#{gid}\n", owner_key=andreas.identity().public_key,
                             extra=[("Team-Inbox", gid), ("Team-Key", base64.b64encode(forged.seed).decode())])
    await andreas.fetch_group(andreas.my_inbox)
    fake = next(m for m in andreas.private_messages() if andreas.team_invitation(m) and m.sender_key == sonia.identity().key_text)
    with pytest.raises(SessionError, match="owner"):
        await andreas.accept_team_invitation(fake)

    # someone writes to the team inbox: both readers read it, the owner cannot
    await sonia.send_private(gid, "Spam i alt.snak", "se her\n", owner_key=project.identity().public_key)
    for reader in (andreas, helper):
        [m] = [m for m in await reader.fetch_group(gid) if m.subject == "Spam i alt.snak"]
        assert m.readable and m.sender_key == sonia.identity().key_text
    project.subscribe(gid)
    assert not any(m.readable for m in await project.fetch_group(gid))

    # andreas answers on the inbox's behalf: sonia sees the team, verified, not a person
    [m] = [m for m in await andreas.fetch_group(gid) if m.subject == "Spam i alt.snak"]
    await andreas.send_private(andreas.reply_target(m), "Re: Spam i alt.snak", "Tak, vi ser på det\n",
                               references=[m.message_id], as_team=gid)
    await sonia.fetch_group(sonia.my_inbox)
    [answer] = [x for x in sonia.private_messages() if x.subject.startswith("Re: Spam")]
    assert sonia.team_sender(answer) == {"group": gid, "name": "Unseenet (operator)", "verified": True}
    assert answer.sender_key == k1 and answer.reply_inbox == gid
    assert "andreas" not in (answer.from_name or "").lower()          # who wrote it stays hidden

    # the owner removes andreas: new messages are not for him, his replies no longer verify
    await project.remove_team_reader(gid, k1)
    await sonia.send_private(gid, "Igen", "endnu en\n", owner_key=project.identity().public_key)
    seen = {m.subject: m.readable for m in await andreas.fetch_group(gid)}
    assert seen == {"Spam i alt.snak": True, "(a message for the team's readers)": False}
    assert {m.subject: m.readable for m in await helper.fetch_group(gid)}.get("Igen") is True
    assert [t["reader"] for t in andreas.team_inboxes()] == [False]
    sonia.group_entry(gid).pop("manifest", None)
    await sonia.check_team_senders()
    assert sonia.team_sender(answer)["verified"] is False
    with pytest.raises(SessionError, match="not a reader"):
        await project.remove_team_reader(gid, k1)
    andreas.forget_team_key(gid)
    assert andreas.team_inboxes() == []


async def test_team_inboxes_through_the_local_api_and_the_command_line(net, capsys):
    import json
    from argparse import Namespace

    from unseenet import cli
    from unseenet.client.localapi import LocalAPI
    from unseenet.client.localapi import server as srv
    project, andreas, sonia = net("project"), net("andreas"), net("sonia")
    for p in (andreas, sonia):
        await p.ensure_inbox()
    gid = await project.create_group("operator", "inbox")
    papi, aapi = LocalAPI(session=project), LocalAPI(session=andreas)
    got = await papi.change_team_readers({"group": gid, "add": andreas.identity().key_text,
                                          "team_name": "Unseenet (operator)"})
    assert len(got["readers"]) == 1 and got["team_name"] == "Unseenet (operator)"
    await andreas.fetch_group(andreas.my_inbox)
    inv = next(m for m in andreas.private_messages() if andreas.team_invitation(m))
    assert (await aapi.accept_team({"id": inv.message_id}))["group"] == gid
    assert aapi.teams()["teams"] == [{"group": gid, "name": "Unseenet (operator)", "reader": True}]

    await sonia.send_private(gid, "Hjælp", "min node\n", owner_key=project.identity().public_key)
    await andreas.fetch_group(gid)
    m = next(x for x in andreas.cache[gid].values() if x.subject == "Hjælp")

    class App:
        def __init__(self, s):
            self.session = s
    await cli.c_team(App(andreas), Namespace(json=True, identity=None, what="reply", group=gid,
                                             msgid=m.message_id, text="Vi ser på det"))
    assert json.loads(capsys.readouterr().out)["id"].startswith("<")
    await sonia.fetch_group(sonia.my_inbox)
    rows = LocalAPI(session=sonia)
    answer = next(x for x in sonia.private_messages() if x.subject == "Re: Hjælp")
    row = rows._row(sonia, answer, 0, set(), [], set())
    assert row["who"] == "Unseenet (operator)" and row["team"]["verified"] is True
    await cli.c_team(App(project), Namespace(json=True, identity=None, what="readers", group=gid))
    assert len(json.loads(capsys.readouterr().out)["readers"]) == 1
    routes = {(m, p) for m, p, _ in srv.ROUTES}
    assert {("GET", "/api/teams"), ("POST", "/api/teams/accept"), ("POST", "/api/teams/forget"),
            ("GET", "/api/teams/readers"), ("POST", "/api/teams/readers")} <= routes


async def test_reports_to_an_issuer_land_in_its_team_inbox(net):
    """An issuer whose contact is a team inbox: reports to it land there, so the people
    who read the team inbox see them in their everyday client (27 Oct)."""
    project, issuer, andreas, sonia, owner, spammer = (net(n) for n in
                                                      ("project", "issuer", "andreas", "sonia", "owner", "spammer"))
    for p in (andreas, sonia, owner):
        await p.ensure_inbox()
    team = await project.create_group("contact", "inbox")
    await project.add_team_reader(team, andreas.identity().key_text, "Unseenet (operator)")
    await andreas.fetch_group(andreas.my_inbox)
    await andreas.accept_team_invitation(next(m for m in andreas.private_messages() if andreas.team_invitation(m)))
    await issuer.start_reports(contact=team)

    gid = await owner.create_group("alt.snak", "open", min_pow=8)
    spammer.subscribe(gid)
    await spammer.fetch_group(gid)
    await spammer.post(gid, "Ure", "køb\n")
    sonia.subscribe(gid)
    sonia.follow_issuer(issuer.identity().key_text, "Projektet")
    await sonia.refresh_reports()
    [post] = await sonia.fetch_group(gid)
    targets = await sonia.report_targets(post)
    [(who, inbox, key)] = [t for t in targets if t[0].startswith("Report issuer")]
    assert inbox == team and key == project.identity().key_text          # its team inbox
    await sonia.report(post, [(who, inbox, key)], "spam igen", reason="spam")

    await andreas.fetch_group(team)
    [r] = andreas.reports_sent_to_you()
    assert andreas.received_report(r)[:2] == (post.message_id, gid) and r.group == team
    from unseenet.client.localapi import LocalAPI
    row = LocalAPI(session=andreas)._row(andreas, r, 0, set(), [], set())
    assert row["report"] == {"id": post.message_id, "group": gid,
                             "author_key": spammer.identity().key_text, "reason": "spam"}


@pytest.mark.parametrize("name", ["contact", "operator", "inbox"])
def test_any_inbox_takes_sealed_posts_from_unripe_one_time_keys(ripening_rules, name):
    """Found 27 Oct: a report to contact@ (a team inbox) was refused, "no Key-Ripening
    header" - nodes knew sealed posts by the name inbox@ only, not by the type."""
    from unseenet.core import ripening as rp
    owner, writer, reader = (crypto.Identity.generate() for _ in range(3))
    n = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), min_ripe=None))
    extra = None if name == "inbox" else {"readers": [reader.key_text]}
    m = make_manifest(owner, name, "inbox", pow_bits=BITS + 8, extra=extra)
    n.accept(m.to_bytes())                                 # the owner's key is not what is tested
    n.config.min_ripe = rp.DEFAULT_MIN_RIPE                 # from here: the node's real rule
    bits = rp.required_pow(BITS, m and 0, None, allow_unripe=True)
    art = inbox_article(m.group, owner.public_key, from_name="x", subject="Report", body="spam\n",
                        sender=writer, readers=[reader.public_key] if extra else None, pow_bits=bits)
    n.accept(art.to_bytes())                               # no ripening asked of a one-time key
