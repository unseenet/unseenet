"""Recovery words (UN-RFC 0046 section 4.18, UN-RFC 0050 section 4): showing them,
checking them as typed, restoring an identity, and asking to be invited again.

Belongs here: the words of an identity (behind the passphrase), the reminder, checking
words while they are typed, restoring - also as the first setup of a new vault - and
the closed groups that do not come back.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts
from ....core import recovery as rc
from ...session.recovery import NOT_RESTORED


class Recovery:
    # --- the words (UN-RFC 0050 section 4.2) ---------------------------------------
    async def recovery_words(self, passphrase: str, identity: str | None = None) -> dict:
        """``POST /api/recovery/words``: an identity's 24 words, after the vault passphrase
        again; with the three positions to ask back, what to say with them, and the text
        for *Save as file* or *Print* (section 4.3: the front end decides whether)."""
        s = self._ready()
        if self.service:
            raise SessionError("a service has no recovery words to show")
        name = identity or s.default_identity_name()
        words = await asyncio.to_thread(s.recovery_words, passphrase, name)
        ident = s.identity(name)
        return {"identity": name, "fingerprint": ident.fingerprint, "words": words,
                "check": rc.check_positions(), "note": NOT_RESTORED, "not_a_wallet": rc.NOT_A_WALLET,
                "title": rc.NAME, "page": rc.text_page(s.display_name(name), ident.fingerprint, words)}

    def recovery_written(self, identity: str | None = None) -> dict:
        """``POST /api/recovery/written``: the words were written down and checked."""
        s = self._ready()
        s.note_words_written(identity)
        return {"written": True}

    def recovery_reminded(self, identity: str | None = None) -> dict:
        """``POST /api/recovery/reminded``: the front end reminded the user (or they
        skipped at creation); the next reminder comes in a week at the earliest."""
        s = self._ready()
        s.note_words_reminded(identity)
        return {"reminder": s.words_reminder_due(identity)}

    @staticmethod
    def recovery_check(words: str) -> dict:
        """``POST /api/recovery/check``: are these words readable? For feedback while
        they are typed - no session needed, nothing is kept. ``{"ok", "words"}`` (the
        full words) or ``{"ok": false, "kind", "error", "position"}``."""
        try:
            return {"ok": True, "words": rc.normalised(words)}
        except rc.RecoveryError as exc:
            return {"ok": False, "kind": exc.kind, "error": str(exc), "position": exc.position}

    # --- restoring (section 4.4) ------------------------------------------------------
    async def recovery_restore(self, words: str, display: str = "", node: str = "",
                               name: str = "") -> dict:
        """``POST /api/recovery/restore``: put the identity in the vault and read what the
        network keeps for it. Also the first setup of a new vault (instead of choosing a
        name): then ``node`` is needed as for ``/api/setup``. Answers what
        ``Session.restore_from_network`` found, with ``new`` and the ``note`` that closed
        groups do not come back, and starts the runtime."""
        if self.service:
            raise SessionError("a service is set up with its key file")
        s = self._unlocked()
        node = node.strip()
        if not s.node and not node:
            raise SessionError("choose a node")
        vault_name, ident, new = s.restore_identity(words, name or None, display or None)
        if not s.node:
            s.add_node(node)
        self._say("Reading your state from the network ...")
        found = await s.restore_from_network(vault_name)
        if self.runtime is None and not self.needs_setup():
            await self.start()
        return {**found, "identity": vault_name, "new": new, "note": NOT_RESTORED}

    async def recovery_closed_groups(self) -> dict:
        """``GET /api/recovery/closed-groups``: closed groups you follow without their
        secrets, after a restore (UN-RFC 0050 section 4.5)."""
        s = self._ready()
        return {"groups": await s.closed_groups_to_rejoin(), "note": NOT_RESTORED}

    async def recovery_ask(self, group: str, note: str = "") -> dict:
        """``POST /api/recovery/ask``: ask a closed group's owner by private post to
        invite you again."""
        s = self._ready()
        return {"message_id": await s.ask_to_be_invited(group, note)}
