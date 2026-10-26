"""Session: recovery words (UN-RFC 0050 section 4) - showing them, the reminder to write
them down, restoring an identity from them, and what does not come back.

The words are the identity's seed (``core/recovery.py``). Showing them asks for the
vault passphrase again even when the vault is open (4.2). Nothing here saves them:
not in the vault, the state, a log or the network (4.3) - the vault only notes that
they were written down, so the client stops reminding.

Restoring puts the key in the vault and reads the rest from the network: the state
(UN-RFC 0044) and, to show it is the right identity, its name and profile (4.4).
Access to closed groups does not come back (4.5): ``closed_groups_to_rejoin`` lists
them and ``ask_to_be_invited`` asks an owner, by private post, to invite you again.

Belongs here: everything about recovery words above the encoding. Copying an
identity to another device (section 3) has a file of its own.
"""

from __future__ import annotations

import asyncio
import time

from . import *  # noqa: F403  - the shared names: SessionError, NNTPError, ...
from ...core import recovery as rc
from ...core import profiles as prof
from ...core.groups import personal_inbox_id

REMIND_EVERY = 7 * 86400          # section 4.2: gently, not more than once a week
NOT_RESTORED = ("Closed groups do not come back with recovery words: their owners "
                "must invite you again.")


class RecoveryMixin:
    # --- showing the words (section 4.2) ---
    def recovery_words(self, passphrase: str, name: str | None = None) -> list[str]:
        """The 24 recovery words of an identity (the default if ``name`` is None).
        Asks for the vault passphrase again, even with the vault open (4.2). Slow:
        the passphrase check runs the key derivation."""
        if getattr(self.vault, "path", None) is None:
            raise SessionError("a service has no recovery words to show")
        if not self.vault.check_passphrase(passphrase):
            raise SessionError("The passphrase is not right.")
        name = name or self.default_identity_name()
        entry = self.data["identities"].get(name)
        if entry is None:
            raise SessionError(f"no identity {name}")
        return rc.words_from_seed(bytes.fromhex(entry["seed"]))

    def note_words_written(self, name: str | None = None) -> None:
        """The user wrote the words down and passed the check: stop reminding."""
        name = name or self.default_identity_name()
        self.data["identities"][name]["words_written"] = int(time.time())
        self.save()

    def words_written(self, name: str | None = None) -> bool:
        """True when the words of this identity were written down (and checked)."""
        name = name or self.default_identity_name()
        return bool(self.data["identities"].get(name, {}).get("words_written"))

    def words_reminder_due(self, name: str | None = None, now: float | None = None) -> bool:
        """True when the client should remind the user to write the words down: not
        done yet, and not reminded within a week (section 4.2). The client calls
        ``note_words_reminded`` when it has."""
        name = name or self.default_identity_name()
        entry = self.data["identities"].get(name, {})
        if entry.get("words_written") or "seed" not in entry:
            return False
        last = entry.get("words_reminded", 0)
        return (now or time.time()) - last >= REMIND_EVERY

    def note_words_reminded(self, name: str | None = None) -> None:
        """The client reminded the user (or showed the words at creation, skipped)."""
        name = name or self.default_identity_name()
        self.data["identities"][name]["words_reminded"] = int(time.time())
        self.save()

    # --- restoring (section 4.4) ---
    def restore_identity(self, words, name: str | None = None, display: str | None = None,
                         make_default: bool = True) -> tuple[str, crypto.Identity, bool]:
        """Put the identity the words encode in the vault. Raises ``SessionError`` with
        the reason a person can act on (an unknown word, a typing mistake). Returns
        (its name in the vault, the identity, True if it was not here already). The
        words are not kept; the identity counts as written down."""
        try:
            seed = rc.seed_from_words(words)
        except rc.RecoveryError as exc:
            raise SessionError(str(exc)) from exc
        ident = crypto.Identity.from_seed(seed)
        for have, entry in self.data["identities"].items():
            if entry.get("seed") == seed.hex():
                if make_default:
                    self.data["default_identity"] = have
                    self.save()
                return have, ident, False
        name = (name or "").strip() or f"restored-{ident.fingerprint[:6]}"
        if name in self.data["identities"]:
            raise SessionError(f"there is already an identity {name} with another key")
        self.data["identities"][name] = {"seed": seed.hex(), "display": (display or "").strip() or name,
                                         "signature": DEFAULT_SIGNATURE,
                                         "words_written": int(time.time()), "restored": int(time.time())}
        if make_default or not self.data.get("default_identity"):
            self.data["default_identity"] = name
        self.save()
        return name, ident, True

    async def restore_from_network(self, name: str | None = None) -> dict:
        """After ``restore_identity``: read what the network keeps for the key (4.4) -
        the state with subscriptions, contacts, read marks and settings, and its name
        and profile so the user sees it is the right one. Never writes. Returns
        ``{"fingerprint", "label", "profile", "state", "closed_groups"}``, where
        ``state`` is "read", "none" (no state found: start with the default groups)
        or "unreachable", and ``closed_groups`` what ``closed_groups_to_rejoin`` gives."""
        if name is not None and name != self.default_identity_name():
            self.data["default_identity"] = name
            self.save()
        ident = self.identity()
        out = {"fingerprint": ident.fingerprint, "key": ident.key_text, "label": "",
               "profile": None, "state": "none", "closed_groups": []}
        try:
            await self.refresh_naming()
        except (SessionError, OSError, ConnectionError, NNTPError, asyncio.IncompleteReadError):
            pass
        out["label"] = self.identity_label(ident.key_text, self.display_name())
        try:
            m = await self.fetch_manifest(prof.profile_id(ident.public_key))
            if m is not None:
                self.group_entry(m.group_id).update({"type": "profile", "owner": True,
                                                     "manifest": dict(m.raw)})
                out["profile"] = m.raw.get("profile")
            result = await self.sync_state(write=False)
        except SessionError:
            out["state"] = "unreachable"
            return out
        out["state"] = "read" if result == "read" else "none"
        self.save()
        out["closed_groups"] = await self.closed_groups_to_rejoin()
        return out

    # --- what does not come back (section 4.5) ---
    async def closed_groups_to_rejoin(self) -> list[dict]:
        """The closed groups you follow whose secrets this vault lacks - after a restore,
        those the state says you follow (4.5). Each is ``{"group", "label", "owner"}``;
        groups you own yourself are left out (you hold their keys only if the vault
        does - a restored owner must make a new group key, UN-RFC 0004)."""
        subscribed = list(self.data["subscribed"])
        unknown = [g for g in subscribed if not self.manifest_data(g)]
        if unknown:
            try:
                got = await self.fetch_manifests(unknown)
            except (SessionError, OSError, ConnectionError, NNTPError, asyncio.IncompleteReadError):
                got = {}
            for gid, m in got.items():
                if m is not None:
                    self.group_entry(gid).update({"type": m.type, "manifest": dict(m.raw)})
        me = self.identity().key_text
        out = []
        for gid in subscribed:
            entry = self.data["groups"].get(gid, {})
            manifest = entry.get("manifest") or {}
            if manifest.get("type") != "closed" or entry.get("keys"):
                continue
            out.append({"group": gid, "label": self.group_label(gid),
                        "owner": manifest.get("owner"), "mine": manifest.get("owner") == me})
        return out

    async def ask_to_be_invited(self, group_id: str, note: str = "") -> str:
        """Ask a closed group's owner, by private post to their inbox, to invite you
        again after a restore (4.5). Returns the post's Message-ID."""
        owner = (self.manifest_data(group_id) or {}).get("owner")
        if not owner:
            raise SessionError("the group's owner is not known yet")
        if owner == self.identity().key_text:
            raise SessionError("you own this group")
        label = self.group_label(group_id)
        body = (f"Hi,\n\nI restored my identity from its recovery words, and closed groups "
                f"do not come back that way. Could you invite me to {label} again?\n\n"
                f"Group: {group_id}\nMy key: {self.identity().key_text}\n")
        if note.strip():
            body += f"\n{note.strip()}\n"
        owner_key = crypto.key_from_text(owner)
        return await self.send_private(personal_inbox_id(owner_key), f"Invite me again to {label}",
                                       body, owner_key=owner_key)
