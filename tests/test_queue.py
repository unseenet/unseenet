"""#569: the posting queue - many posts paced by postage, ripening and quotas, kept where
the caller says, each article built when it is posted (UN-RFC 0049 section 3.1)."""
import json
import os
import stat
import time
from datetime import datetime, timedelta, timezone

import pytest

from unseenet.client.session import Session, SessionError
from unseenet.core.article import Article, parse_date
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def world(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", BITS)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("andreas", "Andreas")
    s.add_node("127.0.0.1:%d" % server.sockets[0].getsockname()[1])
    gid = await s.create_group("dk.notes", "channel", min_pow=BITS, view="feed")
    yield node, s, gid, tmp_path
    await s.close()
    server.close()


def test_items_are_checked_and_kept(tmp_path):
    s = Session(Vault.open(tmp_path / "v.vault", "pw", **KDF), status=lambda *_: None)
    path = tmp_path / "queue.json"
    q = s.posting_queue(path)
    with pytest.raises(SessionError, match="group"):
        q.add({"subject": "x", "body": "y"})
    with pytest.raises(SessionError, match="subject"):
        q.add({"group": "g@x", "body": "y"})
    with pytest.raises(SessionError, match="Origin"):
        q.add({"group": "g@x", "subject": "x", "body": "y", "origin": {"network": "Not OK"}})
    assert q.add({"group": "g@x", "subject": "a", "body": "1", "key": "fb:1", "junk": "dropped"},
                 {"group": "g@x", "body": "2", "kind": "chat"}) == 2
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    again = s.posting_queue(path)
    assert [i.get("key") for i in again.items] == ["fb:1", None] and "junk" not in again.items[0]
    kept = {}
    mine = s.posting_queue(load=lambda: kept.get("q"), save=lambda st: kept.__setitem__("q", st))
    mine.add({"group": "g@x", "subject": "a", "body": "1"})
    assert kept["q"]["items"][0]["body"] == "1" and not (tmp_path / "other.json").exists()
    assert mine.estimate()["left"] == 1


async def test_posts_in_order_with_the_time_of_posting(world):
    node, s, gid, tmp = world
    q = s.posting_queue(tmp / "q.json")
    q.add(*({"group": gid, "subject": f"Post {i}", "body": f"{i}\n", "key": f"src:{i}",
             "origin": {"network": "facebook", "date": "2026-08-0%dT10:00:00Z" % (3 - i)}}
            for i in range(3)))
    seen = []
    left = await q.run()
    assert left["left"] == 0 and [d["key"] for d in q.done] == ["src:0", "src:1", "src:2"]
    for d in q.done:
        art = Article.from_bytes(node.store.get(d["message_id"]))
        assert datetime.now(timezone.utc) - parse_date(art["Date"]) < timedelta(minutes=11)
        assert art["Origin-Network"] == "facebook"
        seen.append(art["Subject"])
    assert seen == ["Post 0", "Post 1", "Post 2"]
    assert json.loads((tmp / "q.json").read_text())["items"] == []


async def test_a_refused_post_is_set_aside_and_the_rest_go_on(world):
    node, s, gid, tmp = world
    q = s.posting_queue()
    q.add({"group": "nowhere@aaaaaaaaaaaaaaaa", "subject": "x", "body": "y\n", "key": "bad"},
          {"group": gid, "subject": "ok", "body": "fine\n", "key": "good"})
    await q.run()
    assert [d["key"] for d in q.done] == ["good"]
    assert q.failed[0]["item"]["key"] == "bad" and q.failed[0]["error"]


async def test_a_quota_waits_for_tomorrow_and_the_network_is_tried_again(world, monkeypatch):
    node, s, gid, tmp = world
    q = s.posting_queue()
    q.add({"group": gid, "subject": "x", "body": "y\n"})

    async def over_quota(*a, **k):
        raise SessionError("rejected by node: quota: too many blob octets today for this key or group")
    monkeypatch.setattr(s, "post", over_quota)
    assert await q.post_one() is None and len(q.items) == 1
    assert q.waiting_until - time.time() > 60 and q.estimate()["until"] == q.waiting_until

    async def offline(*a, **k):
        raise ConnectionError("node unreachable")
    monkeypatch.setattr(s, "post", offline)
    q.waiting_until = 0
    assert await q.post_one() is None and len(q.items) == 1 and q.waiting_until > time.time()
    assert not q.failed

    stops = []

    async def fake_sleep(seconds):
        stops.append(seconds)
        q.stop()
    await q.run(sleep=fake_sleep)
    assert stops and len(q.items) == 1                         # waited, then stopped
