"""Session: exporting your data (UN-RFC 0049 section 7, #577).

``export(dest)`` writes a zip of what is yours: ``export.json`` (what it holds, from
which nodes, when), ``profile.json`` with ``profile/`` and its picture, ``articles/``
- your own articles one file each, exactly as signed, so anyone can check them
against your key - ``files/`` with the blobs they refer to, ``sites/`` with the pages
of the sites you write in, ``state.json`` (UN-RFC 0044) and a plain ``index.html``.

Never your keys: an export is not a backup of the identity (section 7.2). Private
posts and chats only when asked for, and then the whole export is encrypted with a
passphrase you give (``vault.seal``, UN-RFC 0007), since a readable export of them
would be easier to read than the vault. It holds what the nodes still carry and what
this client has kept - not everything you ever wrote; ``export.json`` and
``index.html`` say so.

Belongs here: gathering and writing. Not here: where to save it (the clients).
"""

from __future__ import annotations

import base64
import html as _html
import io
import json
import zipfile
from datetime import datetime, timezone

from . import *  # noqa: F403  - the shared names: SessionError, Client, ...

NOTE = ("This export holds what the nodes still carry (each keeps articles for its "
        "retention time) and what this client has kept - not everything you ever wrote.")
SEALED_SUFFIX = ".sealed"


def _name(message_id: str) -> str:
    return message_id.strip("<>").replace("/", "_").replace(":", "_") + ".eml"


class ExportMixin:
    def _own_raw(self) -> dict[str, tuple[str, bytes | None]]:
        """{Message-ID: (group, raw article or None)} for your own articles this client
        has: raw ones as fetched (signed), the rest to be fetched by Message-ID."""
        keys = {self.identity(n).key_text for n in self.data["identities"]}
        out: dict[str, tuple[str, bytes | None]] = {}
        for gid, msgs in self.cache.items():
            if gid == getattr(self, "my_inbox", None):
                continue                      # sealed to you by others; private ones apart
            raws = self._raw.get(gid, {})
            for n, m in msgs.items():
                if m.author_key in keys and m.message_id not in out:
                    raw = raws.get(n)
                    out[m.message_id] = (gid, raw if isinstance(raw, (bytes, bytearray)) else None)
        for gid, held in self.reaction_msgs.items():          # reactions are yours too
            raws = self._raw.get(gid, {})
            for n, m in held.items():
                if m.author_key in keys and m.message_id not in out and n >= 0:
                    raw = raws.get(n)
                    out[m.message_id] = (gid, raw if isinstance(raw, (bytes, bytearray)) else None)
        return out

    async def _fetch_raw(self, gid: str, mid: str) -> bytes | None:
        async def get(c: Client):
            return await c.article(mid)
        try:
            return await self._call(get, self.node_for(gid))
        except (OSError, ConnectionError, SessionError, NNTPError, asyncio.IncompleteReadError):
            return None

    async def _fetch_blob_raw(self, gid: str, blob_id: str) -> bytes | None:
        from ...core import blobs as bl

        async def get(c: Client):
            if c.capability("UNSEENET-BLOB") is None:
                return None
            return await c.blob(blob_id)
        try:
            got = await self._call(get, self.node_for(gid))
        except (OSError, ConnectionError, SessionError, NNTPError, asyncio.IncompleteReadError):
            return None
        return got if got is not None and bl.blob_id(got) == blob_id else None

    def _private_conversations(self) -> list[dict]:
        """Private posts and chats, both sides, as the inbox and the sent list hold them."""
        out = []
        for m in self.private_messages():
            if m.kind == "reaction" or not m.readable:
                continue
            out.append({"id": m.message_id, "from": m.author_key or "anonymous",
                        "from_name": m.from_name, "to": m.to_key,
                        "date": m.date.isoformat() if m.date else None, "kind": m.kind,
                        "subject": m.subject, "body": m.body, "references": list(m.references)})
        return out

    async def export(self, dest, *, private: bool = False, passphrase: str | None = None,
                     progress=None) -> dict:
        """Write an export to ``dest`` (a zip; with ``private``, encrypted with
        ``passphrase`` and named ``….zip.sealed``). Answers ``{"path", "articles",
        "files", "sites", "private", "encrypted", "missing", "note"}``. ``progress(done,
        total)`` is called while articles and files are gathered."""
        from pathlib import Path
        from ...core import blobs as bl
        from ...core import profiles as prof
        from ...core.article import Article
        from ...core.vault import seal
        if private and not (passphrase or "").strip():
            raise SessionError("an export with private messages needs a passphrase to encrypt it")
        me = self.identity()
        made = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        own = self._own_raw()
        buf = io.BytesIO()
        z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
        index = {"articles": [], "files": [], "sites": [], "missing": []}
        total, done = len(own), 0
        blobs_of: dict[str, str] = {}
        for mid, (gid, raw) in own.items():
            if raw is None:
                raw = await self._fetch_raw(gid, mid)
            done += 1
            if progress is not None:
                progress(done, total)
            if raw is None:
                index["missing"].append(mid)
                continue
            z.writestr("articles/" + _name(mid), bytes(raw))
            index["articles"].append({"id": mid, "group": gid, "file": "articles/" + _name(mid)})
            try:
                for bid, _size in bl.parse_blobs(Article.from_bytes(bytes(raw))):
                    blobs_of.setdefault(bid, gid)
            except Exception:
                pass
        for bid, gid in blobs_of.items():
            got = await self._fetch_blob_raw(gid, bid)
            if got is None:
                index["missing"].append(bid)
                continue
            path = "files/" + bid.replace(":", "_")
            z.writestr(path, got)
            index["files"].append({"id": bid, "file": path})
        # the sites you write in: the pages in force, as articles (UN-RFC 0035)
        for gid in list(self.data.get("subscribed", [])):
            data = self.manifest_data(gid)
            if data.get("view") != "pages" or me.key_text not in (
                    [data.get("owner")] + list(data.get("moderators", [])) + list(data.get("posters", []))):
                continue
            pages = []
            for p in self.site(gid)["pages"]:
                cur = p["current"]
                raw = own.get(cur.message_id, (gid, None))[1] or self._raw.get(gid, {}).get(cur.number)
                if not isinstance(raw, (bytes, bytearray)):
                    raw = await self._fetch_raw(gid, cur.message_id)
                if raw is None:
                    index["missing"].append(cur.message_id)
                    continue
                path = f"sites/{gid.replace('@', '_')}/{p['path']}.eml"
                z.writestr(path, bytes(raw))
                pages.append({"path": p["path"], "title": p["title"], "file": path})
            index["sites"].append({"group": gid, "title": data.get("title", ""), "pages": pages})
        # the profile and its picture (UN-RFC 0022)
        profile = self.my_profile() or {}
        picture = self.my_picture()
        if picture:
            ext = {"image/webp": "webp", "image/jpeg": "jpg", "image/png": "png"}.get(
                picture.get("type", ""), "img")
            try:
                z.writestr(f"profile/picture.{ext}", base64.urlsafe_b64decode(
                    picture["data"] + "=" * (-len(picture["data"]) % 4)))
            except (KeyError, ValueError):
                pass
        z.writestr("profile.json", json.dumps({"key": me.key_text, "fingerprint": me.fingerprint,
                                               "name": self.display_name(), "profile": profile},
                                              indent=2, ensure_ascii=False))
        z.writestr("state.json", json.dumps(self.local_state(), indent=2, ensure_ascii=False,
                                            default=str))
        conversations = self._private_conversations() if private else []
        if private:
            z.writestr("private.json", json.dumps(conversations, indent=2, ensure_ascii=False))
        info = {"version": 1, "fingerprint": me.fingerprint, "key": me.key_text, "made": made,
                "nodes": list(self.nodes), "note": NOTE, "private": private,
                "index": {**index, "private": len(conversations)}}
        z.writestr("export.json", json.dumps(info, indent=2, ensure_ascii=False))
        z.writestr("index.html", _index_html(self.display_name(), me.fingerprint, made, info,
                                             profile))
        z.close()
        payload = buf.getvalue()
        dest = Path(dest)
        if private:
            if not dest.name.endswith(SEALED_SUFFIX):
                dest = dest.with_name(dest.name + SEALED_SUFFIX)
            payload = await asyncio.to_thread(seal, payload, passphrase)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        return {"path": str(dest), "articles": len(index["articles"]), "files": len(index["files"]),
                "sites": len(index["sites"]), "private": len(conversations),
                "encrypted": private, "missing": len(index["missing"]), "note": NOTE}


def _index_html(name, fp, made, info, profile) -> str:
    e = _html.escape
    rows = "".join(f"<li><a href=\"{e(a['file'])}\">{e(a['id'])}</a> <small>{e(a['group'])}</small></li>"
                   for a in info["index"]["articles"])
    sites = "".join(f"<li>{e(s['group'])}: " + ", ".join(
        f"<a href=\"{e(p['file'])}\">{e(p['path'])}</a>" for p in s["pages"]) + "</li>"
                    for s in info["index"]["sites"])
    return (f"<!doctype html><meta charset=utf-8><title>Unseenet export: {e(name)}</title>"
            f"<h1>Unseenet export: {e(name)}</h1><p>Key {e(info['key'])} ({e(fp)}), made {e(made)} "
            f"from {e(', '.join(info['nodes']))}.</p><p><b>{e(NOTE)}</b></p>"
            f"<p>The articles are kept exactly as signed: anyone can check them against the key. "
            f"No secret keys are in this export.</p>"
            f"<h2>Profile</h2><pre>{e(json.dumps(profile, indent=2, ensure_ascii=False))}</pre>"
            f"<h2>Articles ({len(info['index']['articles'])})</h2><ul>{rows}</ul>"
            f"<h2>Sites</h2><ul>{sites or '<li>none</li>'}</ul>"
            f"<h2>Files</h2><p>{len(info['index']['files'])} in files/.</p>"
            + (f"<h2>Private messages</h2><p>{info['index']['private']} in private.json.</p>"
               if info["private"] else "")
            + "<h2>State</h2><p>state.json: the groups you follow, your contacts and closed "
              "chats (UN-RFC 0044).</p>")
