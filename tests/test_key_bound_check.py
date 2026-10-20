"""tools/key_bound_check.py: completeness of key-bound state (UN-RFC 0040 section 7)."""

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import key_bound_check as kb  # noqa: E402
from unseenet.core import reconcile as rc  # noqa: E402
from unseenet.core.store import Store  # noqa: E402

FAR = int(time.time()) + 10**7


class FakeNode:
    """Answers XUN-RECONCILE over a store, as the node does."""

    def __init__(self, items: dict[str, str]):
        self.store = Store()
        for gid, msgid in items.items():
            self.store._kb_put(gid, msgid, FAR)
        self.store.db.commit()

    async def reconcile(self, lines):
        return rc.format_message(rc.answer(self.store, rc.parse_message(lines)))


def _items(n, seed):
    rnd = random.Random(seed)
    return {f"inbox@k{i:06d}": f"<{rnd.getrandbits(64):x}@x>" for i in range(n)}


async def test_same_state_lacks_nothing():
    items = _items(3000, 1)
    c = await kb.compare(FakeNode(items), FakeNode(items))
    assert c.finished and c.lacking == {} and c.reference_count == c.node_count == 3000


async def test_finds_exactly_what_the_node_lacks():
    ref = _items(3000, 2)
    node = dict(ref)
    gone = random.Random(3).sample(sorted(ref), 150)
    for gid in gone:
        del node[gid]
    node.update({f"profile@x{i}": f"<x{i}@x>" for i in range(50)})    # extra: not lacking
    c = await kb.compare(FakeNode(node), FakeNode(ref))
    assert c.finished
    assert sorted(c.lacking.values()) == sorted(ref[g] for g in gone)
    assert sorted(c.lacking) == sorted(rc.item_key(g).hex() for g in gone)


async def test_far_behind_stops_with_a_lower_bound():
    c = await kb.compare(FakeNode({}), FakeNode(_items(20000, 4)))
    assert not c.finished and c.lacking_count >= 19000 and c.reference_count == 20000


def test_verdict_needs_two_checks():
    lacking = {f"{i:064x}": f"<{i}@x>" for i in range(300)}
    today = kb.Comparison(reference_count=1000, node_count=700, lacking=lacking)
    assert kb.verdict("node1", today, None) is None                       # first time
    half = kb.record(kb.Comparison(lacking=dict(list(lacking.items())[:150])), "node1", "d")
    assert kb.verdict("node1", today, half) is not None                   # 150 > 100 in both
    few = kb.record(kb.Comparison(lacking=dict(list(lacking.items())[:90])), "node1", "d")
    assert kb.verdict("node1", today, few) is None                        # 90 in both: fine
    caught_up = kb.Comparison(reference_count=1000, node_count=1000)
    assert kb.verdict("node1", caught_up, kb.record(today, "node1", "d")) is None
    far = kb.Comparison(reference_count=50000, finished=False, at_least=40000)
    over = kb.record(far, "node1", "d")
    assert over["over"] and "40000" in kb.verdict("node1", far, over)
    assert kb.allowance(50000) == 100 and kb.allowance(500000) == 500


def _node_health():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "node_health", Path(__file__).resolve().parent.parent / "tools" / "node_health.py")
    nh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nh)
    return nh


async def test_node_health_judges_on_the_second_day(monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    import canary
    nh = _node_health()
    ref = _items(1000, 5)
    behind = dict(list(ref.items())[150:])
    old = FakeNode(behind)
    old.reconcile = None                               # a node from before UN-RFC 0040
    fakes = {"A": FakeNode(ref), "B": FakeNode(ref), "C": FakeNode(behind), "D": old}

    async def connect(address, port):
        f = fakes[address]
        f.capability = lambda name, f=f: "1" if name == "UNSEENET-RECONCILE" and f.reconcile else None

        async def quit():
            pass
        f.quit = quit
        return f
    monkeypatch.setattr(canary, "_connect", connect)
    nodes = [SimpleNamespace(name=f"node{k}", address=k, node_key=f"key{k}") for k in "ABCD"]

    problems, records = await nh.check_key_bound(nodes, 0, date(2026, 10, 20), {})
    assert problems["A"] == problems["B"] == problems["C"] == []     # first check: not yet
    assert "update the node" in problems["D"][0]
    assert len(records["keyC"]["lacking"]) == 150 and records["keyA"]["lacking"] == []

    health = {"key_bound": records}
    before = nh.key_bound_before(health, date(2026, 10, 21))
    assert set(before) == {"keyA", "keyB", "keyC"}
    assert nh.key_bound_before(health, date(2026, 10, 20)) == {}      # same day: not 6 h apart
    assert nh.key_bound_before(health, date(2026, 10, 25)) == {}      # too old
    problems, _ = await nh.check_key_bound(nodes, 0, date(2026, 10, 21), before)
    assert "lacks 150 of the 1000" in problems["C"][0] and problems["A"] == []
