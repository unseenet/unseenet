"""#538: a folder of Markdown (and HTML) as a site's pages - the plan (no network),
then publishing through a node: only what changed is sent."""
import io
import json
from argparse import Namespace

import pytest

from unseenet import cli
from unseenet.client import siteimport as si
from unseenet.core import blobs as bl
from unseenet.core.article import Article
from unseenet.core.blobs import BlobStore
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

BITS = 8
KDF = {"ops": 1, "mem": 8192 * 1024}
FILES = {"attachments": {"max_size": 1048576, "types": ["image/*"]}}


def _jpeg(size=(60, 40), secret="SecretCam") -> bytes:
    from PIL import Image
    img = Image.new("RGB", size, (90, 160, 60))
    ex = Image.Exif()
    ex[0x010F] = secret
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=ex)
    return buf.getvalue()


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "site"
    (f / "Guide").mkdir(parents=True)
    (f / "pics").mkdir()
    (f / "_drafts").mkdir()
    (f / "pics" / "garden.jpg").write_bytes(_jpeg())
    (f / "index.md").write_text("---\ntitle: \"Our garden\"\n---\n# Welcome\n\n"
                                "See [the first steps](Guide/First%20Steps.md) and "
                                "[the list](plants.html#roses).\n\n<b>Bold</b> words.\n\n"
                                "![the garden in May](pics/garden.jpg)\n")
    (f / "Guide" / "First Steps.md").write_text("# First steps\n\nBack [home](../index.md), "
                                                "a [broken one](nowhere.md), and "
                                                "[out](https://example.org).\n")
    (f / "plants.html").write_text("<html><head><title>Plants</title><script>evil()</script>"
                                   "</head><body><h1>Plants</h1><table><tr><th>Name</th><th>Colour</th>"
                                   "</tr><tr><td>Rose</td><td>red</td></tr></table></body></html>")
    (f / "_drafts" / "secret.md").write_text("# not this\n")
    (f / "notes.md").write_text("# ignored by .siteignore\n")
    (f / ".siteignore").write_text("# not published\nnotes.md\n")
    return f


def test_the_plan(folder):
    plan = si.plan(folder, FILES)
    assert plan.ok, plan.problems
    paths = {p.path: p for p in plan.pages}
    assert set(paths) == {"index", "guide/first-steps", "plants"}        # ignored ones left out
    home = paths["index"]
    assert home.title == "Our garden"                                   # front matter
    assert "[the first steps](/guide/first-steps)" in home.text
    assert "[the list](/plants#roses)" in home.text
    assert "**Bold**" in home.text and "<b>" not in home.text           # raw HTML turned
    (pic,) = home.files
    assert f"](blob1:" in home.text and bl.blob_id(pic.octets) in home.text
    assert b"SecretCam" not in pic.octets                               # metadata gone
    assert "[home](/index)" in paths["guide/first-steps"].text
    assert "[out](https://example.org)" in paths["guide/first-steps"].text
    assert "broken one" in paths["guide/first-steps"].text and "nowhere" not in paths["guide/first-steps"].text
    plants = paths["plants"]
    assert plants.title == "Plants" and "| Rose | red |" in plants.text and "evil" not in plants.text
    notes = " ".join(str(n) for n in plan.notes)
    assert "nowhere.md: no such page" in notes and "script" in notes and "HTML turned" in notes


def test_what_stops_or_leaves_out(folder):
    plan = si.plan(folder, {})                                          # takes no files
    assert plan.ok and "the site takes no files" in " ".join(map(str, plan.notes))
    assert not si.plan(folder, {"max_pages": 2}).ok                     # 3 pages
    assert si.slug("Første Skridt!") == "forste-skridt"


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(cli, "DEFAULT_POW", BITS)
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", BITS)
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), sites="accept"))
    node.config.blobs = {"max_size": 1048576}
    node.blobs = BlobStore()
    server = await node.serve("127.0.0.1", 0)
    a = cli.App(Vault.open(tmp_path / "me.vault", "pw", **KDF))
    a.data["nodes"].append(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    await cli.c_id_new(a, Namespace(name="me", display=None))
    yield node, a
    if a._session is not None:
        await a._session.close()
    server.close()


def _args(**kw):
    base = dict(identity=None, json=True, subject=None, body="", kind="post", reply_to=None,
                edit=None, format=None, attach=None, publish_outside_tor=False, local=False,
                moderator=None, poster=None, title=None, description=None, min_pow=BITS,
                retention_days=None, view=None, kinds=None, rules=None, comments=None,
                comment_days=None, attachments=None, types=None, max_pins=None, max_pages=None,
                home=None, note=None, unpin=False, yes=True, dry_run=False, prune=False)
    return Namespace(**(base | kw))


async def test_publishing_sends_only_what_changed(setup, folder, capsys):
    node, me = setup
    await cli.c_group_create(me, _args(name="dk.have", type="channel", view="pages",
                                       attachments=1048576, types="image/*"))
    gid = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["group"]
    s = me._session
    first = await s.publish_site(gid, folder)
    assert first["sent"] == 3 and not first["problems"]
    site = {p["path"]: p["current"] for p in s.site(gid)["pages"]}
    art = Article.from_bytes(node.store.get(site["index"].message_id))
    (bid, _), = bl.parse_blobs(art)
    assert bid in art.body and b"SecretCam" not in node.blobs.get(bid)

    again = await s.publish_site(gid, folder)                          # the same folder
    assert again["sent"] == 0 and {c["action"] for c in again["changes"]} == {"unchanged"}

    (folder / "plants.html").unlink()
    (folder / "Guide" / "First Steps.md").write_text("# First steps\n\nNow different.\n")
    dry = await s.publish_site(gid, folder, dry_run=True, prune=True)
    actions = {c["path"]: c["action"] for c in dry["changes"]}
    # the home page links to plants.html, now gone: its link became text, so it changed too
    assert actions == {"index": "changed", "guide/first-steps": "changed", "plants": "remove"}
    assert dry["sent"] == 0 and any("plants.html" in n for n in dry["notes"])
    done = await s.publish_site(gid, folder, prune=True)
    assert done["sent"] == 3
    pages = {p["path"]: p["current"] for p in s.site(gid)["pages"]}
    assert set(pages) == {"index", "guide/first-steps"}
    assert pages["guide/first-steps"].supersedes                       # a new version (0042)


async def test_the_cli(setup, folder, capsys):
    node, me = setup
    await cli.c_group_create(me, _args(name="dk.have2", type="channel", view="pages"))
    gid = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["group"]
    await cli.c_site_publish(me, _args(group=gid, folder=str(folder), dry_run=True))
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["sent"] == 0 and len(out["changes"]) == 3
    await cli.c_site_publish(me, _args(group=gid, folder=str(folder)))
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["sent"] == 3


async def test_the_local_api(setup, folder, capsys):
    import asyncio
    from unseenet.client.localapi import LocalAPI
    node, me = setup
    await cli.c_group_create(me, _args(name="dk.have3", type="channel", view="pages"))
    gid = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["group"]
    api = LocalAPI(session=me._session)
    dry = await api.publish_folder(gid, {"folder": str(folder)})
    assert dry["sent"] == 0 and {c["action"] for c in dry["changes"]} == {"new"}
    job = (await api.publish_folder(gid, {"folder": str(folder), "dry_run": False}))["job"]
    for _ in range(100):
        if len(me._session.site(gid)["pages"]) == 3:
            break
        await asyncio.sleep(0.05)
    assert job and len(me._session.site(gid)["pages"]) == 3
