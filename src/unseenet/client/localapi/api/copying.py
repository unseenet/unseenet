"""Copying to another device (UN-RFC 0046 section 4.19, UN-RFC 0050 section 3).

One copy at a time, offered or received. The old device's offer lives while the user
waits; what happens to it comes as ``copy`` events over the WebSocket (section 5):
``{"event": "copy", "role": "old" | "new", "state", "check_words", "error", "added"}``.

Belongs here: offering a copy, the user's answer to the check words, cancelling, and
receiving one - also as the first setup of a new vault.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class Copying:
    def _copy_event(self, role: str, state: str, **extra) -> dict:
        data = {"event": "copy", "role": role, "state": state, **extra}
        self._broadcast(data)
        return data

    def copy_state(self) -> dict:
        """``GET /api/copy``: the copy in progress, if any."""
        offer = getattr(self, "_copy_offer", None)
        got = getattr(self, "_copy_got", None)
        if offer is not None:
            return {"role": "old", **offer.result()}
        if got is not None:
            return {"role": "new", "state": "check", "check_words": list(got.check_words)}
        return {"role": None, "state": None}

    # --- the old device ---
    async def copy_offer(self, identities: list[str] | None = None, group_secrets: bool = True) -> dict:
        """``POST /api/copy/offer``: offer a copy of the vault's identities (all, or
        ``identities``) and, unless left out, the closed groups' secrets. Answers the code,
        the QR text and when it runs out; the check words come as a ``copy`` event."""
        s = self._ready()
        if self.service:
            raise SessionError("a service is not copied to other devices")
        await self.copy_cancel()
        offer = await s.start_copy(identities or None, bool(group_secrets))
        self._copy_offer = offer

        async def follow():
            words = await offer.wait_for_check()
            if words:
                self._copy_event("old", "check", check_words=list(words))
            await offer._done.wait()
            self._copy_event("old", offer.state, error=offer.error, added=offer.added)
            if getattr(self, "_copy_offer", None) is offer:
                self._copy_offer = None
        self.spawn(follow())
        return {"role": "old", **offer.result()}

    async def copy_confirm(self, match: bool) -> dict:
        """``POST /api/copy/confirm`` ``{"match"}``: the user compared the check words. True
        sends the copy and answers when the new device has it; false sends nothing."""
        offer = getattr(self, "_copy_offer", None)
        if offer is None:
            raise SessionError("no copy is being offered")
        return {"role": "old", **await offer.confirm(bool(match))}

    async def copy_cancel(self) -> dict:
        """``POST /api/copy/cancel``: stop the copy offered or being received."""
        offer, self._copy_offer = getattr(self, "_copy_offer", None), None
        got, self._copy_got = getattr(self, "_copy_got", None), None
        if offer is not None:
            await offer.cancel()
        if got is not None:
            await got.cancel()
        return {"cancelled": offer is not None or got is not None}

    # --- the new device ---
    async def copy_receive(self, code: str, node: str = "") -> dict:
        """``POST /api/copy/receive`` ``{"code", "node"}``: connect to the old device with
        the typed code or scanned QR text. Answers the check words to compare; then
        ``/api/copy/finish``. Also the first setup of a new vault (``node`` needed then,
        as for ``/api/setup``)."""
        if self.service:
            raise SessionError("a service is set up with its key file")
        s = self._unlocked()
        if not s.node and not node.strip():
            raise SessionError("choose a node")
        await self.copy_cancel()
        self._copy_node = node.strip()
        self._copy_got = await s.receive_copy(code)
        return {"role": "new", "state": "check", "check_words": list(self._copy_got.check_words)}

    async def copy_finish(self) -> dict:
        """``POST /api/copy/finish``: wait for the copy (the user confirms the words on the
        old device), add it to the vault, and start as after a restore: the state is read
        from the network. Answers ``{"added", "state"}``."""
        s = self._unlocked()
        got, self._copy_got = getattr(self, "_copy_got", None), None
        if got is None:
            raise SessionError("no copy is being received")
        try:
            added = await got.finish()
        except SessionError as exc:
            self._copy_event("new", "failed", error=str(exc))
            raise
        if not s.node and getattr(self, "_copy_node", ""):
            s.add_node(self._copy_node)
        state = "none"
        if s.has_identity() and s.node:
            try:
                state = await s.sync_state(write=False)
            except SessionError:
                state = "unreachable"
            await s.adopt_published_ripenings(added)        # the keys' levels, at once
            await s.adopt_published_personal_groups(added)  # their feeds and sites (#771)
            if self.runtime is None and not self.needs_setup():
                await self.start()
        self._copy_event("new", "done", added=added)
        return {"added": added, "state": state}
