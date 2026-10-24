"""#442: sites and pages in the local client API (UN-RFC 0046 section 4.15, UN-RFC 0035),
against a real node: starting your site, writing pages as jobs, the pages in force with
the home page first, a page with its links within the site resolved, going back to the
previous version, removing a page, and refusing other writers."""

import asyncio

import pytest

import unseenet.client.session as sess
from unseenet.client.localapi import LocalAPI, NotFound
from unseenet.client.session import Session, SessionError
from unseenet.core import pages as pg
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


async def _setup(tmp_path, monkeypatch):
    """As test_localapi_owner's, with a node that carries sites (UN-RFC 0035 section 6.2)."""
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0), sites="accept"))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"

    def session(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        return s
    owner, other = session("owner"), session("other")
    return server, owner, other, LocalAPI(session=owner)


async def _jobs(api, events) -> None:
    while api._tasks:
        await asyncio.gather(*list(api._tasks), return_exceptions=True)


def _links(nodes):
    for n in nodes:
        if n.get("t") == "link":
            yield n["href"]
        for k in ("c", "items"):
            for sub in (n.get(k) or []):
                yield from _links(sub if isinstance(sub, list) else [sub])


def test_links_within_a_site():
    assert pg.resolve_link("projects/ovos", "skills") == "projects/skills"
    assert pg.resolve_link("projects/ovos", "/about#team") == "about"
    assert pg.resolve_link("a", "../../b") == "b"                # never above the site
    assert pg.resolve_link("a", "..") is None
    assert pg.resolve_link("a", "Bad Path") is None


async def test_a_site_its_pages_and_versions(tmp_path, monkeypatch):
    server, owner, other, api = await _setup(tmp_path, monkeypatch)
    events = []
    api._job_event = lambda job, group, state, **more: events.append((state, more))
    mine = api.my_feed("site")
    assert mine["started"] is False and "public" in mine["warning"]
    gid = (await api.start_feed({"title": "Min side"}, "site"))["id"]
    assert gid == mine["id"] and api.my_feed("site")["started"]

    api.write_page(gid, {"path": "index", "title": "Velkommen",
                         "text": "# Hej\n\nSe [om mig](about) og [nyt](/news/one#top).\n"})
    api.write_page(gid, {"path": "about", "title": "Om mig", "text": "Første udgave\n"})
    await _jobs(api, events)
    api.write_page(gid, {"path": "about", "title": "Om mig", "text": "Anden udgave\n"})
    await _jobs(api, events)
    assert [s for s, _ in events].count("sent") == 3, events

    site = api.site(gid)
    assert site["home"] == "index" and site["may_write"] and site["title"] == "Min side"
    assert [(p["path"], p["home"]) for p in site["pages"]] == [("index", True), ("about", False)]
    assert site["address"].startswith("unseenet:") and "p=index" in site["address"]
    about = next(p for p in site["pages"] if p["path"] == "about")
    assert about["title"] == "Om mig" and about["previous"] is True

    pre = api.write_page(gid, {"path": "news/one", "text": "[op](../index)", "preview": True})
    assert list(_links(pre["tree"])) == [f"unseenet:{gid}?p=index"]   # nothing written
    home = api.page(gid)                                       # the home page by default
    assert home["path"] == "index" and home["title"] == "Velkommen"
    links = list(_links(home["row"]["tree"]))
    assert links == [f"unseenet:{gid}?p=about", f"unseenet:{gid}?p=news/one"]
    page = api.page(gid, "about")
    assert page["row"]["message"]["text"].startswith("Anden") and page["previous"]["id"]

    api.write_page(gid, {"path": "about", "restore": True})    # back to the first version
    await _jobs(api, events)
    assert api.page(gid, "about")["row"]["message"]["text"].startswith("Første")

    api.write_page(gid, {"path": "about", "remove": True})
    await _jobs(api, events)
    assert [p["path"] for p in api.site(gid)["pages"]] == ["index"]
    with pytest.raises(NotFound):
        api.page(gid, "about")
    with pytest.raises(SessionError):
        api.write_page(gid, {"path": "Bad Path", "text": "x"})
    with pytest.raises(SessionError, match="some text"):
        api.write_page(gid, {"path": "tom", "text": "  "})

    other.subscribe(gid)
    await other.fetch_group(gid)
    theirs = LocalAPI(session=other)
    assert theirs.site(gid)["may_write"] is False
    assert [p["path"] for p in theirs.site(gid)["pages"]] == ["index"]
    with pytest.raises(SessionError, match="writers"):
        theirs.write_page(gid, {"path": "index", "text": "Mit\n"})
    api.set_view(gid, "threads")
    api.set_view(gid, "pages")
    plain = (await api.create_group({"name": "dk.ikkeside", "type": "open"}))["id"]
    with pytest.raises(SessionError, match="not a site"):
        api.site(plain)
    with pytest.raises(SessionError, match="only a site"):
        api.set_view(plain, "pages")
    await owner.close()
    await other.close()
    server.close()
