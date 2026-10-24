"""#496: pictures and files where they were forgotten - personal feeds and sites take
pictures by default, groups are created and edited with a files choice, chat lines
carry files (UN-RFC 0028 section 6.1), and an edit keeps the files of the post."""

import io

import pytest

from unseenet.client.session import Session, SessionError
from unseenet.core import blobs as bl
from unseenet.core.article import Article
from unseenet.core.blobs import BlobStore
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def _node(monkeypatch):
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), sites="accept"))
    node.config.blobs = {"max_size": bl.MAX_BLOB}
    node.blobs = BlobStore()
    server = await node.serve("127.0.0.1", 0)
    return node, server, f"127.0.0.1:{server.sockets[0].getsockname()[1]}"


def _session(tmp_path, addr, name="me"):
    s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity(name, name.title())
    s.add_node(addr)
    s.data["starter_groups"] = 99
    return s


def _jpeg(tmp_path, name="have.jpg") -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (20, 120, 50)).save(buf, "JPEG")
    path = tmp_path / name
    path.write_bytes(buf.getvalue())
    return str(path)


def _with_blobs(node):
    for (mid,) in node.store.db.execute("SELECT message_id FROM articles"):
        raw = node.store.get(mid) or b""
        if b"Blobs:" in raw:
            yield Article.from_bytes(raw)


def test_file_choice():
    assert bl.file_choice(None) == "none"
    assert bl.file_choice(bl.PICTURES) == "pictures"
    assert bl.file_choice({"max_size": bl.MAX_BLOB, "types": ["application/pdf", "image/*"]}) \
        == "pictures+pdf"
    assert bl.file_choice({"max_size": 1024}) == "custom"


async def test_personal_feed_and_site_take_pictures_by_default(tmp_path, monkeypatch):
    node, server, addr = await _node(monkeypatch)
    s = _session(tmp_path, addr)
    try:
        feed = await s.start_personal_group("feed")
        assert s.manifest_data(feed)["attachments"] == bl.PICTURES
        site = await s.start_personal_group("site", attachments={})
        assert "attachments" not in s.manifest_data(site)      # {}: none, as asked
        # started again without saying: what the owner chose is kept
        await s.start_personal_group("site")
        assert "attachments" not in (await s.fetch_manifest(site)).raw
        assert s.personal_group_without_files("site") and not s.personal_group_without_files("feed")
        await s.allow_pictures(site)
        assert (await s.fetch_manifest(site)).raw["attachments"] == bl.PICTURES
    finally:
        await s.close()
        server.close()


async def test_chat_lines_carry_files_and_edits_keep_them(tmp_path, monkeypatch):
    node, server, addr = await _node(monkeypatch)
    s = _session(tmp_path, addr)
    try:
        gid = await s.create_group("dk.foto", "open", min_pow=9,
                                   extra={"attachments": bl.PICTURES})
        files = s.prepare_files([_jpeg(tmp_path)])
        chat = await s.send_chat(gid, "Se her", files=files)
        (art,) = [a for a in _with_blobs(node) if a.message_id == chat]
        assert art.get("Message-Kind") == "chat"
        (blob, _), = bl.parse_blobs(art)
        assert node.blobs.get(blob)
        # a post with a picture, then a new version of it: the picture goes along
        await s.fetch_group(gid)
        post = await s.post(gid, "Haven", "Se her\n", files=files)
        await s.fetch_group(gid)
        msg = s.find_message(gid, post)
        new = await s.edit(msg, "Haven", "Se her igen\n")
        (edited,) = [a for a in _with_blobs(node) if a.message_id == new]
        assert [b for b, _ in bl.parse_blobs(edited)] == [blob]
        await s.fetch_group(gid)
        newer = await s.edit(s.find_message(gid, new), "Haven", "Uden billede\n", files=[])
        assert newer not in [a.message_id for a in _with_blobs(node)]
        with pytest.raises(SessionError, match="private chats"):
            other = _session(tmp_path, addr, "other")
            await s.send_chat("contact:" + other.identity().key_text, "Hej", files=files)
    finally:
        await s.close()
        server.close()


async def test_tui_create_group_with_pictures_and_attach_to_a_chat_line(tmp_path, monkeypatch):
    pytest.importorskip("textual")
    from tuihelp import app_ready, press, stack, wait_for
    from unseenet.client.tui import CreateGroupDialog, UnseenetApp
    node, server, addr = await _node(monkeypatch)
    s = _session(tmp_path, addr)
    await s.ensure_inbox()
    await s.close()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(tmp_path / "me.vault")
    picture = _jpeg(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        app.action_create_group()
        assert await wait_for(pilot, lambda: isinstance(app.screen, CreateGroupDialog), 100)
        app.screen.query_one("#name").value = "dk.foto.chat"
        app.screen.query_one("#view").value = "chat"
        app.screen.query_one("#files").value = "pictures"
        await press(pilot, app, "#ok")
        assert await wait_for(pilot, lambda: (app.current_group or "").startswith("dk.foto.chat"),
                              400), [n.message for n in app._notifications]
        gid = app.current_group
        assert await wait_for(pilot, lambda: gid in app.groups, 400), stack(app)
        assert app.session.manifest_data(gid)["attachments"] == bl.PICTURES
        app.select_group(gid)
        assert await wait_for(pilot, lambda: app.current_group == gid and app.view_of(gid) == "chat",
                              200)
        assert app._chat_takes_files(gid)
        app.chat_files[gid] = [picture]
        box = app.query_one("#chat-input")
        box.focus()
        box.value = "Min have"
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: any(a.get("Message-Kind") == "chat"
                                                 for a in _with_blobs(node)), 400)
        assert not app.chat_files.get(gid)
        await pilot.press("escape")
        await pilot.press("q")
    server.close()
