"""'Add my entrance' and the daily check of web entrances (unseenet-entrance#3):
the form, the signed versions, the checks against a small local entrance, and the
daily rules - without Tor or the internet."""

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # before running it: dataclasses look it up
    spec.loader.exec_module(mod)
    return mod


ec = _load("entrance_check")
er = _load("entrance_request")
eh = _load("entrance_health")

from unseenet.core import crypto  # noqa: E402
from unseenet.core.article import new_article  # noqa: E402
from unseenet.core.groups import make_manifest  # noqa: E402

OPERATOR = crypto.Identity.generate().key_text
ONION = "b" * 56 + ".onion"
BODY = f"""### Entrance name

my-entrance

### Open-web address

https://203.0.113.7

### Onion address

{ONION}

### Operator key

{OPERATOR}

### Contact (optional)

_No response_

### Description

A small entrance in Frankfurt

### As the operator

- [X] I run this entrance and intend to keep it running for a while.
- [X] The entrance follows UN-RFC 0043 section 5 - in memory only, no logs.
"""


def test_the_form():
    f = er.parse_issue(BODY)
    assert f["url"] == "https://203.0.113.7/" and f["onion"] == ONION and f["promised"] == "yes"
    assert er.validate(f) == []
    bad = er.parse_issue(BODY.replace("https://203.0.113.7", "http://x/path")
                         .replace(ONION, "nope.onion").replace("- [X] The entrance", "- [ ] The entrance"))
    errors = " ".join(er.validate(bad))
    assert "Open-web address" in errors and "Onion address" in errors and "section 5" in errors
    none = er.parse_issue(BODY.replace("https://203.0.113.7", "_No response_").replace(ONION, "_No response_"))
    assert any("or both" in e for e in er.validate(none))


def test_the_challenge():
    c = er.new_challenge("unseenet/unseenet", 7)
    comments = [{"user": {"login": "someone"}, "body": c.replace("#7", "#8")},
                {"user": {"login": er.BOT}, "body": "Hi\n" + c}]
    assert er.find_challenge(comments, "unseenet/unseenet", 7) == c
    assert er.find_challenge(comments[:1], "unseenet/unseenet", 7) is None
    assert f'ENTRANCE_CLAIM="{c}"' in er.how_to_prove(c)


def test_already_listed():
    assert er.listed({"url": "https://129.151.209.26/"}) == "unseenet-entrance-1"
    assert er.listed({"url": "https://203.0.113.7/", "onion": ONION}) is None


# --- signed versions --------------------------------------------------------------

def _bundle(owner, poster, versions, other=None):
    m = make_manifest(owner, "unseenet.releases", "channel", posters=[poster.key_text], pow_bits=8)
    posts = []
    for v, files in versions.items():
        body = f"Unseenet web client {v}\n\nBuilt from x.\n\n" + "".join(
            f"{h}  {p}\n" for p, h in files.items())
        a = new_article(m.group, f"Web client {v}", body)
        a.finalize(other or poster, 8)
        posts.append(base64.b64encode(a.to_bytes()).decode())
    return {"v": 1, "group": m.group, "manifest": base64.b64encode(m.to_bytes()).decode(),
            "posts": posts}, m.group


def test_signed_versions_only_from_the_pinned_owner_and_its_posters():
    owner, poster, stranger = (crypto.Identity.generate() for _ in range(3))
    files = {"index.html": "0" * 64, "pyodide/x.wasm": "1" * 64}
    b, group = _bundle(owner, poster, {"1.2": files})
    assert ec.signed_releases(b, owner.key_text, group) == {"1.2": files}
    with pytest.raises(ValueError, match="not the project"):
        ec.signed_releases(b, stranger.key_text, group)
    b2, _ = _bundle(owner, poster, {"6.6": files}, other=stranger)    # signed by a stranger
    assert ec.signed_releases(b2, owner.key_text, group) == {}


# --- the checks against a small local entrance ------------------------------------

class Entrance:
    """Just enough of an entrance: the well-known, the version, its signed versions,
    its files, and a tunnel that sends a node's greeting."""

    def __init__(self, info, version, files, bundle, greeting=b"200 node ready\r\n"):
        self.info, self.version, self.files, self.bundle = info, version, files, bundle
        self.greeting = greeting

    async def handle(self, r, w):
        line = (await r.readline()).decode()
        headers = {}
        while (h := (await r.readline()).decode().rstrip("\r\n")):
            k, _, v = h.partition(":")
            headers[k.lower()] = v.strip()
        path = line.split()[1]
        if path.startswith("/onntp"):
            accept = base64.b64encode(hashlib.sha1(
                (headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()).decode()
            w.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                     f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
            w.write(bytes([0x82, len(self.greeting)]) + self.greeting)
        else:
            body = {"/.well-known/unseenet-entrance": json.dumps(self.info).encode(),
                    "/version.json": json.dumps({"version": self.version}).encode(),
                    "/.well-known/unseenet-releases.json": json.dumps(self.bundle).encode()
                    }.get(path, self.files.get(path[1:]))
            status = "200 OK" if body is not None else "404 Not Found"
            body = body or b"no"
            w.write(f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
        await w.drain()
        w.close()


async def _check(entrance, **kw):
    server = await asyncio.start_server(entrance.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkey_url = f"http://127.0.0.1:{port}/"
    try:
        return await ec.check_at(monkey_url, socks_port=None, **kw)
    finally:
        server.close()


def _setup(change=False):
    owner, poster = crypto.Identity.generate(), crypto.Identity.generate()
    files = {"index.html": b"<html>client</html>", "pyodide/x.wasm": os.urandom(3000)}
    digests = {p: hashlib.sha256(d).hexdigest() for p, d in files.items()}
    bundle, group = _bundle(owner, poster, {"20261024.1709": digests})
    if change:
        files["pyodide/x.wasm"] = b"something else"
    return owner, group, files, bundle


def test_a_good_entrance_passes(monkeypatch):
    owner, group, files, bundle = _setup()
    monkeypatch.setattr(ec, "PROJECT_KEY", owner.key_text)
    monkeypatch.setattr(ec, "RELEASES_GROUP", group)
    monkeypatch.setattr(ec.signed_releases, "__defaults__", (owner.key_text, group))
    claim = er.new_challenge("unseenet/unseenet", 3)
    e = Entrance({"operator": OPERATOR, "claim": claim}, "20261024.1709", files, bundle)
    r = asyncio.run(_check(e, operator=OPERATOR, claim=claim, node="c" * 56 + ".onion"))
    assert r.problems == [] and r.unchanged is True and r.version == "20261024.1709"


def test_changed_files_a_missing_claim_and_no_tunnel_are_found(monkeypatch):
    owner, group, files, bundle = _setup(change=True)
    monkeypatch.setattr(ec.signed_releases, "__defaults__", (owner.key_text, group))
    e = Entrance({"operator": "ed25519:someone-else"}, "20261024.1709", files, bundle,
                 greeting=b"nope")
    r = asyncio.run(_check(e, operator=OPERATOR, claim="the challenge", node="c" * 56 + ".onion"))
    text = " ".join(r.problems)
    assert r.unchanged is False and "not the file the signed version" in text
    assert "names operator" in text and "challenge" in text and "not a node's greeting" in text


def test_a_version_no_longer_signed(monkeypatch):
    owner, group, files, bundle = _setup()
    monkeypatch.setattr(ec.signed_releases, "__defaults__", (owner.key_text, group))
    e = Entrance({"operator": OPERATOR}, "20261022.0927", files, bundle)
    r = asyncio.run(_check(e, operator=OPERATOR))
    assert r.unchanged is None and any("which no signed post" in p for p in r.problems)


# --- the daily rules ----------------------------------------------------------------

@pytest.fixture
def lists(tmp_path, monkeypatch):
    data = {"v": 1, "updated": "2026-10-20", "entrances": [
        {"name": "ours", "url": "https://198.51.100.1/", "operator": ec.PROJECT_KEY,
         "description": "the project's"},
        {"name": "theirs", "url": "https://203.0.113.7/", "operator": OPERATOR,
         "description": "someone's"},
        {"name": "third", "onion": ONION, "operator": OPERATOR, "description": "onion only"}]}
    path, health = tmp_path / "entrances.json", tmp_path / "health.json"
    path.write_text(json.dumps(data))
    health.write_text(json.dumps({"entrances": {"theirs": {"issue": 12, "requested_by": "bob"}}}))
    monkeypatch.setattr(eh, "ENTRANCES", path)
    monkeypatch.setattr(eh, "HEALTH", health)
    return path, health


def ok():
    return {"problems": [], "changed": False, "outdated": False}


def bad(text="Could not reach it"):
    return {"problems": [text], "changed": False, "outdated": False}


def test_changed_files_are_removed_at_once_but_never_ours(lists):
    path, _ = lists
    changed = {"problems": ["`x` is not the file"], "changed": True, "outdated": False}
    a = eh.update({"ours": changed, "theirs": changed, "third": ok()}, date(2026, 10, 25))
    names = [e["name"] for e in json.loads(path.read_text())["entrances"]]
    assert names == ["ours", "third"] and a["announce"]
    assert a["comments"][0]["issue"] == 12 and "at once" in a["comments"][0]["body"]
    assert any("serves changed files" in i["title"] for i in a["issues"])        # ours: an issue


def test_failing_entrances_get_a_note_then_go(lists):
    path, health = lists
    day = date(2026, 10, 1)
    a = eh.update({"ours": ok(), "theirs": bad(), "third": ok()}, day)
    assert not a["comments"]
    a = eh.update({"ours": ok(), "theirs": bad(), "third": ok()}, date(2026, 10, 4))
    assert a["comments"][0]["issue"] == 12 and "@bob" in a["comments"][0]["body"]
    a = eh.update({"ours": ok(), "theirs": bad(), "third": ok()}, date(2026, 10, 11))
    assert [e["name"] for e in json.loads(path.read_text())["entrances"]] == ["ours", "third"]
    assert a["announce"] and "taken off" in a["comments"][0]["body"]


def test_ours_is_never_removed_for_failing_and_a_pass_forgets(lists):
    path, health = lists
    for d in (1, 4, 12):
        eh.update({"ours": bad(), "theirs": ok(), "third": ok()}, date(2026, 10, d))
    assert len(json.loads(path.read_text())["entrances"]) == 3
    eh.update({"ours": ok(), "theirs": ok(), "third": ok()}, date(2026, 10, 13))
    assert "ours" not in json.loads(health.read_text())["entrances"]


def test_an_old_version_only_gets_a_note(lists):
    path, _ = lists
    old = {"problems": [], "changed": False, "outdated": True}
    for d in (1, 2, 3):
        a = eh.update({"ours": ok(), "theirs": old, "third": ok()}, date(2026, 10, d))
        assert not a["comments"]
    a = eh.update({"ours": ok(), "theirs": old, "third": ok()}, date(2026, 10, 4))
    assert "updates itself" in a["comments"][0]["body"]
    assert len(json.loads(path.read_text())["entrances"]) == 3


def test_when_everything_fails_nothing_is_counted(lists):
    a = eh.update({"ours": bad(), "theirs": bad(), "third": bad()}, date(2026, 10, 1))
    assert "nothing counted" in a["summary"][0] and not a["changed"]
