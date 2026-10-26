"""Session: your state in the network (UN-RFC 0044) - built from the vault, merged with
what the network has, and written back at most once an hour.

The state follows the vault's default identity: it is that identity's ``state@<fp>``.
Rather than every change noting its own time, ``sync_state`` compares what the vault
holds now with what it held at the last sync (``data["state_seen"]``) and stamps what
changed with the current time; merging then lets the newest entry win, so two
clients never undo each other. What the merged state says is put back in the vault.
An identity whose state is kept local writes nothing (section 7.4).

Belongs here: building the state from the vault, merging it with the network's,
putting it back, writing it, and keeping it local. The protocol (sealing, merging
rules) is in ``core/state.py``.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

from . import *  # noqa: F403  - the shared names: SessionError, NNTPError, ...
from ...core import state as st

WRITE_EVERY = 3600.0              # section 7.1: at most once an hour
SETTINGS = ("show_pictures", "show_blocked", "hide_bots", "private_min_ripe", "mention_notices",
            "notifications",      # whether, and how, clients tell you of what is new
            "clients")                # each client's own: the TUI's theme, the GUI's (UN-RFC 0044, 4.2)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(d) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if d else ""


class StateMixin:
    # --- keeping it local (section 7.4) ---
    def state_kept_local(self, name: str | None = None) -> bool:
        """True when this identity's state stays in the vault only."""
        name = name or self.default_identity_name()
        return self.data["identities"].get(name, {}).get("state") == "local"

    async def set_state_kept_local(self, local: bool, name: str | None = None) -> None:
        """Keep the state in the vault only, or in the network (the default). Turning
        it local removes the state group, so the last state written does not linger."""
        name = name or self.default_identity_name()
        self.data["identities"][name]["state"] = "local" if local else "network"
        self.save()
        gid = st.state_id(self.identity(name).public_key)
        if local and self.data["groups"].get(gid, {}).get("owner"):
            try:
                await self.remove_group(gid, "kept local from now on")
            except (SessionError, OSError, ConnectionError, NNTPError, asyncio.IncompleteReadError):
                pass                        # it expires by itself anyway (UN-RFC 0029)

    # --- what the vault holds, as a state ---
    def _snapshot(self) -> dict:
        """The vault's state now, without times."""
        d = self.data
        name = self.default_identity_name()
        sig = d["identities"].get(name, {}).get("signature")
        settings = {k: d[k] for k in SETTINGS if k in d}
        if sig is not None:
            settings["signature"] = sig
        starter = d.get("starter_groups")
        return {
            "subscribed": {g: True for g in d["subscribed"]},
            "following": {fp: {k: p[k] for k in ("key", "name", "feeds", "skip") if k in p}
                          for fp, p in d.get("following", {}).get("people", {}).items()},
            "contacts": {k: {"name": v.get("name", "")} for k, v in d["contacts"].items()},
            "ignored": {k: {"label": v.get("label", "")} for k, v in d["ignored"].items()},
            "hidden": {k: True for k in d.get("hidden_profiles", [])},
            "closed_chats": {k: {"since": v} for k, v in d.get("closed_chats", {}).items()},
            "starter": 1 if starter is True else int(starter or 0),
            "settings": settings,
            "read": self._read_marks(),
            "sent": [dict(e) for e in d.get("sent_copies", [])],
        }

    def _read_marks(self) -> dict:
        """Read marks by date (section 4.3): for each group followed, everything dated up
        to ``to`` is read, and ``also`` the read ones after it (at most 64)."""
        out = {}
        for gid in self.data["subscribed"]:
            msgs = sorted((m for m in self.cache.get(gid, {}).values() if m.date),
                          key=lambda m: m.date)
            # "to" must not cover anything unread: Date is rounded to 10 minutes, so a
            # post and the unread reply to it can carry the same time
            unread = [_iso(m.date) for m in msgs if not self.is_read(m)]
            first_unread = min(unread) if unread else None
            to = self.data.get("read_to", {}).get(gid, "")
            for m in msgs:
                d = _iso(m.date)
                if self.is_read(m) and (first_unread is None or d < first_unread):
                    to = max(to, d)
            also = sorted(m.message_id for m in msgs if _iso(m.date) > to and self.is_read(m))
            if to or also:
                out[gid] = {"to": to, "also": also[-st.MAX_ALSO:]}
        return out

    def local_state(self) -> dict:
        """The vault's state, each entry with the time it last changed here."""
        snap, now = self._snapshot(), _now()
        first = "state_seen" not in self.data
        seen = self.data.setdefault("state_seen", {})
        s = st.empty()
        def stamp(key, value):
            # a vault that never synced has changed nothing yet: what it holds is older
            # than anything in the network, so a new device's defaults never win
            v = json.dumps(value, sort_keys=True)
            old = seen.get(key)
            at = old[1] if old and old[0] == v else ("" if first else now)
            seen[key] = [v, at]
            return at
        for section, off in (("subscribed", "unsubscribed"), ("following", "unfollowed")):
            for k, v in snap[section].items():
                seen.pop(f"{off}:{k}", None)             # followed again: no tombstone
                at = stamp(f"{section}:{k}", v)
                s[section][k] = at if section == "subscribed" else {**v, "at": at}
            for key in [k for k in seen if k.startswith(section + ":")]:
                k = key.split(":", 1)[1]
                if k not in snap[section]:               # left since: a tombstone
                    at = stamp(f"{off}:{k}", "gone")
                    s[off][k] = at
                    del seen[key]
            for key in [k for k in seen if k.startswith(off + ":")]:
                k = key.split(":", 1)[1]
                if k not in snap[section]:
                    s[off][k] = seen[key][1]
        for section in ("contacts", "ignored", "hidden", "closed_chats"):
            for k, v in snap[section].items():
                at = stamp(f"{section}:{k}", v)
                s[section][k] = {**(v if isinstance(v, dict) else {}), "at": at}
            for key in [k for k in seen if k.startswith(section + ":")]:
                k = key.split(":", 1)[1]
                if k not in snap[section]:               # removed: kept as removed
                    if seen[key][0] != '"removed"':
                        stamp(key, "removed")
                    s[section][k] = {"removed": True, "at": seen[key][1]}
        s["starter"] = snap["starter"]
        s["settings"] = {**snap["settings"], "at": stamp("settings", snap["settings"])}
        s["read"] = snap["read"]
        s["sent"] = snap["sent"]
        s["updated"] = now
        return s

    def _apply_state(self, s: dict) -> None:
        """Put a merged state into the vault, and remember it as seen."""
        d = self.data
        follow = [g for g in d["subscribed"] if g in s["subscribed"]]
        follow += sorted(g for g in s["subscribed"] if g not in follow)
        d["subscribed"][:] = follow
        people = d.setdefault("following", {}).setdefault("people", {})
        for fp, p in s["following"].items():
            people[fp] = {**people.get(fp, {}), **{k: v for k, v in p.items() if k != "at"}}
        for fp in s["unfollowed"]:
            people.pop(fp, None)
        for section, store in (("contacts", d["contacts"]), ("ignored", d["ignored"])):
            for k, v in s[section].items():
                if v.get("removed"):
                    store.pop(k, None)
                else:
                    store[k] = {**store.get(k, {}), **{x: y for x, y in v.items() if x != "at"}}
        hidden = set(d.get("hidden_profiles", []))
        for k, v in s["hidden"].items():
            (hidden.discard if v.get("removed") else hidden.add)(k)
        d["hidden_profiles"] = sorted(hidden)
        closed = d.setdefault("closed_chats", {})
        for k, v in s.get("closed_chats", {}).items():
            if v.get("removed"):
                closed.pop(k, None)
            elif v.get("since"):
                closed[k] = v["since"]
        if s["starter"] > (1 if d.get("starter_groups") is True else int(d.get("starter_groups") or 0)):
            d["starter_groups"] = s["starter"]
        settings = {k: v for k, v in s["settings"].items() if k != "at"}
        for k in SETTINGS:
            if k in settings:
                d[k] = settings[k]
        if "signature" in settings:
            d["identities"][self.default_identity_name()]["signature"] = settings["signature"]
        read_to = d.setdefault("read_to", {})
        for gid, r in s["read"].items():
            if r.get("to", "") > read_to.get(gid, ""):
                read_to[gid] = r["to"]
            marks = d["read"].setdefault(gid, [])
            marks.extend(m for m in r.get("also", []) if m not in marks)
        copies = {e["msgid"]: e for e in d.get("sent_copies", [])}
        for e in s.get("sent", []):
            copies.setdefault(e["msgid"], {k: e[k] for k in ("msgid", "inbox", "at") if k in e})
        d["sent_copies"] = sorted(copies.values(), key=lambda e: e.get("at", ""))[-MAX_SENT_COPIES:]
        self._remember(s)

    def _remember(self, s: dict) -> None:
        """What a merged state says, as seen - with its own times, so what came from
        the network does not count as changed here."""
        def v(value):
            return json.dumps(value, sort_keys=True)
        seen = {}
        for k, at in s["subscribed"].items():
            seen[f"subscribed:{k}"] = [v(True), at]
        for k, at in s["unsubscribed"].items():
            seen[f"unsubscribed:{k}"] = [v("gone"), at]
        for k, p in s["following"].items():
            seen[f"following:{k}"] = [v({x: p[x] for x in ("key", "name", "feeds", "skip") if x in p}),
                                      p.get("at", "")]
        for k, at in s["unfollowed"].items():
            seen[f"unfollowed:{k}"] = [v("gone"), at]
        for section, field in (("contacts", "name"), ("ignored", "label"), ("hidden", None),
                               ("closed_chats", "since")):
            for k, e in s.get(section, {}).items():
                value = "removed" if e.get("removed") else ({field: e.get(field, "")} if field else True)
                seen[f"{section}:{k}"] = [v(value), e.get("at", "")]
        settings = {k: x for k, x in s["settings"].items() if k != "at"}
        seen["settings"] = [v(settings), s["settings"].get("at", "")]
        self.data["state_seen"] = seen

    # --- the network ---
    async def sync_state(self, write: bool = True) -> str:
        """Fetch this identity's state from the network, merge it with the vault's, put
        the result in the vault, and - when it says more than the network has and the
        last write is an hour old - write it (section 7). Returns what happened:
        "local", "no identity", "read", "written", "later" (written within the hour)
        or "unchanged"."""
        if not self.has_identity():
            return "no identity"
        if self.state_kept_local():
            return "local"
        ident = self.identity()
        gid = st.state_id(ident.public_key)
        try:
            current = await self.fetch_manifest(gid)
        except (SessionError, OSError, ConnectionError, NNTPError, asyncio.IncompleteReadError) as exc:
            raise SessionError(f"the state could not be fetched: {exc}") from exc
        remote = st.empty()
        if current is not None and isinstance(current.raw.get("state"), str):
            try:
                remote = st.unseal(current.raw["state"], ident.seed, gid)
            except st.StateError:
                remote = st.empty()                   # not readable: ours replaces it
            self.group_entry(gid).update({"type": "state", "owner": True,
                                          "manifest": dict(current.raw)})
        merged = st.merge(self.local_state(), remote)
        self._apply_state(merged)
        self.save()
        unread = lambda s: {**s, "read": {}}                    # noqa: E731
        if not write or (current is not None and st.same(unread(merged), unread(remote))):
            return "read" if current is not None else "unchanged"   # read marks alone: no write
        if time.time() - self.data.get("state_written", 0) < WRITE_EVERY:
            return "later"
        sealed = st.seal(merged, ident.seed, gid)
        await self._publish_key_bound(gid, lambda serial, bits: st.state_manifest(
            ident, sealed, serial=serial, pow_bits=bits))
        self.group_entry(gid)["type"] = "state"
        self.data["state_written"] = time.time()
        self.save()
        return "written"
