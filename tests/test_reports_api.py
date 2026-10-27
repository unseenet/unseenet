"""UN-RFC 0045 through the local client API and the command line (#122, CLI parity #578)."""

import json
from argparse import Namespace

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
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0),
                                    blobs={"max_size": 1 << 20, "encrypted": True}))   # pictures in reports
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


async def test_reports_through_the_local_api(net):
    from unseenet.client.localapi import LocalAPI
    from unseenet.client.localapi import server as srv
    issuer, owner, spammer, me = net("issuer"), net("owner"), net("spammer"), net("me")
    api, iapi = LocalAPI(session=me), LocalAPI(session=issuer)
    gid = await owner.create_group("alt.snak", "open", min_pow=8)
    spammer.subscribe(gid)
    await spammer.post(gid, "Ure", "køb\n")
    assert iapi.reports()["mine"] is None and "spam" in iapi.reports()["reasons"]
    mine = (await iapi.start_reports({"policy": "Spam", "automatic": True}))["mine"]
    assert mine["policy"] == "Spam" and mine["automatic"] is True
    assert iapi.settings()["report_issuer"] is True and api.settings()["report_issuer"] is False
    spam = next(m for m in await issuer.fetch_group(gid) if m.subject == "Ure")
    job = (await iapi.publish_report({"posts": [{"id": spam.message_id, "group": gid}],
                                      "keys": [{"key": spammer.identity().key_text, "days": 30}]}))["job"]
    assert job                                                  # a job: postage takes a while
    import asyncio
    for _ in range(100):
        if (await iapi.my_reports())["reports"]:
            break
        await asyncio.sleep(0.05)
    [r] = (await iapi.my_reports())["reports"]
    rid = r["id"]
    assert r["keys"][0]["key"] == spammer.identity().key_text
    with pytest.raises(SessionError, match="days"):
        await iapi.publish_report({"keys": [{"key": spammer.identity().key_text, "days": 400}]})

    me.subscribe(gid)
    got = await api.follow_issuer({"key": issuer.identity().key_text, "label": "Jægeren"})
    assert got["issuers"][0]["label"] == "Jægeren" and got["issuers"][0]["on"]
    [shown] = [m.to_dict() for m in me.visible(await me.fetch_group(gid))]
    assert shown["reported"]["reason"] == "spam" and shown["reported"]["automatic"] is True
    assert shown["reported"]["label"] == "Jægeren"                   # the name you gave it
    api.show_reported(gid, {"id": spam.message_id})
    assert me.visible(await me.fetch_group(gid))[0].to_dict()["reported"] is None
    await api.follow_issuer({"key": issuer.identity().key_text, "on": False})
    assert api.reports()["issuers"] == []
    await iapi.withdraw_report({"id": rid})
    assert (await iapi.my_reports())["reports"] == []
    routes = {(m, p) for m, p, _ in srv.ROUTES}
    assert {("GET", "/api/reports"), ("POST", "/api/reports/follow"), ("POST", "/api/reports/publish"),
            ("POST", "/api/reports/start"), ("GET", "/api/reports/mine"), ("POST", "/api/reports/withdraw"),
            ("GET", "/api/reports/received"), ("POST", "/api/reports/hierarchy"),
            ("POST", "/api/reports/refresh"), ("POST", "/api/groups/{gid}/show")} <= routes


async def test_reports_from_the_command_line(net, capsys):
    from unseenet import cli
    issuer, owner, spammer = net("issuer"), net("owner"), net("spammer")
    gid = await owner.create_group("alt.snak", "open", min_pow=8)
    spammer.subscribe(gid)
    await spammer.post(gid, "Ure", "køb\n")

    class App:                                          # the CLI's App around a session
        def __init__(self, s):
            self.session = s

    def ns(**kw):
        return Namespace(json=True, identity=None, **kw)

    def out():
        return json.loads(capsys.readouterr().out)

    i = App(issuer)
    await cli.c_reports(i, ns(what="start", policy="Spam", contact="", automatic=False))
    assert out()["group"] == issuer.my_reports_group()
    spam = next(m for m in await issuer.fetch_group(gid) if m.subject == "Ure")
    await cli.c_reports(i, ns(what="publish", post=[[gid, spam.message_id]], key=[],
                              reason="spam", days=365, note="ure"))
    rid = out()["id"]
    await cli.c_reports(i, ns(what="mine"))
    assert [r["id"] for r in out()] == [rid]

    reader = App(net("reader"))
    reader.session.subscribe(gid)
    await cli.c_reports(reader, ns(what="follow", key=issuer.identity().key_text, label=""))
    assert out()["read"] == 1
    await cli.c_reports(reader, ns(what="hidden", group=gid))
    [row] = out()
    assert row["id"] == spam.message_id and row["reason"] == "spam"
    await cli.c_reports(reader, ns(what="issuers"))
    assert out()[0]["yours"] is True
    await cli.c_reports(i, ns(what="withdraw", msgid=rid))
    assert out()["id"] == rid


async def test_a_report_in_markdown_with_a_picture_and_a_reason(net):
    """gui#70: a report's note is Markdown, may carry a screenshot or a document, and says
    why; the receiver still finds the post, and an issuer publishes it with that reason."""
    import base64
    import io

    from unseenet.client.localapi import LocalAPI
    from unseenet.client.session import REPORT_TYPE, is_report_type
    PIL = pytest.importorskip("PIL.Image")
    issuer, owner, troll, me = net("issuer"), net("owner"), net("troll"), net("me")
    await issuer.start_reports()
    gid = await owner.create_group("alt.snak", "open", min_pow=8)
    troll.subscribe(gid)
    await troll.post(gid, "Trussel", "jeg ved hvor du bor\n")
    me.subscribe(gid)
    me.follow_issuer(issuer.identity().key_text)
    api = LocalAPI(session=me)
    post = next(m for m in await me.fetch_group(gid) if m.subject == "Trussel")
    got = await api.report_targets(gid, post.message_id)
    assert [r["id"] for r in got["reasons"]] == ["spam", "illegal", "threats", "other"]
    to_issuer = [t["i"] for t in got["targets"] if t["who"].startswith("Report issuer")]
    buf = io.BytesIO()
    PIL.new("RGB", (8, 8), "red").save(buf, "PNG")
    started = await api.report(gid, {"id": post.message_id, "targets": to_issuer, "reason": "threats",
                                  "note": "Se **skærmbilledet** - politiet er kontaktet.",
                                  "files": [{"name": "skaerm.png", "data": base64.b64encode(buf.getvalue()).decode(),
                                             "alt": "Skærmbillede af truslen"}]})
    assert started["targets"] == 1 and started["job"]
    import asyncio
    for _ in range(200):                                       # the job, in the background
        if not api._job:
            await asyncio.sleep(0.05)
            if not api._job:
                break
        await asyncio.sleep(0.05)
    await issuer.fetch_group(issuer.my_inbox)
    [r] = [m for m in issuer.private_messages() if issuer.reported_post(m)]
    assert is_report_type(r.content_type) and r.content_type.startswith("text/markdown")
    assert "**skærmbilledet**" in r.body and len(r.attachments) == 1
    assert issuer.received_report(r) == (post.message_id, gid, troll.identity().key_text, "other")
    assert is_report_type(REPORT_TYPE + "; charset=utf-8")      # the plain reports of before too
    with pytest.raises(SessionError, match="reason"):
        await me.report(post, [("x", me.my_inbox, me.identity().key_text)], reason="boring")


def test_a_hierarchy_names_its_contact():
    """#647, UN-RFC 0018 section 4.1: where reports to a maintainer go."""
    from unseenet import hierarchies as hz
    from unseenet.core import crypto
    m = crypto.Identity.generate()
    base = {"name": "dk", "policy": "governed", "maintainer": m.key_text,
            "list": f"dk.liste@{m.fingerprint}"}
    assert hz._entry({**base, "contact": f"contact@{m.fingerprint}"}).contact == f"contact@{m.fingerprint}"
    assert hz._entry({**base, "contact": "not a group"}).contact == ""
    assert hz._entry(base).contact == ""
    v, root = hz.builtin_root_list()
    assert root["unseenet"].contact == "contact@ph5fc5hop5232qsz"


async def test_report_targets_without_an_inbox_are_left_out(net):
    owner, reader, nobody = net("owner"), net("reader"), net("nobody")
    await reader.ensure_inbox()
    await owner.ensure_inbox()
    gid = await owner.create_group("alt.snak", "open", min_pow=8,
                                   moderators=[nobody.identity().key_text])   # has no inbox
    await owner.post(gid, "Hej", "x\n")
    reader.subscribe(gid)
    [m] = await reader.fetch_group(gid)
    targets = await reader.report_targets(m)
    assert [t[2] for t in targets] == [owner.identity().key_text]
    assert await reader.report(m, targets, "test") == 1


async def test_a_groups_issuers_and_team_name_are_edited(net, capsys):
    """What Edit group needs (27 Oct): the issuers a group names, and a team inbox's name."""
    from unseenet import cli
    from unseenet.client.localapi import LocalAPI
    owner, issuer = net("owner"), net("issuer")
    api = LocalAPI(session=owner)
    gid = await owner.create_group("alt.snak", "open", min_pow=8)
    key = issuer.identity().key_text
    await api.group_settings(gid, {"report_issuers": [key]})
    assert api.group(gid)["group"]["report_issuers"] == [{"key": key, "label": owner.issuer_label(key)}]
    await api.group_settings(gid, {"report_issuers": []})
    assert owner.manifest_data(gid).get("report_issuers") is None

    class App:
        def __init__(self, s):
            self.session = s
    ns = dict(json=True, identity=None, group=gid, add_poster=None, remove_poster=None,
              add_moderator=None, remove_moderator=None, ban=None, unban=None, reason=None,
              add_report_issuer=[key], remove_report_issuer=None, team_name=None)
    from argparse import Namespace
    import unseenet.cli.groups as cg
    base = {k: None for k in ("title", "description", "min_pow", "retention_days", "view", "kinds",
                              "rules", "comments", "comment_days", "attachments", "types", "max_pins",
                              "reactions", "max_pages", "home", "index")}
    await cli.c_group_edit(App(owner), Namespace(**{**base, **ns}))
    assert owner.manifest_data(gid)["report_issuers"] == [key]
    inbox = await owner.create_group("kontakt", "inbox")
    await api.group_settings(inbox, {"team_name": "Snak (ejer)"})
    assert api.group(inbox)["group"]["team_name"] == "Snak (ejer)"
    assert cg


async def test_an_issuer_as_a_separate_identity_and_copied_to_a_colleague(net):
    """For everyone, not only the project (27 Oct): become an issuer as a separate
    identity beside yours; copy it to a colleague's vault (UN-RFC 0050), where it is
    found to be an issuer by itself and never becomes the one in use."""
    from unseenet.client.localapi import LocalAPI
    from unseenet.core import copying as cp
    me, colleague = net("me"), net("colleague")
    api = LocalAPI(session=me)
    got = await api.start_reports({"policy": "Spam i alt.*", "separate": {"name": "reports", "display": "Alt spam"}})
    assert got["mine"]["identity"] == "reports" and got["mine"]["label"] != "you"
    assert me.default_identity_name() == "me" and me.issuer_names() == ["reports"]
    with pytest.raises(SessionError, match="already"):
        await api.start_reports({"separate": {"name": "reports"}})

    colleague.data.pop("default_identity", None)        # a vault that never chose one
    added = cp.merge_payload(colleague.data, cp.build_payload(me.data, ["reports"], False))
    assert added == ["reports"] and colleague.default_identity_name() == "colleague"
    assert colleague.issuer_names() == []
    assert await colleague.discover_issuers() == ["reports"]          # from the network
    assert colleague.issuer_names() == ["reports"] and colleague.issuer_for() == "reports"
    assert colleague.default_identity_name() == "colleague"           # still you
