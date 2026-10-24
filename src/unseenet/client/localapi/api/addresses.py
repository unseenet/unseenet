"""``unseenet:`` addresses in the local client API (UN-RFC 0046 section 4.13, UN-RFC 0031
section 3.4.1): the address of a group, a post and an identity in the answers, to copy,
and ``GET /api/address`` to say what any address names - the older forms too - so a
front end can open it. The forms are core.addresses', as in every client."""

from __future__ import annotations

import re

from . import *  # noqa: F403  - the module's names, as when this was one file
from ....core import addresses as addr

_ONION = re.compile(r"^[a-z2-7]{56}\.onion(:\d{1,5})?$")      # what an n= hint may be


def _hints(s: Session, gid: str | None) -> list[str]:
    """The node this client reads a group from, as an ``n=`` hint - only an onion
    address, which is what others can reach."""
    node = s.node_for(gid) if gid else None
    return [node] if node and _ONION.match(node.lower()) else []


def group_address(s: Session, gid: str) -> str:
    return addr.group_address(gid, _hints(s, gid))


def post_address(s: Session, gid: str, message_id: str) -> str:
    return addr.post_address(gid, message_id, _hints(s, gid))


def identity_address(key: str) -> str:
    return addr.identity_address(crypto.fingerprint(crypto.key_from_text(key)))


class Addresses:
    @staticmethod
    def _key_for_fingerprint(s: Session, fp: str) -> str | None:
        """A key this client knows with that fingerprint: yours, a contact's, someone
        you follow, or an author you have read."""
        known = [s.identity(n).key_text for n in s.data["identities"]]
        known += list(s.data.get("contacts", {}))
        known += [p.get("key") for p in s.data.get("following", {}).get("people", {}).values()]
        known += [m.author_key for g in s.cache.values() for m in g.values()]
        for key in dict.fromkeys(k for k in known if k):
            try:
                if crypto.fingerprint(crypto.key_from_text(key)) == fp:
                    return key
            except crypto.CryptoError:
                continue
        return None

    async def address(self, text: str) -> dict:
        """``GET /api/address?a=...`` (section 4.13): what an ``unseenet:`` address names -
        an identity, a group, a post or a page - and whether you have it, fetched from
        your nodes. Its ``n=`` hints are given back, never used by themselves."""
        s = self._ready()
        try:
            a = addr.parse(str(text or ""))
        except addr.AddressError as exc:
            raise SessionError(f"not an address: {exc}") from None
        try:
            web = addr.web_address(a)
        except addr.AddressError:
            web = None
        out: dict = {"kind": a.kind, "address": str(a), "web": web, "nodes": list(a.nodes)}
        if a.kind == "identity":
            key = self._key_for_fingerprint(s, a.fingerprint)
            return {**out, "fingerprint": a.fingerprint, "key": key,
                    "label": s.label_of(key) if key else None,
                    "mine": a.fingerprint in s.my_fingerprints()}
        gid = a.group_id
        followed = gid in s.data["subscribed"] or gid in s.data["groups"]
        out.update({"group_id": gid, "followed": followed})
        manifest = None
        with contextlib.suppress(*NETWORK_ERRORS):
            manifest = await s.fetch_manifest(gid)
        data = manifest.raw if manifest is not None else (s.manifest_data(gid) if followed else {})
        if not data:
            return {**out, "available": False}
        out["available"] = True
        out["group"] = {"id": gid, "label": s.group_label(gid), "title": data.get("title", ""),
                        "type": data.get("type"), "view": data.get("view")}
        if a.kind in ("post", "page"):
            with contextlib.suppress(*NETWORK_ERRORS):
                await s.fetch_group(gid)
        if a.kind == "post":
            m = s.find_message(gid, a.message_id)
            out["message"] = None if m is None else {
                "id": m.message_id, "subject": m.subject, "kind": m.kind,
                "who": s.identity_label(m.author_key, m.from_name) if m.author_key else None,
                "date": m.date.isoformat() if m.date else None}
        elif a.kind == "page":
            page = next((p for p in s.site(gid)["pages"] if p["path"] == a.path), None)
            out["page"] = None if page is None else {"path": a.path, "title": page["title"]}
        return out
