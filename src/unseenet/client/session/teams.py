"""Session: team inboxes (UN-RFC 0047, #341) - an inbox read by up to 16 readers, each
with a team key of its own, who answer on the inbox's behalf.

The owner key is needed only to change who reads (and to renew); reading and replying
need a team key, which a reader keeps in its everyday vault. So the project key can stay
offline while the operator inbox of every node is read and answered.

Belongs here: the team keys in your vault, adding and removing readers (owner), the
invitation a new reader gets and accepting it, what a team box is opened with, whether
a reply on an inbox's behalf is really from one of its readers, and the team's name.

Not here: the team box itself (``core/groups.py``: ``team_box``, ``open_team_box``),
sending (private.py, ``send_private(..., as_team=...)``).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

import base64

from . import *  # noqa: F403  - the shared names: SessionError, Message, ...
from ...core.groups import TEAM_NAME_MAX, TEAM_SLOTS, team_readers


class TeamsMixin:
    # --- your team keys (section 6) ---
    def _team_keys(self) -> dict:
        """{team inbox: {"seed", "identity", "name"}}: the team keys in this vault."""
        return self.data.setdefault("team_keys", {})

    def team_key(self, group_id: str) -> crypto.Identity | None:
        """Your team key for a team inbox, or None."""
        e = self._team_keys().get(group_id)
        return crypto.Identity.from_seed(bytes.fromhex(e["seed"])) if e else None

    def team_inboxes(self) -> list[dict]:
        """The team inboxes you read: ``{"group", "name", "reader": bool}`` - ``reader``
        False when its manifest no longer lists your key (section 9)."""
        out = []
        for gid, e in sorted(self._team_keys().items()):
            key = crypto.Identity.from_seed(bytes.fromhex(e["seed"])).key_text
            data = self.manifest_data(gid)
            out.append({"group": gid, "name": self.team_name(gid) or e.get("name", ""),
                        "reader": not data or key in data.get("readers", [])})
        return out

    def team_name(self, group_id: str) -> str:
        """The name a team inbox answers as: ``team_name``, else its owner's label."""
        data = self.manifest_data(group_id)
        return data.get("team_name") or (self.identity_label(data["owner"]) if data.get("owner") else "")

    def forget_team_key(self, group_id: str) -> None:
        """Remove a team key from the vault (after you were removed, or to stop reading)."""
        self._team_keys().pop(group_id, None)
        self.subscribe(group_id, False)
        self.save()

    # --- the owner: who reads (sections 6, 9) ---
    async def add_team_reader(self, group_id: str, to_key: str, team_name: str | None = None) -> str:
        """Owner: make a new team key for ``to_key``, list it in the inbox's readers and
        send it to their personal inbox with a ``#group`` reference to accept. The
        seed is not kept here (section 6, step 4). Returns the team key, as text."""
        data = await self._own_inbox(group_id)
        readers = list(data.get("readers", []))
        if len(readers) >= TEAM_SLOTS:
            raise SessionError(f"a team inbox has at most {TEAM_SLOTS} readers - more is a group")
        if team_name is not None and len(team_name) > TEAM_NAME_MAX:
            raise SessionError(f"the team's name is at most {TEAM_NAME_MAX} characters")
        to = crypto.key_from_text(to_key.strip())
        team = crypto.Identity.generate()
        team_text = team.key_text
        changes = {"readers": readers + [team_text]}
        if team_name is not None:
            changes["team_name"] = team_name.strip() or None
        await self.update_group(group_id, **changes)
        name = self.team_name(group_id) or "a team inbox"
        body = (f"You have been added as a reader of #{group_id} ({name}).\n\n"
                f"Open it to accept: you will read this inbox and can reply as {name}. "
                "The owner can remove you at any time.\n")
        try:
            await self.send_private(personal_inbox_id(to), f"You can read {name}", body, owner_key=to,
                                    extra=[("Team-Inbox", group_id),
                                           ("Team-Key", base64.b64encode(team.seed).decode())],
                                    remember=False)
        finally:
            del team                                    # the owner keeps no reader's key
        return team_text

    async def remove_team_reader(self, group_id: str, team_key: str) -> None:
        """Owner: a new manifest without this team key. It reads no new messages and its
        replies no longer verify; nothing tells it (section 9)."""
        data = await self._own_inbox(group_id)
        readers = [k for k in data.get("readers", []) if k != team_key]
        if len(readers) == len(data.get("readers", [])):
            raise SessionError("that key is not a reader of this inbox")
        await self.update_group(group_id, readers=readers or None)

    async def _own_inbox(self, group_id: str) -> dict:
        m = await self.fetch_manifest(group_id)
        if m is None:
            raise SessionError("the inbox's manifest cannot be read")
        self.group_entry(group_id)["manifest"] = dict(m.raw)
        if m.type != "inbox":
            raise SessionError("only an inbox can have readers")
        if crypto.key_to_text(m.owner) not in {self.identity(n).key_text for n in self.data["identities"]}:
            raise SessionError("only the inbox's owner chooses who reads it")
        self.group_entry(group_id)["owner"] = True
        return dict(m.raw)

    # --- the reader: the invitation (section 6) ---
    @staticmethod
    def team_invitation(msg: "Message") -> dict | None:
        """``{"group", "seed"}`` of a private post that hands you a team key, before it
        is checked; None for other posts. ``accept_team_invitation`` checks it."""
        inv = getattr(msg, "team_invite", None)
        return dict(inv) if inv else None

    async def accept_team_invitation(self, msg: "Message") -> str:
        """Check an invitation - its sender owns the team inbox, and the key it brings is
        among the inbox's current readers - then keep the team key in the vault next to
        the identity that got it, and follow the inbox. Returns the inbox's Group ID."""
        inv = self.team_invitation(msg)
        if not inv:
            raise SessionError("this post hands you no team key")
        gid = inv["group"]
        try:
            seed = base64.b64decode(inv["seed"], validate=True)
            team = crypto.Identity.from_seed(seed)
        except (ValueError, crypto.CryptoError) as exc:
            raise SessionError("the team key in it is damaged") from exc
        m = await self.fetch_manifest(gid)
        if m is None or m.type != "inbox":
            raise SessionError("that team inbox cannot be read")
        if msg.sender_key != crypto.key_to_text(m.owner):
            raise SessionError("it is not from the inbox's owner: not accepted")
        if team.key_text not in m.raw.get("readers", []):
            raise SessionError("its key is not (or no longer) a reader of that inbox")
        self.group_entry(gid)["manifest"] = dict(m.raw)
        self.group_entry(gid)["type"] = "inbox"
        self._team_keys()[gid] = {"seed": seed.hex(), "identity": self.default_identity_name(),
                                  "name": m.raw.get("team_name", "")}
        self.subscribe(gid)
        self.save()
        return gid

    # --- a reply on an inbox's behalf (section 8) ---
    def team_sender(self, msg: "Message") -> dict | None:
        """For a message written on a team inbox's behalf: ``{"group", "name",
        "verified"}`` - verified when its key is among that inbox's readers in the
        manifest you hold; None for other messages. Never shown as a person."""
        t = getattr(msg, "team", None)
        if not t:
            return None
        data = self.manifest_data(t["group"])
        verified = bool(data) and msg.sender_key in data.get("readers", [])
        return {"group": t["group"], "name": self.team_name(t["group"]) if data else "",
                "verified": verified}

    async def check_team_senders(self) -> int:
        """Read the manifests of the team inboxes that wrote to you, so their replies
        can be verified (section 8). Returns how many were read."""
        groups = {m.team["group"] for m in self.cache.get(self.my_inbox, {}).values()
                  if getattr(m, "team", None) and not self.manifest_data(m.team["group"])}
        if not groups:
            return 0
        found = await self.fetch_manifests(sorted(groups))
        for gid, m in found.items():
            if m is not None:
                self.group_entry(gid)["manifest"] = dict(m.raw)
        return len(found)

    def _team_readers_for(self, group_id: str) -> list[bytes]:
        return team_readers(self.manifest_data(group_id))
