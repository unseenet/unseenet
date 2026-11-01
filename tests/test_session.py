"""Client session against a local node: open and closed groups, invites, read marks."""

import asyncio
import os
import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def test_closed_group_invite_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    a, b, c = session("andreas"), session("sonia"), session("outsider")
    fam = await a.create_group("familie", "closed", min_pow=10)
    await a.invite(fam, b.identity().key_text)
    await a.post(fam, "Hemmeligt", "Kun for familien\n")

    for s in (b, c):
        s.subscribe(fam)
    got_b = await b.fetch_group(fam)
    got_c = await c.fetch_group(fam)
    assert [m.body for m in got_b] == ["Kun for familien\n"]
    assert got_c and not got_c[0].readable and "Kun" not in got_c[0].body

    # b can post back; own posts count as read, others' do not
    await b.post(fam, "Re: Hemmeligt", "Fint!\n", references=[got_b[0].message_id])
    msgs = await b.fetch_group(fam)
    assert b.unread_count(fam) == 1
    assert msgs[-1].references == [got_b[0].message_id]

    # an outsider cannot post into the closed group
    c.group_entry(fam)["keys"] = {}
    try:
        await c.post(fam, "spam", "spam")
        raise AssertionError("outsider could post")
    except sess.SessionError:
        pass

    for s in (a, b, c):
        await s.close()
    server.close()


async def test_offline_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    a = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    a.new_identity("a", "A"); a.add_node(addr)
    b = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    b.new_identity("b", "B"); b.add_node(addr)
    open_g = await a.create_group("dk.snak", "open", min_pow=10)
    closed = await a.create_group("familie", "closed", min_pow=10)
    await a.invite(closed, b.identity().key_text)
    await a.post(open_g, "Offentligt", "Alle kan læse\n")
    await a.post(closed, "Hemmeligt", "Kun familien\n")
    b.subscribe(open_g); b.subscribe(closed)
    await b.fetch_group(open_g); await b.fetch_group(closed)
    await b.close(); await a.close()
    server.close(); await server.wait_closed()

    # the cache file is encrypted
    blob = (tmp_path / "b.vault.cache").read_bytes()
    assert b"Kun familien" not in blob and b"Alle kan" not in blob
    if os.name != "nt":                    # Windows has no Unix file modes
        assert oct((tmp_path / "b.vault.cache").stat().st_mode & 0o777) == "0o600"

    # node is gone: everything is still readable from the cache
    again = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    assert again.load_offline() == 2
    bodies = {m.subject: m.body for g in again.cache.values() for m in g.values()}
    assert bodies == {"Offentligt": "Alle kan læse\n", "Hemmeligt": "Kun familien\n"}
    try:
        await again.fetch_group(open_g)
        raise AssertionError("node should be unreachable")
    except (OSError, ConnectionError):
        pass
    assert again.cache[open_g]          # cache untouched by the failed fetch

    # a cache made for another node is ignored (article numbers are per node)
    other = Session(Vault.open(tmp_path / "b.vault", "pw", **KDF), status=lambda *_: None)
    other.data["nodes"] = ["127.0.0.1:1"]
    assert other.load_offline() == 0


def test_signatures(tmp_path):
    from unseenet.client.session import split_signature
    assert split_signature("Hej\n-- \nAndreas\n") == ("Hej\n", "Andreas\n")
    assert split_signature("Hej\n--\nikke en signatur\n") == ("Hej\n--\nikke en signatur\n", None)
    assert split_signature("a\n-- \nfirst\n-- \nlast\n") == ("a\n-- \nfirst\n", "last\n")

    s = Session(Vault.open(tmp_path / "s.vault", "pw", **KDF), status=lambda *_: None)
    ident = s.new_identity("a", "Andreas")
    assert s.signature() == f"Andreas  ·  {ident.key_text}"     # the default
    s.set_signature("{name} ({fp})\n{key}")
    assert s.signature() == f"Andreas ({ident.fingerprint[:4]})\n{ident.key_text}"
    try:
        s.set_signature("1\n2\n3\n4\n5")
        raise AssertionError("five lines accepted")
    except sess.SessionError:
        pass


async def test_group_charter_and_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    owner, reader = session("owner"), session("reader")
    gid = await owner.create_group("dk.snak", "open", title="Snak", charter="Vær søde ved hinanden.",
                                   min_pow=10)
    reader.subscribe(gid)
    await reader.fetch_group(gid)
    assert reader.manifest_data(gid)["charter"] == "Vær søde ved hinanden."
    assert reader.charter_unseen(gid)
    reader.mark_charter_seen(gid)
    assert not reader.charter_unseen(gid)

    # only the owner can change it; a change raises the serial and shows the charter again
    with pytest.raises(sess.SessionError):
        await reader.update_group(gid, charter="hacked")
    new = await owner.update_group(gid, charter="Vær søde. Ingen reklamer.", view="chat")
    assert new["serial"] == 2 and new["type"] == "open" and new["title"] == "Snak"
    await reader.fetch_group(gid)
    assert reader.manifest_data(gid)["charter"] == "Vær søde. Ingen reklamer."
    assert reader.manifest_data(gid)["view"] == "chat" and reader.charter_unseen(gid)
    with pytest.raises(sess.SessionError):
        await owner.update_group(gid, type="closed")      # type can never change

    # a Markdown charter (UN-RFC 0014 2.1); an emptied charter takes its type with it
    md = "text/markdown; charset=utf-8; variant=unseenet"
    new = await owner.update_group(gid, charter="# Regler\n\n- vær søde", charter_type=md)
    await reader.fetch_group(gid)
    assert reader.manifest_data(gid)["charter_type"] == md
    new = await owner.update_group(gid, charter="")
    assert "charter" not in new and "charter_type" not in new

    # postage follows the group: a cheap chat group, a node with its own minimum
    chat = await owner.create_group("chat.venner", "open", view="chat", low_latency=True, min_pow=9)
    assert await owner.required_pow(chat) == 9
    assert await owner.required_pow(gid) == 10
    for s in (owner, reader):
        await s.close()
    server.close()


async def test_post_without_cached_manifest_meets_group_postage(tmp_path, monkeypatch):
    """A group joined before manifests were cached (or whose manifest was never
    fetched) must still get enough postage: the group asks more than the node."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s

    owner, reader = session("owner"), session("reader")
    gid = await owner.create_group("strict", "open", min_pow=11)
    reader.subscribe(gid)
    await reader.fetch_group(gid)
    reader.data["groups"][gid].pop("manifest", None)   # as in an older vault
    await reader.post(gid, "Hej", "Det virker\n")
    assert int(reader.manifest_data(gid)["min_pow"]) == 11   # learned from the node
    await reader.post(gid, "Igen", "Og nu i første forsøg\n")
    bodies = [m.body for m in await owner.fetch_group(gid)]
    assert "Det virker\n" in bodies and "Og nu i første forsøg\n" in bodies
    for s in (owner, reader):
        await s.close()
    server.close()


async def test_old_vault_learns_manifest_and_charter(tmp_path, monkeypatch):
    """A vault from before manifests were cached rereads the group once and so
    learns its charter; the owner can then edit it."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    s = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("owner", "Owner")
    s.add_node(addr)
    gid = await s.create_group("charter", "open", min_pow=8)
    await s.post(gid, "Hej", "Første\n")
    await s.fetch_group(gid)
    entry = s.data["groups"][gid]
    entry.pop("manifest", None)                      # as in an older vault
    assert not s.manifest_data(gid)
    await s.fetch_group(gid)
    assert s.manifest_data(gid).get("serial")
    await s.update_group(gid, charter="Vær søde ved hinanden")
    assert s.manifest_data(gid)["charter"] == "Vær søde ved hinanden"
    # a manifest signed when the field was called rules (UN-RFC 0014 2.2), and a vault
    # that kept what was seen as rules_seen (#726)
    entry["manifest"] = {**{k: v for k, v in entry["manifest"].items() if k != "charter"},
                         "rules": "Gamle ord"}
    s.data["rules_seen"] = {gid: int(entry["manifest"]["serial"])}
    assert s.manifest_data(gid)["charter"] == "Gamle ord" and "rules" not in s.manifest_data(gid)
    assert not s.charter_unseen(gid) and "rules_seen" not in s.data
    await s.update_group(gid, title="Snak")                  # republished: the new name
    assert s.data["groups"][gid]["manifest"]["charter"] == "Gamle ord"
    assert "rules" not in s.data["groups"][gid]["manifest"] and s.charter_unseen(gid)
    await s.close()
    server.close()


async def test_one_tor_for_concurrent_connections(tmp_path, monkeypatch):
    """Several connections at once start one Tor, not one each (seen on Windows:
    the extra ones died and left a client talking to a Tor that was gone)."""
    import asyncio

    started = []

    class FakeTor:
        def __init__(self, data_dir, binary, bridges=None):
            self.socks_port = 9050 + len(started)
            self.running = False

        async def start(self, progress=None):
            started.append(self)
            await asyncio.sleep(0.05)
            self.running = True

        def alive(self):
            return self.running

        async def stop(self):
            self.running = False

    monkeypatch.setattr(sess, "TorProcess", FakeTor)
    monkeypatch.setattr(FakeTor, "find_binary", staticmethod(lambda: "tor"), raising=False)
    s = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    ports = await asyncio.gather(*(s._ensure_tor(lambda *_: None) for _ in range(5)))
    assert len(started) == 1 and set(ports) == {9050}

    # a Tor that died is replaced on the next connection
    s.tor.running = False
    assert await s._ensure_tor(lambda *_: None) == 9051
    assert len(started) == 2
    await s.close()


def test_new_vault_has_signature_and_project_groups(tmp_path):
    from unseenet.known_nodes import STARTER_GROUPS
    s = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("andreas", "Andreas")
    assert s.signature().startswith("Andreas  ·  ed25519:")
    s.set_signature("")                       # the user's choice of none is kept
    assert s.signature() == ""

    assert not s.subscribe_starter_groups()   # no node yet: later
    s.add_node("127.0.0.1:1119")
    assert s.subscribe_starter_groups()
    assert all(g in s.data["subscribed"] for g in STARTER_GROUPS)
    assert "unseenet.test@ph5fc5hop5232qsz" not in s.data["subscribed"]     # moved away
    s.subscribe(STARTER_GROUPS[-1], False)    # unsubscribed groups stay away
    assert not s.subscribe_starter_groups()
    assert STARTER_GROUPS[-1] not in s.data["subscribed"]


async def test_interrupted_exchange_does_not_poison_the_connection(tmp_path, monkeypatch):
    """A reader cancelled half-way through an answer (the TUI cancels a fetch when
    you pick another group) left the rest on the connection; every later command
    then read it as its own status line ("invalid literal for int(): 'dk.'")."""
    import asyncio
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    s = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("a", "A")
    s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    for n in ("dk.snak", "dk.teknik", "alt.test"):
        await s.create_group(n, "open", min_pow=10)

    async def cancelled_half_way(c):
        await c.command("LIST NEWSGROUPS *", (215,))   # the list itself is not read
        raise asyncio.CancelledError
    try:
        await s._call(cancelled_half_way)
    except asyncio.CancelledError:
        pass
    assert len(await s.list_groups()) == 3             # a fresh connection
    await s.close()
    server.close()


def test_manifest_from_a_node_must_be_signed_by_the_owner(tmp_path):
    """A hostile node cannot make the client take a manifest signed by another
    key, or one that changes the group's type (UN-RFC 0004 section 4, #41)."""
    from unseenet.core import crypto
    from unseenet.core.groups import make_group_id, make_manifest, manifest_article

    s = Session(Vault.open(tmp_path / "m.vault", "pw", **KDF), status=lambda *_: None)
    owner, mallory = crypto.Identity.generate(), crypto.Identity.generate()
    first = make_manifest(owner, "unseenet.nodes", "channel", pow_bits=0)
    gid = make_group_id("unseenet.nodes", owner.public_key)
    entry: dict = {}

    def feed(art):
        raw = art.to_bytes()
        assert s._parse(1, raw, gid, entry, None) is None      # manifests are not posts

    feed(first)
    assert entry["manifest"]["serial"] == 1

    # Mallory signs a "newer" manifest for the owner's group, adding herself as poster
    forged = dict(entry["manifest"], serial=99, posters=[mallory.key_text])
    feed(manifest_article(mallory, gid, forged, pow_bits=0))
    assert entry["manifest"]["serial"] == 1
    assert "posters" not in entry["manifest"]

    # The owner cannot change the type either
    feed(manifest_article(owner, gid, dict(entry["manifest"], serial=5, type="open"), pow_bits=0))
    assert entry["manifest"]["type"] == "channel"

    # A real update from the owner is taken; an older one after it is not
    feed(manifest_article(owner, gid, dict(entry["manifest"], serial=3, title="Nodes"), pow_bits=0))
    assert entry["manifest"]["serial"] == 3 and entry["title"] == "Nodes"
    feed(manifest_article(owner, gid, dict(entry["manifest"], serial=2, title="Old"), pow_bits=0))
    assert entry["manifest"]["title"] == "Nodes"


async def test_withdraw_posts_and_honour_cancels(tmp_path, monkeypatch):
    """UN-RFC 0004 section 7: authors withdraw their own posts, the owner any
    post; a reader checks every cancel itself and remembers early ones."""
    from unseenet.core import crypto
    from unseenet.core.article import new_article
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    owner, author, reader = person("owner"), person("author"), person("reader")
    gid = await owner.create_group("dk.snak", "open", min_pow=8)
    for p in (author, reader):
        p.subscribe(gid)
    await author.post(gid, "Ups", "Forkert gruppe\n")
    await author.post(gid, "Bliver", "Den her bliver\n")
    await owner.post(gid, "Ejer", "Fra ejeren\n")
    msgs = {m.subject: m for m in await author.fetch_group(gid)}

    # a stranger's cancel is refused by the node; a node that serves one anyway
    # (here: written straight into the store) is ignored by the reader
    mallory = crypto.Identity.generate()
    forged = new_article(gid, None, "", extra=[("Control", f"cancel {msgs['Bliver'].message_id}")])
    node.store.add(forged.finalize(mallory, 8), forged.to_bytes())
    assert not author.may_cancel(msgs["Ejer"])
    with pytest.raises(sess.SessionError):
        await author.cancel(msgs["Ejer"])

    await author.cancel(msgs["Ups"])                   # own post
    assert all(m.subject != "Ups" for m in author.cache[gid].values())
    owner_msgs = {m.subject: m for m in await owner.fetch_group(gid)}
    assert owner.may_cancel(owner_msgs["Bliver"]) is True   # the owner may withdraw any post

    subjects = {m.subject for m in await reader.fetch_group(gid)}
    assert subjects == {"Bliver", "Ejer"}              # Ups withdrawn, forged cancel ignored

    # a cancel seen before its target: the target is not shown when it arrives
    early = reader.group_entry(gid).setdefault("cancels", {})
    from datetime import datetime, timezone
    from email.utils import format_datetime
    early[msgs["Ejer"].message_id] = {"by": owner.identity().key_text,
                                      "date": format_datetime(datetime.now(timezone.utc))}
    reader.cache[gid].clear(); reader._raw[gid].clear(); reader._high[gid] = 0
    subjects = {m.subject for m in await reader.fetch_group(gid)}
    assert subjects == {"Bliver"}
    for p in (owner, author, reader):
        await p.close()
    server.close()


async def test_ignore_a_person(tmp_path, monkeypatch):
    """#72: the reader's own killfile - hidden everywhere, kept in the vault, nothing sent."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    me, troll, friend = person("me"), person("troll"), person("friend")
    gid = await friend.create_group("dk.snak", "open", min_pow=8)
    me.subscribe(gid)
    await troll.post(gid, "Spam", "Køb nu\n")
    await friend.post(gid, "Hej", "Hej alle\n")
    msgs = await me.fetch_group(gid)
    articles_before = len(node.store.numbers(gid))
    assert me.unread_count(gid) == 2

    me.ignore(troll.identity().key_text, "Trolden")
    assert [m.subject for m in me.visible(msgs)] == ["Hej"]
    assert me.unread_count(gid) == 1
    assert len(node.store.numbers(gid)) == articles_before       # nothing was sent
    with pytest.raises(sess.SessionError):
        me.ignore(me.identity().key_text)

    me.save()
    again = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    assert again.ignored() == [(troll.identity().key_text, "Trolden")]
    again.unignore(troll.identity().key_text)
    assert len(again.visible(msgs)) == 2
    for p in (me, troll, friend):
        await p.close()
    server.close()


async def test_ban_from_a_group(tmp_path, monkeypatch):
    """UN-RFC 0004 section 5.1: the owner bans a key; nodes refuse its posts and
    readers hide the old ones; lifting the ban lets it post again."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    owner, troll, reader = person("owner"), person("troll"), person("reader")
    gid = await owner.create_group("dk.snak", "open", min_pow=8)
    for p in (troll, reader):
        p.subscribe(gid)
    await troll.post(gid, "Trussel", "...\n")
    await owner.fetch_group(gid)

    with pytest.raises(sess.SessionError):
        await reader.ban(gid, troll.identity().key_text, "nej")        # not the owner
    await owner.ban(gid, troll.identity().key_text, "trusler mod andre")
    assert owner.banned(gid) == [(troll.identity().key_text, "trusler mod andre")]

    with pytest.raises(sess.SessionError) as e:
        await troll.post(gid, "Igen", "...\n")
    assert "banned" in str(e.value)
    msgs = await reader.fetch_group(gid)
    assert [m.subject for m in reader.visible(msgs)] == []          # the old post is hidden
    assert reader.is_banned(gid, troll.identity().key_text)

    await owner.unban(gid, troll.identity().key_text)
    await troll.fetch_group(gid)
    await troll.post(gid, "Undskyld", "...\n")
    msgs = await reader.fetch_group(gid)
    assert {m.subject for m in reader.visible(msgs)} == {"Trussel", "Undskyld"}
    for p in (owner, troll, reader):
        await p.close()
    server.close()


def test_manifest_banned_entries_are_checked():
    from unseenet.core import crypto
    from unseenet.core.article import ArticleError
    from unseenet.core.groups import Manifest, make_group_id, manifest_article
    owner = crypto.Identity.generate()
    gid = make_group_id("dk.snak", owner.public_key)
    base = {"v": 1, "name": "dk.snak", "type": "open", "owner": owner.key_text, "serial": 1}
    for bad in ([{"reason": "no key"}], [{"key": "nonsense"}], ["ed25519:abc"],
                [{"key": crypto.Identity.generate().key_text, "reason": "x" * 201}]):
        with pytest.raises(ArticleError):
            Manifest.from_article(manifest_article(owner, gid, dict(base, banned=bad), pow_bits=0))


async def test_moderators_posters_and_removing_members(tmp_path, monkeypatch):
    """#70: the owner chooses moderators and posters, and removes a member of a
    closed group with a new epoch."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    owner, mod, user = person("owner"), person("mod"), person("user")
    key = {p: p.identity().key_text for p in (owner, mod, user)}

    # moderated group: a moderator posts directly and may withdraw others' posts
    gid = await owner.create_group("dk.mod", "moderated", min_pow=8)
    for p in (mod, user):
        p.subscribe(gid)
    with pytest.raises(sess.SessionError):
        await mod.post(gid, "Før", "x\n")
    await owner.set_role(gid, "moderators", key[mod])
    await mod.fetch_group(gid)
    await mod.post(gid, "Efter", "x\n")
    assert mod.may_cancel(next(m for m in await mod.fetch_group(gid) if m.subject == "Efter"))
    with pytest.raises(sess.SessionError):
        await owner.set_role(gid, "posters", key[user])           # posters are for channels
    await owner.set_role(gid, "moderators", key[mod], False)
    assert "moderators" not in owner.manifest_data(gid)

    # channel: a poster may post
    ch = await owner.create_group("dk.kanal", "channel", min_pow=8)
    user.subscribe(ch)
    await owner.set_role(ch, "posters", key[user])
    await user.fetch_group(ch)
    await user.post(ch, "Nyt", "x\n")

    # closed group: remove a member with a new epoch
    cl = await owner.create_group("dk.lukket", "closed", min_pow=8)
    await owner.invite(cl, key[mod])
    await owner.invite(cl, key[user])
    assert owner.members(cl) == [key[mod], key[user]]
    for p in (mod, user):
        p.subscribe(cl)
        await p.fetch_group(cl)
    assert await owner.remove_member(cl, key[user]) == 2
    assert owner.members(cl) == [key[mod]]
    await owner.post(cl, "Hemmeligt", "kun for mod\n")
    seen = {p: [m for m in await p.fetch_group(cl) if m.readable and m.subject == "Hemmeligt"]
            for p in (mod, user)}
    assert len(seen[mod]) == 1 and seen[user] == []
    # the removed member still has the previous key, but may not post with it (#84)
    with pytest.raises(sess.SessionError) as e:
        await user.post(cl, "Stadig her", "x\n")
    assert "closed" in str(e.value)
    for p in (owner, mod, user):
        await p.close()
    server.close()


async def test_moderation_queue(tmp_path, monkeypatch):
    """UN-RFC 0009 section 3: a non-moderator's post to a moderated group goes to
    the owner and every moderator; the first approval posts it, unchanged."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    owner, mod, user = person("owner"), person("mod"), person("user")
    for p in (owner, mod, user):
        await p.ensure_inbox()
    gid = await owner.create_group("dk.mod", "moderated", min_pow=8)
    await owner.set_role(gid, "moderators", mod.identity().key_text)
    for p in (mod, user):
        p.subscribe(gid)
        await p.fetch_group(gid)

    msgid = await user.post(gid, "Spørgsmål", "Må jeg spørge om noget?\n")
    assert user.was_submitted(gid, msgid)
    assert await user.fetch_group(gid) == []                   # not in the group yet

    for p in (owner, mod):
        await p.fetch_group(p.my_inbox)
    queue = mod.submissions()
    assert [(a.message_id, a["Subject"]) for _, a in queue] == [(msgid, "Spørgsmål")]
    assert len(owner.submissions()) == 1
    assert user.sent_messages() == []                          # no copies of submissions

    await mod.approve_submission(*queue[0])
    posted = await user.fetch_group(gid)
    assert [m.message_id for m in posted] == [msgid]           # same Message-ID
    await owner.fetch_group(gid)
    assert owner.submissions() == []                           # handled by the other moderator

    # a rejection with a reason reaches the submitter
    msgid2 = await user.post(gid, "Spam", "køb\n")
    await mod.fetch_group(mod.my_inbox)
    m2, a2 = next((m, a) for m, a in mod.submissions() if a.message_id == msgid2)
    await mod.reject_submission(m2, "Ikke relevant her")
    assert mod.submissions() == []
    await user.fetch_group(user.my_inbox)
    assert any("Ikke relevant" in m.body for m in user.private_messages())
    for p in (owner, mod, user):
        await p.close()
    server.close()


async def test_hierarchy_blocks(tmp_path, monkeypatch):
    """UN-RFC 0018 sections 5.4 and 8: a maintainer blocks a key in its hierarchy;
    readers hide it (unless they choose to see it); a node that honours blocks
    refuses the key's new posts, one that does not still carries them."""
    import json
    import unseenet.hierarchies as hz
    import unseenet.known_nodes as kn
    from unseenet.client import naming
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    nodes, addrs, servers = [], [], []
    for honour in (True, False):
        n = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0), honour_blocks=honour))
        srv = await n.serve("127.0.0.1", 0)
        nodes.append(n); servers.append(srv)
        addrs.append(f"127.0.0.1:{srv.sockets[0].getsockname()[1]}")
    honouring, plain = addrs

    def person(name, addr):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    # the root publisher (stands in for the project) gives dk to a maintainer
    root_pub = person("root", honouring)
    maint = person("maint", honouring)
    root_gid = await root_pub.create_group("unseenet.hierarchies", "channel", min_pow=8)
    list_gid = await maint.create_group("dk.liste", "channel", min_pow=8)
    root_text = json.dumps({"v": 1, "hierarchies": [{"name": "dk", "policy": "governed",
                            "maintainer": maint.identity().key_text, "list": list_gid}]})
    await root_pub.post(root_gid, "Hierarchies", root_text + "\n")
    monkeypatch.setattr(hz, "HIERARCHIES_GROUP", root_gid)
    monkeypatch.setattr(kn, "PROJECT_KEY", root_pub.identity().key_text)

    owner = person("owner", honouring)
    troll = person("troll", honouring)
    gid = await owner.create_group("dk.snak.biler", "open", min_pow=8)
    troll.subscribe(gid)
    await troll.post(gid, "Trussel", "...\n")

    # the maintainer blocks the troll in all of dk.*
    maint.subscribe(gid)
    await naming.refresh(maint)
    assert [h.name for h in naming.governing(maint, gid)] == ["dk"]
    where = await naming.block(maint, gid, troll.identity().key_text, "trusler i flere grupper")
    assert where == "dk"

    reader = person("reader", honouring)
    reader.subscribe(gid)
    await naming.refresh(reader)
    msgs = await reader.fetch_group(gid)
    assert reader.visible(msgs) == []
    assert reader.hidden_by_blocks(gid) == [("dk", "trusler i flere grupper", 1)]
    reader.set_show_blocked(True)
    assert [m.subject for m in reader.visible(msgs)] == ["Trussel"]

    # the honouring node refuses new posts; its node information says so
    nodes[0]._blocks.clear()
    with pytest.raises(sess.SessionError) as e:
        await troll.post(gid, "Igen", "...\n")
    assert "blocked in dk.*" in str(e.value)
    assert nodes[0].node_info()["policy"]["honours_blocks"] is True
    assert nodes[1].node_info()["policy"]["honours_blocks"] is False
    for p in (root_pub, maint, owner, troll, reader):
        await p.close()
    for srv in servers:
        srv.close()


async def test_report_a_post(tmp_path, monkeypatch):
    """#74: a report goes as a private message to the owner, the moderators and the
    node's operator; recipients find the reported post from it."""
    from unseenet.core import crypto
    from unseenet.core.groups import personal_inbox_id
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    operator = Session(Vault.open(tmp_path / "op.vault", "pw", **KDF), status=lambda *_: None)
    op = operator.new_identity("op", "Op")
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0), name="node1",
                                    operator={"key": op.key_text,
                                              "contact": personal_inbox_id(op.public_key)}))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    owner, mod, troll, reader = (person(n) for n in ("owner", "mod", "troll", "reader"))
    for p in (owner, mod):
        await p.ensure_inbox()
    operator.add_node(addr)
    await operator.ensure_inbox()

    gid = await owner.create_group("dk.snak", "open", min_pow=8)
    await owner.set_role(gid, "moderators", mod.identity().key_text)
    troll.subscribe(gid)
    await troll.post(gid, "Trussel", "Jeg ved hvor du bor\n")
    reader.subscribe(gid)
    post = (await reader.fetch_group(gid))[0]

    targets = await reader.report_targets(post)
    assert [k for _, _, k in targets] == [owner.identity().key_text, mod.identity().key_text,
                                          op.key_text]
    assert await reader.report(post, targets, "Trusler mod et medlem", anonymous=True) == 3
    for p in (owner, mod, operator):
        await p.fetch_group(p.my_inbox)
        reports = [m for m in p.private_messages() if p.reported_post(m)]
        assert len(reports) == 1 and p.reported_post(reports[0]) == (gid, post.message_id)
        assert "Trusler mod et medlem" in reports[0].body and reports[0].sender_key is None
    for p in (owner, mod, troll, reader, operator):
        await p.close()
    server.close()


def test_client_hides_old_epoch_posts_after_a_closing_key_update(tmp_path):
    """UN-RFC 0004 section 6.5: an article of an earlier epoch that comes after a
    closing key update (a lagging node accepted it) is not shown."""
    from unseenet.core import crypto
    from unseenet.core.groups import encrypted_article, make_key_update, make_manifest
    s = Session(Vault.open(tmp_path / "m.vault", "pw", **KDF), status=lambda *_: None)
    me = s.new_identity("me", "Me")
    owner, removed = crypto.Identity.generate(), crypto.Identity.generate()
    gid = make_manifest(owner, "dk.lukket", "closed", pow_bits=0).group
    k1, k2 = crypto.GroupKeys.generate(), crypto.GroupKeys.generate()
    entry = {"type": "closed", "keys": {}, "manifest": {}}
    up1 = make_key_update(owner, gid, 1, k1, [me.public_key, removed.public_key], pow_bits=0)
    up2 = make_key_update(owner, gid, 2, k2, [me.public_key], closes_previous=True, pow_bits=0)
    before = encrypted_article(gid, 1, k1, removed, from_name="R", subject="Før", body="x\n", pow_bits=0)
    after = encrypted_article(gid, 1, k1, removed, from_name="R", subject="Efter", body="x\n", pow_bits=0)
    shown = []
    for n, art in enumerate([up1, before, up2, after], start=1):
        msg = s._parse(n, art.to_bytes(), gid, entry, me)
        if msg is not None:
            shown.append(msg.subject)
    assert shown == ["Før"]
    assert entry["closed"] == {"2": 3}


def _registrar_store(s, registrar, certs):
    st = s.data.setdefault("naming", {})
    st.setdefault("names", {})
    st["names"].update({"registrars": [registrar.key_text], "certs": [c.to_json() for c in certs],
                        "revoked": []})


def test_names_under_a_name_in_the_client(tmp_path):
    """UN-RFC 0019 section 5.4: sonia@lorensen counts while its issuer holds
    @lorensen, until revoked; DNS wins for person@domain; the author chooses."""
    from datetime import timedelta
    from unseenet import names as nm
    from unseenet.client import naming
    from unseenet.core import crypto
    reg = crypto.Identity.generate()
    andreas = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    a = andreas.new_identity("a", "Andreas")
    reader = Session(Vault.open(tmp_path / "r.vault", "pw", **KDF), status=lambda *_: None)
    reader.new_identity("r", "R")
    sonia, other = crypto.Identity.generate(), crypto.Identity.generate()
    lorensen = nm.make_certificate(reg, "lorensen", a.key_text, 1)
    jaxie = nm.make_certificate(reg, "jaxie", sonia.key_text, 1)
    for s in (andreas, reader):
        _registrar_store(s, reg, [lorensen, jaxie])

    assert naming.parents_i_hold(andreas) == ["lorensen"]
    sub = nm.make_subname(a, "sonia@lorensen", sonia.key_text, 1)
    naming.note_certificate(reader, sonia.key_text, sub.header_value())
    assert naming.identity_label(reader, sonia.key_text) == "sonia@lorensen"   # most recent
    naming.note_certificate(reader, sonia.key_text, jaxie.header_value())
    assert naming.identity_label(reader, sonia.key_text) == "@jaxie"           # she chose
    assert [c.name for c in naming.names_of(reader, sonia.key_text)] == ["sonia@lorensen", "jaxie"]

    # someone who does not hold @lorensen cannot give names under it
    fake = nm.make_subname(other, "eve@lorensen", other.key_text, 1)
    naming.note_certificate(reader, other.key_text, fake.header_value())
    assert naming.names_of(reader, other.key_text) == []

    # revoked by the issuer
    naming._store(reader)["issuer_revoked"][a.key_text] = [["sonia@lorensen", 1]]
    assert [c.name for c in naming.names_of(reader, sonia.key_text)] == ["jaxie"]
    naming._store(reader)["issuer_revoked"] = {}

    # @lorensen changes hands: its sub-names stop counting
    moved = nm.make_certificate(reg, "lorensen", other.key_text, 2)
    _registrar_store(reader, reg, [lorensen, moved, jaxie])
    assert [c.name for c in naming.names_of(reader, sonia.key_text)] == ["jaxie"]

    # person@domain: a DNS certificate from the registrar wins over a holder's sub-name
    dk = nm.make_certificate(reg, "lorensen.dk", a.key_text, 1)
    dns = nm.make_certificate(reg, "andlo@lorensen.dk", other.key_text, 1)
    given = nm.make_subname(a, "andlo@lorensen.dk", sonia.key_text, 1)
    _registrar_store(reader, reg, [dk, dns])
    naming.note_certificate(reader, sonia.key_text, given.header_value())
    assert "andlo@lorensen.dk" not in [c.name for c in naming.names_of(reader, sonia.key_text)]
    assert [c.name for c in naming.names_of(reader, other.key_text)] == ["andlo@lorensen.dk"]


async def test_ask_for_give_and_revoke_a_name_under_a_name(tmp_path, monkeypatch):
    """The whole round: Sonia asks for sonia@lorensen, Andreas approves, her client
    takes the certificate and shows it; Andreas revokes it and readers see that."""
    from unseenet import names as nm
    from unseenet.client import naming
    from unseenet.core import crypto
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    reg = crypto.Identity.generate()
    andreas, sonia, reader = person("andreas"), person("sonia"), person("reader")
    lorensen = nm.make_certificate(reg, "lorensen", andreas.identity().key_text, 1)
    for p in (andreas, sonia, reader):
        _registrar_store(p, reg, [lorensen])
        await p.ensure_inbox()

    await naming.request_subname(sonia, "sonia@lorensen")
    await andreas.fetch_group(andreas.my_inbox)
    reqs = naming.name_requests(andreas)
    assert [d["name"] for _, d in reqs] == ["sonia@lorensen"]
    await naming.answer_request(andreas, *reqs[0], approve=True)
    assert naming.name_requests(andreas) == []

    await sonia.fetch_group(sonia.my_inbox)
    assert naming.take_certificates(sonia)
    assert [c.name for c in naming.my_names(sonia)] == ["sonia@lorensen"]
    hdr = naming.header_for(sonia, "dk.x@abc")
    naming.note_certificate(reader, sonia.identity().key_text, hdr[1])
    assert naming.identity_label(reader, sonia.identity().key_text) == "sonia@lorensen"

    # andreas names himself too, and chooses what his posts show
    await naming.give_subname(andreas, "andreas@lorensen", andreas.identity().key_text)
    naming.set_primary(andreas, "andreas@lorensen")
    assert naming.identity_label(andreas, andreas.identity().key_text) == "andreas@lorensen"

    await naming.revoke_subname(andreas, "sonia@lorensen")
    gid = nm.revocation_group(andreas.identity().key_text)
    assert andreas.manifest_data(gid).get("view") == "data"
    posts = await naming._read(reader, gid, andreas.identity().key_text)
    best = naming._newest(posts, nm.parse_revocations)
    naming._store(reader)["issuer_revoked"][andreas.identity().key_text] = sorted(
        [n, v] for n, v in best[2])
    assert naming.names_of(reader, sonia.identity().key_text) == []
    for p in (andreas, sonia, reader):
        await p.close()
    server.close()


async def test_a_service_keeps_its_name_under_a_name(tmp_path, monkeypatch):
    """#592: a bot (Session.from_key) shows help@unseenet without code of its own -
    its first post makes its inbox, the name is given there, a later post carries it."""
    from datetime import datetime, timedelta, timezone
    from unseenet import names as nm
    from unseenet.client import naming
    from unseenet.core import crypto
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    reg = crypto.Identity.generate()
    project, reader = person("project"), person("reader")
    bot = Session.from_key(crypto.Identity.generate(), tmp_path / "bot.state.json",
                           name="helpbot", display="Unseenet help (bot)", status=lambda *_: None)
    bot.add_node(addr)
    assert bot.service and not project.service
    held = nm.make_certificate(reg, "unseenet", project.identity().key_text, 1)
    for p in (project, reader, bot):
        _registrar_store(p, reg, [held])
    await project.ensure_inbox()
    gid = await project.create_group("unseenet.help", "open", min_pow=10)
    for p in (reader, bot):
        p.subscribe(gid)

    await bot.post(gid, "Hello", "First post.\n")          # makes the bot's inbox
    await naming.give_subname(project, "help@unseenet", bot.identity().key_text)
    await bot.post(gid, "Again", "Same day: names are kept once a day.\n")
    assert naming.my_names(bot) == []
    naming._store(bot)["kept"] = nm.rfc3339(datetime.now(timezone.utc) - timedelta(days=2))
    await bot.post(gid, "Tomorrow", "Now with a name.\n")
    assert [c.name for c in naming.my_names(bot)] == ["help@unseenet"]

    await reader.fetch_group(gid)
    assert naming.identity_label(reader, bot.identity().key_text) == "help@unseenet"
    for p in (project, reader, bot):
        await p.close()
    server.close()


async def test_replies_and_mentions_for_you(tmp_path, monkeypatch):
    """#109: replies to your posts and posts naming your certified names; a display
    name or someone else's name under yours does not count."""
    from unseenet import names as nm
    from unseenet.core import crypto
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    me, other = person("andreas"), person("other")
    reg = crypto.Identity.generate()
    _registrar_store(me, reg, [nm.make_certificate(reg, "lorensen", me.identity().key_text, 1)])
    gid = await other.create_group("dk.snak", "open", min_pow=8)
    me.subscribe(gid)
    mine = await me.post(gid, "Spørgsmål", "Nogen der ved noget?\n")
    await other.fetch_group(gid)
    await other.post(gid, "Re: Spørgsmål", "Ja!\n", references=[mine])
    await other.post(gid, "Hej", "Spørg @lorensen om det.\n")
    await other.post(gid, "Ikke dig", "sonia@lorensen og @lorensen.dk og Andreas\n")
    msgs = {m.subject: m for m in await me.fetch_group(gid)}
    assert me.for_me(msgs["Re: Spørgsmål"]) == "reply"
    assert me.for_me(msgs["Hej"]) == "mention"
    assert me.for_me(msgs["Ikke dig"]) is None
    assert me.for_me(msgs["Spørgsmål"]) is None                     # your own post
    assert {m.subject for m in me.for_you()} == {"Hej", "Re: Spørgsmål"}
    assert me.for_you_count(gid) == 2
    assert me.for_you_counts(gid) == (1, 1)                         # #170: replies, mentions apart
    assert me.for_you_counts() == (1, 1)                            # all followed groups
    me.mark_read(msgs["Hej"])
    assert me.for_you_count(gid) == 1
    assert me.for_you_counts(gid) == (1, 0)
    for p in (me, other):
        await p.close()
    server.close()


async def test_for_you_rules_seen_and_show_all(tmp_path, monkeypatch):
    """#629, UN-RFC 0051 5.5: only [foryou] rules act; quiet is listed but not counted
    or told; hide leaves it out; Show all shows everything; seen in For you, or in its
    group, stops the count but keeps it listed."""
    from datetime import datetime, timezone
    from unseenet import names as nm
    from unseenet.client.localapi import LocalAPI
    from unseenet.client.session import FOR_YOU
    from unseenet.core import crypto
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    me, other, troll = person("andreas"), person("other"), person("troll")
    reg = crypto.Identity.generate()
    _registrar_store(me, reg, [nm.make_certificate(reg, "lorensen", me.identity().key_text, 1)])
    gid = await other.create_group("dk.snak", "open", min_pow=8)
    me.subscribe(gid)
    mine = await me.post(gid, "Spørgsmål", "Nogen?\n")
    for p in (other, troll):
        await p.fetch_group(gid)
    await other.post(gid, "Re: Spørgsmål", "Ja!\n", references=[mine])
    await other.post(gid, "Hej", "Spørg @lorensen.\n")
    await troll.post(gid, "Re: Spørgsmål", "Nej!\n", references=[mine])
    await me.fetch_group(gid)
    assert me.for_you_counts() == (2, 1)
    # a rule for the feed or groups never acts on For you
    me.set_feed_rules(f'hide if author is "{troll.identity().key_text}"\n')
    assert len(me.for_you()) == 3
    me.set_feed_rules(f'[foryou]\nquiet if for you is mention\n'
                      f'hide if author is "{troll.identity().key_text}"\n')
    listed = me.scored_for_you()
    assert [m.subject for m, _ in listed].count("Re: Spørgsmål") == 1     # the troll's hidden
    assert any("quiet" in r.actions for m, r in listed if m.subject == "Hej")  # listed, quiet
    assert me.for_you_counts() == (1, 0)                                 # neither is counted
    assert not any(m.subject == "Hej" for _, m in me._notifiable())      # nor told
    assert len(me.for_you(rules=False)) == 3                             # Show all
    api = LocalAPI(session=me)
    assert len(api.group(FOR_YOU, show_all=True)["rows"]) == 3 and api.group(FOR_YOU, show_all=True)["group"]["show_all"]
    assert len(api.group(FOR_YOU)["rows"]) == 2
    # seen in For you: not counted, still listed
    me.mark_seen(FOR_YOU, datetime.now(timezone.utc))
    assert me.for_you_counts() == (0, 0) and len(me.for_you()) == 2
    for p in (me, other, troll):
        await p.close()
    server.close()


async def test_find_group_ref(tmp_path, monkeypatch):
    """#172: what !dk.marsvin can mean - followed groups first, unknown names nothing."""
    from unseenet.core.groups import GroupRef
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    me, a, b = person("me"), person("a"), person("b")
    ga = await a.create_group("dk.marsvin", "open", min_pow=8)
    gb = await b.create_group("dk.marsvin", "open", min_pow=8)
    found = await me.find_group_ref(GroupRef("dk.marsvin"))
    assert {g.group_id for g in found} == {ga, gb}
    assert not any(g.subscribed for g in found)
    me.subscribe(gb)
    found = await me.find_group_ref(GroupRef("dk.marsvin"))
    assert found[0].group_id == gb and found[0].subscribed
    only = await me.find_group_ref(GroupRef("dk.marsvin", ga.split("@")[1][:4]))
    assert [g.group_id for g in only] == [ga]
    assert await me.find_group_ref(GroupRef("dk.findesikke")) == []
    for p in (me, a, b):
        await p.close()
    server.close()


async def test_mention_notices(tmp_path, monkeypatch):
    """UN-RFC 0032: a notice tells @lorensen about a post in a group he does not
    follow; the receiver checks it; false, ignored and doubled notices are not shown."""
    from unseenet import names as nm
    from unseenet.core import crypto
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    me, other = person("andreas"), person("other")
    reg = crypto.Identity.generate()
    certs = [nm.make_certificate(reg, "lorensen", me.identity().key_text, 1)]
    _registrar_store(me, reg, certs)
    _registrar_store(other, reg, certs)
    await me.ensure_inbox()
    gid = await other.create_group("dk.snak", "open", min_pow=8)
    secret = await other.create_group("familie", "closed", min_pow=8)

    text = "Spørg @lorensen om marsvin, eller mail andreas@example.org.\n"
    assert other.mentioned("Marsvin", text) == [("@lorensen", me.identity().key_text)]
    assert other.mentioned("", "@ukendt og @lorensen.dk") == []            # not resolvable
    assert me.mentioned("", "@lorensen") == []                             # not yourself
    assert other.mentioned("Re: x", "Sonia wrote:\n> Spørg @lorensen\n\nJa.\n") == []   # a quote
    assert not other.may_notify(secret) and other.may_notify(gid)

    post = await other.post(gid, "Marsvin", text)
    keys = [k for _, k in other.mentioned("Marsvin", text)]
    assert await other.send_mention_notices(gid, post, "Marsvin", "post", keys, delay=0) == 1
    assert await other.send_mention_notices(gid, post, "Marsvin", "post", keys, delay=0) == 0  # once
    plain = await other.post(gid, "Andet", "Intet navn her\n")               # a false notice
    await other.send_mention_notices(gid, plain, "Andet", "post", keys, delay=0)

    await me.fetch_group(me.my_inbox)
    found = me.for_you()
    assert [m.mention_of for m in found] == [post]
    assert me.for_you_counts() == (0, 1)
    assert not any(me.is_notice(m) for m in me.private_posts())             # in For you only
    assert me.notice_post(found[0])["subject"] == "Marsvin"
    assert gid not in me.data["subscribed"]                                 # checking follows nothing

    me.set_notice_settings(receive=False)
    assert me.for_you() == []
    me.set_notice_settings(receive=True)
    me.ignore(other.identity().key_text, "Other")
    assert me.for_you() == []
    me.unignore(other.identity().key_text)

    me.subscribe(gid)                                                       # now it is marked there
    await me.fetch_group(gid)
    assert [m.message_id for m in me.for_you()] == [post]
    for p in (me, other):
        await p.close()
    server.close()


async def test_mention_notices_go_with_approval(tmp_path, monkeypatch):
    """UN-RFC 0032 section 4.3: the author builds the notices when submitting; the
    moderator posts them on approval - the author need not be online."""
    from unseenet import names as nm
    from unseenet.core import crypto
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    monkeypatch.setattr(sess.random, "uniform", lambda a, b: 0)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def person(name):
        p = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        p.new_identity(name, name.title()); p.add_node(addr)
        return p

    owner, user, sonia = person("owner"), person("user"), person("sonia")
    for p in (owner, user, sonia):
        await p.ensure_inbox()
    reg = crypto.Identity.generate()
    cert = [nm.make_certificate(reg, "sonia", sonia.identity().key_text, 1)]
    _registrar_store(user, reg, cert)
    _registrar_store(sonia, reg, cert)
    gid = await owner.create_group("dk.mod", "moderated", min_pow=8)
    user.subscribe(gid)
    await user.fetch_group(gid)

    text = "Hvad siger du, @sonia?\n"
    msgid = await user.post(gid, "Spørgsmål", text)
    keys = [k for _, k in user.mentioned("Spørgsmål", text)]
    assert await user.send_mention_notices(gid, msgid, "Spørgsmål", "post", keys) == 1
    await user.close()                                             # the author goes away
    await sonia.fetch_group(sonia.my_inbox)
    assert sonia.for_you() == []                                   # nothing before approval

    await owner.fetch_group(owner.my_inbox)
    (msg, art), = owner.submissions()
    assert len(owner.notice_bundle(art)) == 1
    assert not any(m.notices_for for m in owner.private_posts())   # not a post to read
    await owner.approve_submission(msg, art)
    await asyncio.gather(*owner._notice_tasks.values())
    assert owner.data["notices_to_post"] == []
    await sonia.fetch_group(sonia.my_inbox)
    assert [m.mention_of for m in sonia.for_you()] == [msgid]
    assert sonia.for_you()[0].sender_key == user.identity().key_text   # from the author
    for p in (owner, sonia):
        await p.close()
    server.close()


def test_moved_starter_groups_take_the_old_ones_place(tmp_path):
    """UN-RFC 0055 4.1: test and the demo moved out of unseenet.*; a vault that follows
    the old groups follows the new ones in their place, in the user's order."""
    from unseenet import known_nodes
    s = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("andreas", "Andreas")
    s.add_node("127.0.0.1:1119")
    s.data["subscribed"] = ["unseenet.demo.feed@lcgptqqjydt2sevj", "dk.snak@abcdefghijklmnop",
                            "unseenet.test@ph5fc5hop5232qsz"]
    s.data["starter_groups"] = 4
    assert s.subscribe_starter_groups()
    assert s.data["subscribed"] == ["demo.unseenet.feed@lcgptqqjydt2sevj", "dk.snak@abcdefghijklmnop",
                                    "test.unseenet@ph5fc5hop5232qsz"]   # demo.site was left


def test_starter_groups_added_later_reach_earlier_vaults(tmp_path, monkeypatch):
    """#388: a vault that took the first list gets the groups added since - and never
    again one it left."""
    from unseenet import known_nodes
    s = Session(Vault.open(tmp_path / "a.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("andreas", "Andreas")
    s.add_node("127.0.0.1:1119")
    first = known_nodes.STARTER_GROUP_VERSIONS[0]
    s.data["subscribed"] = [g for g in first if g != first[-1]]   # left the last one
    s.data["starter_groups"] = True                              # took version 1 before #388
    assert s.subscribe_starter_groups()
    assert "unseenet.chat@ph5fc5hop5232qsz" in s.data["subscribed"]
    assert first[-1] not in s.data["subscribed"]                 # left: stays away
    assert known_nodes.MOVED_STARTER_GROUPS[first[-1]] not in s.data["subscribed"]  # moved too
    assert s.data["starter_groups"] == len(known_nodes.STARTER_GROUP_VERSIONS)
    assert not s.subscribe_starter_groups()                      # nothing new
    monkeypatch.setattr(known_nodes, "STARTER_GROUP_VERSIONS",
                        known_nodes.STARTER_GROUP_VERSIONS + (("unseenet.demo@aaaaaaaaaaaaaaaa",),))
    assert s.subscribe_starter_groups()                          # a third version, one day
    assert "unseenet.demo@aaaaaaaaaaaaaaaa" in s.data["subscribed"]
