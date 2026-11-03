"""Pipelining (#916): the articles of a turn, headers and files asked for at once, one
round trip over Tor instead of one each - and a connection broken off part-way is never
used again. Against a fake node that answers only once it has every command."""

import asyncio

import pytest

import unseenet.client.session as sess
from unseenet.client.runtime import ClientRuntime
from unseenet.client.session import Session
from unseenet.nntp import Client, NNTPError


def _article(n) -> bytes:
    return f"Message-ID: <{n}@x>\r\nSubject: {n}\r\n\r\nbody {n}\r\n".encode()


async def _fake_node(answer, wait_for: int):
    """A node that reads ``wait_for`` commands before it answers any - a client sending
    them one at a time would wait for ever - then writes ``answer(i, line)`` for each
    (bytes; None closes the connection there)."""
    seen: list[str] = []

    async def handle(reader, writer):
        writer.write(b"200 fake\r\n")
        await writer.drain()
        lines = []
        while len(lines) < wait_for:
            line = await reader.readline()
            if not line:
                return
            lines.append(line.decode().strip())
        seen.extend(lines)
        for i, line in enumerate(lines):
            out = answer(i, line)
            if out is None:
                writer.close()
                return
            writer.write(out)
        await writer.drain()
        await reader.read()                      # until the client goes
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", port)
    c = Client(r, w)
    assert (await c._response())[0] == 200
    return server, c, seen


def _ok(i, line):
    n = line.split()[1]
    return b"220 " + n.encode() + b" <x>\r\n" + _article(n) + b".\r\n"


async def test_articles_go_at_once():
    server, c, seen = await _fake_node(_ok, wait_for=5)
    got = await asyncio.wait_for(c.articles([str(n) for n in range(1, 6)]), 5)
    assert seen == [f"ARTICLE {n}" for n in range(1, 6)]
    assert [g.split(b"\r\n")[1] for g in got] == [f"Subject: {n}".encode() for n in range(1, 6)]
    c.writer.close()
    server.close()


async def test_a_missing_article_in_the_middle():
    def answer(i, line):
        return b"430 no such article\r\n" if i == 2 else _ok(i, line)
    server, c, _ = await _fake_node(answer, wait_for=5)
    got = await asyncio.wait_for(c.articles([str(n) for n in range(1, 6)]), 5)
    assert got[2] is None and all(g is not None for i, g in enumerate(got) if i != 2)
    assert await asyncio.wait_for(c.articles([]), 1) == []      # still in step, still open
    assert not c.writer.is_closing()
    c.writer.close()
    server.close()


async def test_the_node_closes_part_way():
    server, c, _ = await _fake_node(lambda i, line: None if i == 2 else _ok(i, line), wait_for=5)
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(c.articles([str(n) for n in range(1, 6)]), 5)
    assert c.writer.is_closing()                 # never used again
    server.close()


async def test_an_answer_out_of_step_drops_the_connection():
    server, c, _ = await _fake_node(lambda i, line: b"garbage\r\n" if i == 1 else _ok(i, line),
                                    wait_for=3)
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(c.articles(["1", "2", "3"]), 5)
    assert c.writer.is_closing()
    server.close()


async def test_full_is_still_full():
    server, c, _ = await _fake_node(lambda i, line: b"400 too many connections\r\n", wait_for=2)
    with pytest.raises(NNTPError) as e:
        await asyncio.wait_for(c.articles(["1", "2"]), 5)
    assert e.value.code == 400 and c.writer.is_closing()
    server.close()


async def test_heads_and_blobs():
    def answer(i, line):
        cmd, arg = line.split()
        if cmd == "HEAD":
            return b"430 no\r\n" if arg == "2" else b"221 " + arg.encode() + b" <x>\r\nSubject: s\r\n.\r\n"
        return {"a": b"226 3\r\nabc", "b": b"430 no\r\n", "c": b"436 later\r\n"}[arg]
    server, c, _ = await _fake_node(answer, wait_for=3)
    heads = await asyncio.wait_for(c.heads(["1", "2", "3"]), 5)
    assert heads[0] == ["Subject: s"] and heads[1] is None
    c.writer.close()
    server.close()
    server, c, _ = await _fake_node(answer, wait_for=3)
    blobs = await asyncio.wait_for(c.blobs(["a", "b", "c"]), 5)
    assert blobs[0] == b"abc" and blobs[1] is None
    assert isinstance(blobs[2], NNTPError) and blobs[2].code == 436
    c.writer.close()
    server.close()


class _Runtime:
    """The part of ClientRuntime._fetch needs."""
    def __init__(self, order):
        self.order = order
        self.reading_now = None

    def is_slow(self, node):
        return False

    def node_for(self, gid):
        return "n"

    async def fetch_group(self, gid):
        self.order.append(gid)
        if gid == "a":                                       # the reader opens "d" meanwhile
            self.reading_now = "d"


async def test_the_open_group_comes_first():
    order: list = []
    rt = ClientRuntime.__new__(ClientRuntime)
    rt.session = _Runtime(order)
    done = await rt._fetch(["a", "b", "c", "d", "e"])
    assert order == ["a", "d", "b", "c", "e"]
    assert done == set("abcde")


async def test_a_broken_turn_keeps_the_turns_before(tmp_path, monkeypatch):
    s = Session.__new__(Session)
    calls = []

    async def call(fn, node=None):
        calls.append(node)
        if len(calls) > 1:
            raise ConnectionError("gone")

        class C:
            async def group(self, gid):
                return 3, 1, 3

            async def articles(self, idents):
                return [_article(i) for i in idents]
        return await fn(C())
    monkeypatch.setattr(Session, "FETCH_BATCH", 2)
    s._call = call
    fetched, stopped = await s._fetch_numbers("g", [1, 2, 3, 4], "n")
    assert [n for n, _ in fetched] == [1, 2] and stopped == 3


async def test_files_asked_together_go_together(monkeypatch):
    s = Session.__new__(Session)
    lock = asyncio.Lock()
    asked: list = []

    class C:
        def capability(self, name):
            return ""

        async def blob(self, b):
            asked.append([b])
            await asyncio.sleep(0.02)                         # a round trip
            return b.encode()

        async def blobs(self, ids):
            asked.append(list(ids))
            await asyncio.sleep(0.02)
            return [None if b == "gone" else NNTPError(436, "later") if b == "late"
                    else b.encode() for b in ids]

    async def call(fn, node=None):
        async with lock:
            return await fn(C())
    s._call = call
    monkeypatch.setattr(Session, "BLOB_BATCH", 3)
    first = asyncio.ensure_future(s._blob_from("n", "x"))     # asked alone, as before
    await asyncio.sleep(0.005)                                # its turn has begun
    rest = [asyncio.ensure_future(s._blob_from("n", b))       # come while the node is busy
            for b in ("a", "b", "gone", "late", "c", "a")]
    got = await asyncio.gather(first, *rest)
    assert got == [b"x", b"a", b"b", None, "later", b"c", b"a"]
    assert asked == [["x"], ["a", "b", "gone"], ["late", "c"]]   # three turns, not seven


async def test_a_file_not_reached_tells_everyone_waiting():
    s = Session.__new__(Session)

    async def call(fn, node=None):
        raise sess.SessionError("not answering yet")
    s._call = call
    got = await asyncio.gather(s._blob_from("n", "a"), s._blob_from("n", "b"),
                               return_exceptions=True)
    assert all(isinstance(g, sess.SessionError) for g in got)
    assert not s._blob_waiting                                # nothing left behind
