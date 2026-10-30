"""tools/project: the owner's scripts set up groups and the registrar, end to end."""

import getpass
import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import unseenet.client.session as sess
import unseenet.names as nm
from unseenet.client.session import Session
from unseenet.core import crypto
from unseenet.core.groups import manifest_article
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig
from unseenet.nntp import Client
from unseenet.registrar import Registrar

TOOLS = Path(__file__).resolve().parent.parent / "tools" / "project"
KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    # sites: the project groups include one (unseenet.help.guide), as the project nodes carry
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0), sites="accept"))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    monkeypatch.syspath_prepend(str(TOOLS))
    owner_mod = importlib.import_module("_owner")
    project, poster = crypto.Identity.generate(), crypto.Identity.generate()
    vault_path = tmp_path / "owner.vault"
    v = Vault.open(vault_path, "pw", **KDF)
    v.data["identities"]["project"] = {"seed": project.seed.hex(), "display": "Unseenet project"}
    v.data["github_poster"] = {"seed": poster.seed.hex(), "key": poster.key_text}
    v.save()

    real_post_everywhere = owner_mod.post_everywhere

    async def post_local(raws, addresses=None, session=None, others=()):
        # the tools' real posting, through Session (#287), to the local node
        took = await real_post_everywhere(raws, [addr], session=session, others=others)
        assert took == 1, "the local node did not take every article"
        return took

    monkeypatch.setattr(owner_mod, "VAULT", vault_path)
    monkeypatch.setattr(owner_mod, "POW_BITS", 8)
    monkeypatch.setattr(owner_mod, "PROJECT_KEY", project.key_text)
    monkeypatch.setattr(owner_mod, "post_everywhere", post_local)

    async def fetch_local(group_ids, addresses=None):
        c = await Client.connect(addr)
        got = await owner_mod.read_manifests(c, group_ids)
        await c.quit()
        return got

    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "pw")
    names_group = f"unseenet.names@{project.fingerprint}"
    monkeypatch.setattr(nm, "NAMES_GROUP", names_group)
    monkeypatch.setattr(nm, "CLAIM_POW", 12)             # 24 bits take a minute of CPU

    def run_tool(name, *argv):
        sys.modules.pop(name, None)
        mod = importlib.import_module(name)
        monkeypatch.setattr(mod, "open_owner_session",
                            lambda: owner_mod.open_owner_session(vault_path, project.key_text))
        monkeypatch.setattr(mod, "post_everywhere", post_local)
        if hasattr(mod, "fetch_manifests"):
            monkeypatch.setattr(mod, "fetch_manifests", fetch_local)
        if hasattr(mod, "NAMES_GROUP"):
            monkeypatch.setattr(mod, "NAMES_GROUP", names_group)
        monkeypatch.setattr(sys, "argv", [name, *argv])
        return mod.main()

    yield {"addr": addr, "project": project, "vault": vault_path, "run": run_tool,
           "names_group": names_group}
    server.close()


async def test_owner_scripts_set_up_a_working_registrar(setup, tmp_path):
    run, addr = setup["run"], setup["addr"]
    replica_key = crypto.Identity.generate()

    # 1. the project's groups; a second run creates nothing
    with pytest.raises(SystemExit, match="registrar_poster"):
        await run("create_groups")                         # names needs a registrar key first
    v = Vault.open(setup["vault"], "pw")
    v.data["registrar_poster"] = {"seed": replica_key.seed.hex(), "key": replica_key.key_text}
    v.save()
    await run("create_groups")
    v = Vault.open(setup["vault"], "pw")
    owned = {g for g, e in v.data["groups"].items() if e.get("owner")}
    assert setup["names_group"] in owned and len(owned) == 45     # + 23 news bot channels
    news = v.data["groups"][f"alt.news.wikipedia@{setup['project'].fingerprint}"]["manifest"]
    assert (news["type"], news["comments"], news["comment_days"]) == ("channel", "open", 14)
    assert news["posters"] == ["ed25519:2xx732vxtge5ficz7ihbi75uctegsmyzc5bmllwett62etjtfuza"]
    assert "comments" not in v.data["groups"][f"unseenet.announce@{setup['project'].fingerprint}"]["manifest"]
    nodes = f"unseenet.nodes@{setup['project'].fingerprint}"
    talk = f"unseenet@{setup['project'].fingerprint}"
    assert v.data["groups"][nodes]["manifest"]["view"] == "data"
    assert "view" not in v.data["groups"][talk]["manifest"]          # threads, the default
    chat = v.data["groups"][f"unseenet.chat@{setup['project'].fingerprint}"]["manifest"]
    assert chat["portals"][0]["source"] == "#unseenet:unseenet.org"
    assert chat["kinds"] == ["chat"] and chat["view"] == "chat"
    assert "portals" not in v.data["groups"][talk]["manifest"]        # none, left out
    await run("create_groups")
    assert len({g for g, e in Vault.open(setup["vault"], "pw").data["groups"].items()
                if e.get("owner")}) == 45

    async def as_published_before(gid, change):
        """Put a newer manifest on the node, as an older script would have made it."""
        v = Vault.open(setup["vault"], "pw")
        data = dict(v.data["groups"][gid]["manifest"])
        change(data)
        data["serial"] += 1
        c = await Client.connect(addr)
        code, text = await c.post(manifest_article(setup["project"], gid, data, pow_bits=8).to_bytes())
        await c.quit()
        assert code == 240, text
        v.data["groups"][gid]["manifest"] = data
        v.save()

    # a data group made before views existed gets a new manifest; others are left alone
    await as_published_before(nodes, lambda d: d.pop("view"))
    await run("create_groups")
    v = Vault.open(setup["vault"], "pw")
    assert v.data["groups"][nodes]["manifest"]["view"] == "data"
    assert v.data["groups"][nodes]["manifest"]["serial"] == 3
    assert v.data["groups"][talk]["manifest"]["serial"] == 1

    # a group made before the list had a charter gets one; posters and the rest are kept
    kept = [crypto.Identity.generate().key_text]

    def without_charter(d):
        for k in ("title", "description", "charter"):
            d.pop(k, None)
        d["min_pow"], d["posters"] = 0, kept
    await as_published_before(talk, without_charter)
    await run("create_groups")
    new = Vault.open(setup["vault"], "pw").data["groups"][talk]["manifest"]
    assert new["serial"] == 3 and new["charter"].startswith("The place to talk")
    assert new["min_pow"] == 20 and new["posters"] == kept and "view" not in new
    await run("create_groups")
    v = Vault.open(setup["vault"], "pw")
    assert v.data["groups"][talk]["manifest"]["serial"] == 3
    assert v.data["groups"][nodes]["manifest"]["serial"] == 3

    # the nodes, not the vault, say what a group's manifest is now
    test = f"unseenet.test@{setup['project'].fingerprint}"
    del v.data["groups"][test]["manifest"]                    # never kept by the vault
    stale = dict(v.data["groups"][talk]["manifest"], serial=1)
    stale.pop("charter")
    v.data["groups"][talk]["manifest"] = stale
    v.save()                                                   # an out-of-date vault
    await run("create_groups")
    v = Vault.open(setup["vault"], "pw")
    assert v.data["groups"][test]["manifest"]["serial"] == 1  # read from the node, now kept
    assert v.data["groups"][talk]["manifest"]["serial"] == 3  # the node's, not a new one

    # 2. wire up the registrar: claim inbox and manifest with `claims`
    await run("setup_registrar")
    v = Vault.open(setup["vault"], "pw")
    inbox = crypto.Identity.from_seed(bytes.fromhex(v.data["registrar_inbox"]["seed"]))
    manifest = v.data["groups"][setup["names_group"]]["manifest"]
    assert manifest["serial"] == 2 and manifest["claims"] == f"inbox@{inbox.fingerprint}"
    assert manifest["posters"] == [replica_key.key_text]

    # 3. a replica with those keys handles a claim
    rv = Vault.open(tmp_path / "replica.vault", "pw", **KDF)
    rv.data["identities"] = {"registrar": {"seed": replica_key.seed.hex(), "display": "r"},
                             "inbox": {"seed": inbox.seed.hex(), "display": "r"}}
    rv.data["default_identity"] = "registrar"
    rs = Session(rv, status=lambda *_: None)
    rs.add_node(addr)
    clock = [datetime.now(timezone.utc)]
    reg = Registrar(rs, setup["names_group"], tlds=lambda: {"com"}, dns_txt=lambda n: [],
                    now=lambda: clock[0])
    await reg.run_once()
    assert reg.claims_group == manifest["claims"]

    alice = Session(Vault.open(tmp_path / "alice.vault", "pw", **KDF), status=lambda *_: None)
    alice.new_identity("alice", "Alice")
    alice.add_node(addr)
    await alice.ensure_inbox()
    await alice.send_private(manifest["claims"], "claim", nm.make_claim("claim", "lorensen"),
                             owner_key=inbox.public_key, content_type="application/json")
    clock[0] += timedelta(minutes=15)
    await reg.run_once()
    clock[0] += timedelta(hours=1)
    await reg.run_once()
    (cert,) = [c for c in reg.certs if c.name == "lorensen"]
    assert cert.key == alice.identity().key_text and cert.registrar == replica_key.key_text

    # 4. adding a second replica and removing the first
    second = crypto.Identity.generate()
    await run("setup_registrar", "--add", second.key_text, "--remove", replica_key.key_text)
    manifest = Vault.open(setup["vault"], "pw").data["groups"][setup["names_group"]]["manifest"]
    assert manifest["serial"] == 3 and manifest["posters"] == [second.key_text]
    await alice.close(), await rs.close()


async def test_claim_inbox_demands_postage(setup):
    """The nodes enforce the postage on claims through the inbox's min_pow."""
    run = setup["run"]
    v = Vault.open(setup["vault"], "pw")
    k = crypto.Identity.generate()
    v.data["registrar_poster"] = {"seed": k.seed.hex(), "key": k.key_text}
    v.save()
    await run("create_groups")
    await run("setup_registrar")
    v = Vault.open(setup["vault"], "pw")
    inbox = crypto.Identity.from_seed(bytes.fromhex(v.data["registrar_inbox"]["seed"]))
    from unseenet.core.groups import inbox_article
    cheap = inbox_article(f"inbox@{inbox.fingerprint}", inbox.public_key, from_name="x",
                          subject="claim", body=nm.make_claim("claim", "cheap"), pow_bits=8)
    c = await Client.connect(setup["addr"])
    code, text = await c.post(cheap.to_bytes())
    await c.quit()
    assert code != 240 and "12" in text


def test_create_groups_moves_a_charter_to_its_name():
    """A project group whose manifest still says ``rules`` (UN-RFC 0014 section 2.2) gets a
    new manifest with ``charter``, even when nothing else differs (#726)."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "project"))
    try:
        cg = importlib.import_module("create_groups")
    finally:
        sys.path.pop(0)
    current = {"name": "unseenet", "type": "open", "serial": 4, "title": "T",
               "description": "D", "rules": "Be kind", "min_pow": 20}
    wanted = dict(cg.SETTINGS, title="T", description="D", charter="Be kind", min_pow=20)
    data, notes = cg.updated_manifest(current, "open", wanted)
    assert data["charter"] == "Be kind" and "rules" not in data and data["serial"] == 5
    assert notes == ["    rules -> charter (the field's current name)"]
    assert cg.updated_manifest(data, "open", wanted) == (None, [])
