"""Client session against a local node: open and closed groups, invites, read marks."""

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


async def test_group_rules_and_updates(tmp_path, monkeypatch):
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
    gid = await owner.create_group("dk.snak", "open", title="Snak", rules="Vær søde ved hinanden.",
                                   min_pow=10)
    reader.subscribe(gid)
    await reader.fetch_group(gid)
    assert reader.manifest_data(gid)["rules"] == "Vær søde ved hinanden."
    assert reader.rules_unseen(gid)
    reader.mark_rules_seen(gid)
    assert not reader.rules_unseen(gid)

    # only the owner can change it; a change raises the serial and shows the rules again
    with pytest.raises(sess.SessionError):
        await reader.update_group(gid, rules="hacked")
    new = await owner.update_group(gid, rules="Vær søde. Ingen reklamer.", view="chat")
    assert new["serial"] == 2 and new["type"] == "open" and new["title"] == "Snak"
    await reader.fetch_group(gid)
    assert reader.manifest_data(gid)["rules"] == "Vær søde. Ingen reklamer."
    assert reader.manifest_data(gid)["view"] == "chat" and reader.rules_unseen(gid)
    with pytest.raises(sess.SessionError):
        await owner.update_group(gid, type="closed")      # type can never change

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


async def test_old_vault_learns_manifest_and_rules(tmp_path, monkeypatch):
    """A vault from before manifests were cached rereads the group once and so
    learns its rules; the owner can then edit them."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    s = Session(Vault.open(tmp_path / "o.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("owner", "Owner")
    s.add_node(addr)
    gid = await s.create_group("rules", "open", min_pow=8)
    await s.post(gid, "Hej", "Første\n")
    await s.fetch_group(gid)
    entry = s.data["groups"][gid]
    entry.pop("manifest", None)                      # as in an older vault
    assert not s.manifest_data(gid)
    await s.fetch_group(gid)
    assert s.manifest_data(gid).get("serial")
    await s.update_group(gid, rules="Vær søde ved hinanden")
    assert s.manifest_data(gid)["rules"] == "Vær søde ved hinanden"
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

        async def start(self):
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
