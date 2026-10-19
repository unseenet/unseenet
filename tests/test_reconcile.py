"""UN-RFC 0040 section 4: the key-bound index and XUN-RECONCILE."""

import random
import time

import pytest

from unseenet.core import crypto
from unseenet.core import reconcile as rc
from unseenet.core.groups import make_manifest
from unseenet.core.store import Store
from unseenet.nntp import Client, NNTPError
from unseenet.node.server import Node, NodeConfig

BITS = 8


def _ids(n, seed, prefix="g"):
    rnd = random.Random(seed)
    return {f"inbox@{prefix}{i:06d}": f"<{rnd.getrandbits(64):x}@x>" for i in range(n)}


def _direct(source):
    """A send() that answers in-process, as a node would."""
    async def send(lines):
        return rc.format_message(rc.answer(source, rc.parse_message(lines)))
    return send


# --- the algorithm -----------------------------------------------------------
async def test_same_state_settles_in_one_round():
    items = _ids(500, 1)
    r = await rc.reconcile(_direct(rc.MemorySource(items)), rc.MemorySource(items))
    assert r.same and r.rounds == 1 and r.need == r.offer == [] and r.their_count == 500


async def test_differences_are_found_both_ways():
    theirs = _ids(3000, 2)
    ours = dict(theirs)
    missing = random.Random(3).sample(sorted(theirs), 60)
    for gid in missing[:40]:
        del ours[gid]                               # we lack 40
    for gid in missing[40:]:
        ours[gid] = "<newer@x>"                     # 20 differ
    extra = {f"profile@e{i}": f"<e{i}@x>" for i in range(30)}
    ours.update(extra)                              # they lack 30
    r = await rc.reconcile(_direct(rc.MemorySource(theirs)), rc.MemorySource(ours))
    assert sorted(r.need) == sorted(theirs[g] for g in missing)
    assert sorted(r.offer) == sorted(list(extra.values()) + ["<newer@x>"] * 20)
    assert r.rounds <= 6 and r.their_count == 3000


async def test_empty_side_and_tiny_sets():
    items = _ids(40, 4)
    r = await rc.reconcile(_direct(rc.MemorySource(items)), rc.MemorySource())
    assert sorted(r.need) == sorted(items.values()) and r.rounds == 1
    r = await rc.reconcile(_direct(rc.MemorySource()), rc.MemorySource())
    assert r.need == r.offer == [] and r.rounds == 1


async def test_empty_node_catches_up_in_bounded_messages():
    """A new node: never asks for a big list, and stops at max_rounds with what it found."""
    peer = Store()
    far = int(time.time()) + 10**7
    for gid, msgid in _ids(20000, 7).items():
        peer._kb_put(gid, msgid, far)
    peer.db.commit()
    biggest = 0

    async def send(lines):
        nonlocal biggest
        out = rc.format_message(rc.answer(peer, rc.parse_message(lines)))
        biggest = max(biggest, len(out))
        return out
    r = await rc.reconcile(send, Store(), max_rounds=4096)
    assert r.complete and len(r.need) == 20000 and r.their_count == 20000
    assert biggest <= rc.ANSWER_BUDGET + rc.MAX_RANGES
    part = await rc.reconcile(send, Store(), max_rounds=2)
    assert not part.complete and not part.same and part.rounds == 2


def test_messages_are_checked():
    full = f"{0:064x} end"
    assert rc.parse_message([f"{full} F {'0' * 32} 3"])[0].count == 3
    for bad in ([f"{full} = "], [f"end {0:064x} F {'0' * 32} 1"], [f"{full} L 2", f"{'a' * 64} <x>"],
                [f"{'A' * 64} end L 0"], [f"{full} F zz 1"]):
        with pytest.raises(rc.ReconcileError):
            rc.parse_message(bad)
    two = [f"{0:064x} {1 << 255:064x} L 0", f"{(1 << 254):064x} end L 0"]
    with pytest.raises(rc.ReconcileError, match="overlapping"):
        rc.parse_message(two)
    assert rc.parse_message([f"{full} ="], answer=True)[0].kind == "="


def test_fingerprint_format():
    assert rc.fingerprint(0, 0) == rc.hashlib.sha256(bytes(40)).digest()[:16].hex()
    assert rc.fingerprint(1, rc.MOD + 5) == rc.fingerprint(1, 5)
    assert rc.split(0, rc.FULL)[1] == (1 << 252, 2 << 252)
    assert rc.split(10, 13) == [(10, 11), (11, 12), (12, 13)]


# --- the index ----------------------------------------------------------------
def test_running_sums_match_the_items():
    s = Store()
    items = _ids(3000, 5)
    far = int(time.time()) + 10**7
    for gid, msgid in items.items():
        s._kb_put(gid, msgid, far)
    for gid in list(items)[:500]:
        s._kb_drop(gid)
    for gid in list(items)[500:800]:
        s._kb_put(gid, "<renewed" + gid[6:] + ">", far)
    s.db.commit()
    mem = rc.MemorySource({g: m for g, m in s.db.execute("SELECT group_id, message_id FROM kb_items")})
    rnd = random.Random(6)
    bounds = [(0, rc.FULL), (0, 1 << 252), (5 << 248, 6 << 248)]
    bounds += [tuple(sorted((rnd.getrandbits(256), rnd.getrandbits(256)))) for _ in range(40)]
    for lo, hi in bounds:
        assert s.kb_count_sum(lo, hi) == mem.kb_count_sum(lo, hi)
        assert s.kb_items(lo, hi) == mem.kb_items(lo, hi)
    before = s.kb_count_sum()
    s.kb_rebuild()                     # no manifests in groups: rebuild empties it
    assert s.kb_count_sum() == (0, 0) and before[0] == 2500


def test_index_follows_manifests_removal_and_expiry():
    s = Store()
    node = Node(s, NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    owner = crypto.Identity.generate()
    inbox = make_manifest(owner, "inbox", "inbox", pow_bits=BITS)
    snak = make_manifest(owner, "dk.snak", "open", pow_bits=BITS)
    node.accept(inbox.to_bytes())
    node.accept(snak.to_bytes())
    assert s.kb_items() == [(rc.item_key(inbox.group), inbox.message_id)]   # not dk.snak
    want = s.kb_count_sum()

    s2 = Store()
    s2.db.executescript("".join(f"DELETE FROM {t};" for t in ("kb_items", "kb_sums")))
    for row in s.db.execute("SELECT * FROM groups"):
        s2.db.execute("INSERT INTO groups VALUES (?, ?, ?, ?, ?)", row)
    for row in s.db.execute("SELECT * FROM articles"):
        s2.db.execute("INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?, ?)", row)
    s2.kb_rebuild()                    # a store from before the index
    assert s2.kb_count_sum() == want

    s.kb_sweep(time.time() + 3 * 365 * 86400)   # past its expires
    assert s.kb_count_sum() == (0, 0)
    s.kb_rebuild()
    assert s.kb_count_sum() == want
    s.remove_group(inbox.group)
    assert s.kb_items() == []


# --- over the wire --------------------------------------------------------------
async def _serve(node):
    server = await node.serve("127.0.0.1", 0)
    return server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def test_xun_reconcile_between_two_nodes():
    a = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    b = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    people = [crypto.Identity.generate() for _ in range(12)]
    for i, p in enumerate(people):
        m = make_manifest(p, "inbox", "inbox", pow_bits=BITS).to_bytes()
        b.accept(m)
        if i % 3:
            a.accept(m)                 # a lacks a third of them
    only_a = make_manifest(crypto.Identity.generate(), "inbox", "inbox", pow_bits=BITS)
    a.accept(only_a.to_bytes())
    server, addr = await _serve(b)
    c = await Client.connect(addr)
    try:
        await c.fetch_capabilities()
        assert c.capability("UNSEENET-RECONCILE") == "1"
        r = await rc.reconcile(c.reconcile, a.store)
        assert len(r.need) == 4 and r.offer == [only_a.message_id] and r.their_count == 12
        from unseenet.nntp import strip_reader_headers
        for msgid in r.need:
            a.accept(strip_reader_headers(await c.article(msgid)))
        b.accept(only_a.to_bytes())
        assert (await rc.reconcile(c.reconcile, a.store)).same
    finally:
        await c.quit()
        server.close()


async def test_readers_get_one_exchange_per_connection():
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    server, addr = await _serve(node)
    c = await Client.connect(addr)
    line = [f"{0:064x} end L 0"]
    try:
        for _ in range(rc.MAX_ROUNDS):
            assert await c.reconcile(line) == line
        with pytest.raises(NNTPError) as err:
            await c.reconcile(line)
        assert err.value.code == 400
        c2 = await Client.connect(addr)
        with pytest.raises(NNTPError) as err:
            await c2.reconcile(["nonsense"])
        assert err.value.code == 501
        await c2.quit()
    finally:
        server.close()


def test_vector_of_un_rfc_0040_section_2():
    """The test vector in UN-RFC 0040 section 2: Message-ID hashed with <>."""
    key, value = rc.item_key("profile@example"), rc.item_value("<abc@example>")
    assert key.hex() == "545adb31607abddce27addb5f721edb1300bdd50fc5728de3461585c8a0b2828"
    assert value.hex() == "5f0aa3f59b76dab7882d61597fc575585207cdfd34e08f54035576c9326eafa8"
    assert rc.fingerprint(1, rc.item_hash(key, value)) == "1a7d54bbcaac7496050261a6ad763789"
