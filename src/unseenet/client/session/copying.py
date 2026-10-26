"""Session: copying identities to another device (UN-RFC 0050 section 3) - the old device
offers a copy, the new device receives it.

The old device (``start_copy``) opens a one-time onion service on its own Tor (``ADD_ONION``
with a key nobody keeps), leaves its address at a node's meeting point under the code
(section 3.3), and answers one connection: SPAKE2, confirmations, the check words, and
- once the user says they match - the copy. The new device (``receive_copy``) takes the
typed code (and asks the meeting point) or the QR text, connects over Tor, and after the
same steps adds the copy to its vault (section 3.7). The protocol itself is
``core/copying.py``; section 3.9 is the order of the messages.

Opening the onion service and connecting to it are ``_copy_onion`` and ``_copy_open``, so
tests can run the copy between two sessions without Tor.

Belongs here: the copy offer and the copy received, and the meeting point's client side.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from . import *  # noqa: F403  - the shared names: SessionError, NNTPError, ...
from ...core import copying as cp
from ...core.tor import Socks, open_connection

STEP_SECONDS = 120.0               # one step of the exchange, the user's check aside


def _say_error(exc: BaseException) -> str:
    if isinstance(exc, cp.CopyError):
        return str(exc)
    if isinstance(exc, asyncio.TimeoutError):
        return "The other device did not answer in time. Start again with a new code."
    return f"The copy failed: {exc}"


class CopyOffer:
    """A copy offered by the old device. ``code`` and ``qr`` to show; ``state`` goes
    ``waiting`` -> ``check`` (``check_words`` are set: ask the user) -> ``sent`` -> ``done``,
    or ``failed`` (``error``), ``cancelled`` or ``expired``. Use ``wait_for_check``, then
    ``confirm(True)`` (or False), or ``cancel`` at any time."""

    def __init__(self, session, names, group_secrets: bool):
        self.session, self.names, self.group_secrets = session, names, group_secrets
        self.word1, self.word2 = cp.new_words()
        self.n: int | None = None
        self.code = self.qr = ""
        self.onion = self.meeting_node = ""
        self.expires = time.time() + cp.CODE_SECONDS
        self.state, self.error = "waiting", ""
        self.check_words: tuple[str, str] | None = None
        self.added: list[str] = []
        self._server: asyncio.base_events.Server | None = None
        self._remove_onion = None
        self._used = False
        self._check = asyncio.Event()
        self._decision: asyncio.Future = asyncio.get_running_loop().create_future()
        self._done = asyncio.Event()
        self._timer: asyncio.Task | None = None

    # --- what the front end does ---
    async def wait_for_check(self, timeout: float | None = None) -> tuple[str, str] | None:
        """Wait until the new device has connected and the check words can be shown (or the
        offer ended: then None, and ``state`` / ``error`` say why)."""
        waiter = asyncio.ensure_future(self._check.wait())
        done = asyncio.ensure_future(self._done.wait())
        try:
            await asyncio.wait({waiter, done}, timeout=timeout or max(0.0, self.expires - time.time()),
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
            done.cancel()
        return self.check_words if self.state == "check" else None

    async def confirm(self, match: bool) -> dict:
        """The user's answer to "do the words match?". True sends the copy and waits for
        the new device's acknowledgement; False closes without sending anything."""
        if self.state != "check":
            raise SessionError("there is nothing to confirm" if self.state == "waiting"
                               else self.error or f"the copy is {self.state}")
        if not self._decision.done():
            self._decision.set_result(bool(match))
        await self._done.wait()
        return self.result()

    async def cancel(self) -> None:
        if not self._decision.done():
            self._decision.set_result(False)
        await self._finish("cancelled" if self.state not in ("done", "failed") else self.state)

    def result(self) -> dict:
        return {"state": self.state, "error": self.error, "added": self.added,
                "check_words": list(self.check_words or ()), "code": self.code, "qr": self.qr,
                "expires": self.expires}

    # --- the connection (section 3.9) ---
    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._used or self.state != "waiting":          # one attempt per code (3.2)
            writer.close()
            return
        self._used = True
        try:
            x = cp.Exchange(cp.OLD, self.code)
            step = lambda aw: asyncio.wait_for(aw, STEP_SECONDS)       # noqa: E731
            await cp.write_msg(writer, cp.VERSION)
            if await step(cp.read_msg(reader)) != cp.VERSION:
                raise cp.CopyError("the other device speaks another version of copying")
            await cp.write_msg(writer, x.message)
            x.finish(await step(cp.read_msg(reader)))
            x.check_confirmation(await step(cp.read_msg(reader)))     # the new device's first
            await cp.write_msg(writer, x.confirmation())
            self.check_words, self.state = x.check_words, "check"
            self._check.set()
            match = await asyncio.wait_for(asyncio.shield(self._decision),
                                           max(1.0, self.expires - time.time()))
            if not match:
                raise cp.CopyError("The check words did not match: nothing was sent.")
            payload = cp.build_payload(self.session.data, self.names, self.group_secrets)
            await cp.write_msg(writer, x.seal(payload))
            self.state = "sent"
            answer = x.open(await step(cp.read_msg(reader)))
            if not answer.get("ok"):
                raise cp.CopyError(f"The other device could not take the copy: {answer.get('error', '')}")
            self.added = [str(a) for a in answer.get("added", [])]
            await self._finish("done")
        except (cp.CopyError, asyncio.TimeoutError, OSError, ConnectionError) as exc:
            self.error = _say_error(exc)
            await self._finish("cancelled" if self._decision.done() and not self._decision.result()
                               and self.state == "check" else "failed")
        finally:
            writer.close()

    async def _finish(self, state: str) -> None:
        if self._done.is_set():
            return
        self.state = state
        if self._timer is not None and self._timer is not asyncio.current_task():
            self._timer.cancel()
        if self._server is not None:
            self._server.close()
        if self._remove_onion is not None:
            with contextlib.suppress(Exception):
                await self._remove_onion()
        self._done.set()
        self._check.set()

    async def _expire(self) -> None:
        await asyncio.sleep(max(0.0, self.expires - time.time()))
        if self.state in ("waiting", "check"):
            self.error = "The code ran out after 10 minutes. Start again with a new code."
            if not self._decision.done():
                self._decision.set_result(False)
            await self._finish("expired")


class CopyReceive:
    """A copy being received by the new device: ``check_words`` to show, then ``finish``
    (the user sees the same words on the old device and confirms there) or ``cancel``."""

    def __init__(self, session, x: cp.Exchange, reader, writer):
        self.session, self._x, self._reader, self._writer = session, x, reader, writer
        self.check_words = x.check_words

    async def finish(self) -> list[str]:
        """Wait for the copy (the old device's user must confirm the words first), add it
        to the vault, acknowledge it. Returns the names of the identities added."""
        try:
            blob = await asyncio.wait_for(cp.read_msg(self._reader, cp.MAX_COPY), cp.CODE_SECONDS)
        except cp.CopyError as exc:
            self._writer.close()
            raise SessionError("The other device stopped the copy: the check words did not "
                               "match, or it was cancelled there.") from exc
        except asyncio.TimeoutError as exc:
            self._writer.close()
            raise SessionError(_say_error(exc)) from exc
        try:
            payload = cp.check_payload(self._x.open(blob))
            added = cp.merge_payload(self.session.data, payload)
            self.session.save()
        except (cp.CopyError, OSError) as exc:
            with contextlib.suppress(Exception):
                await cp.write_msg(self._writer, self._x.seal({"ok": False, "error": str(exc)}))
            self._writer.close()
            raise SessionError(_say_error(exc)) from exc
        with contextlib.suppress(Exception):
            await cp.write_msg(self._writer, self._x.seal({"ok": True, "added": added}))
        self._writer.close()
        return added

    async def cancel(self) -> None:
        self._writer.close()


class CopyingMixin:
    # --- the old device ---
    async def start_copy(self, names: list[str] | None = None, group_secrets: bool = True,
                         meeting_nodes: list[str] | None = None) -> CopyOffer:
        """Offer a copy of this vault's identities (all, or ``names``) and - unless left
        out - the secrets of its closed groups. Opens the one-time onion service and the
        meeting, and returns the offer with its code and QR text."""
        cp.build_payload(self.data, names, group_secrets)               # something to copy
        offer = CopyOffer(self, names, group_secrets)
        offer._server = await asyncio.start_server(offer._handle, "127.0.0.1", 0)
        port = offer._server.sockets[0].getsockname()[1]
        try:
            offer.onion, offer._remove_onion = await self._copy_onion(port)
            offer.n, offer.meeting_node = await self._open_meeting(
                offer.onion, cp.tag(offer.word1, offer.word2), meeting_nodes)
        except BaseException:
            await offer._finish("failed")
            raise
        offer.code = cp.make_code(offer.n, offer.word1, offer.word2)
        offer.qr = cp.qr_text(offer.onion, offer.code)
        offer._timer = asyncio.ensure_future(offer._expire())
        return offer

    async def _copy_onion(self, local_port: int):
        """A one-time onion service to ``local_port`` on our own Tor, its key kept by
        nobody: (address, a coroutine function that removes it). A Tor we did not start
        cannot be controlled (section 3.9)."""
        socks = await self._ensure_tor(self.say)
        if isinstance(socks, Socks) or self.tor is None or getattr(self.tor, "control", None) is None:
            raise SessionError("This device uses a Tor it cannot control, so it cannot copy to "
                               "another device. It can receive a copy.")
        control = self.tor.control
        onion, _ = await control.add_onion(None, cp.PORT, f"127.0.0.1:{local_port}", discard=True)
        return onion, lambda: control.del_onion(onion)

    def meeting_candidates(self, given: list[str] | None = None) -> list[str]:
        """Where meetings are opened and looked up (section 3.3): the known-node list, in
        its order - every client has it - then this vault's own nodes."""
        if given:
            return list(given)
        out = [k.address for k in self.known_nodes()]
        return out + [n for n in self.nodes if n not in out]

    async def _meeting_client(self, address: str) -> Client | None:
        socks = await self._ensure_tor(self.say) if address.split(":")[0].endswith(".onion") else None
        try:
            client = await asyncio.wait_for(Client.connect(address, socks), STEP_SECONDS)
            await client.fetch_capabilities()
        except (OSError, ConnectionError, NNTPError, asyncio.TimeoutError):
            return None
        if client.capability("XUNMEET") is None:
            with contextlib.suppress(Exception):
                await client.quit()
            return None
        return client

    async def _open_meeting(self, onion: str, tag: str, given=None) -> tuple[int, str]:
        for address in self.meeting_candidates(given):
            client = await self._meeting_client(address)
            if client is None:
                continue
            try:
                code, text = await client.command(f"XUNMEET OPEN {onion} {tag}")
            finally:
                with contextlib.suppress(Exception):
                    await client.quit()
            if code == 290 and text.split()[0].isdigit():
                return int(text.split()[0]), address
        raise SessionError("No node with a meeting point could be reached. Scan the QR code "
                           "instead, or try again.")

    async def _lookup_meeting(self, n: int, tag: str, given=None) -> str:
        for address in self.meeting_candidates(given):
            client = await self._meeting_client(address)
            if client is None:
                continue
            try:
                code, text = await client.command(f"XUNMEET LOOKUP {n} {tag}")
            finally:
                with contextlib.suppress(Exception):
                    await client.quit()
            if code == 291:
                return text.split()[0]
        raise SessionError("No device is waiting with this code. Check the code, or start again "
                           "on the other device.")

    # --- the new device ---
    async def receive_copy(self, code_or_qr: str, meeting_nodes: list[str] | None = None) -> CopyReceive:
        """Connect to the old device with the typed code or the scanned QR text, run the
        exchange and return the copy being received, whose ``check_words`` the user
        compares with the old device's."""
        text = code_or_qr.strip()
        try:
            if text.startswith(cp.QR_PREFIX):
                onion, code = cp.parse_qr(text)
            else:
                code = cp.normal_code(text)
                n, w1, w2 = cp.parse_code(code)
                onion = await self._lookup_meeting(n, cp.tag(w1, w2), meeting_nodes)
        except cp.CopyError as exc:
            raise SessionError(str(exc)) from exc
        x = cp.Exchange(cp.NEW, code)
        reader, writer = await self._copy_open(onion)
        try:
            step = lambda aw: asyncio.wait_for(aw, STEP_SECONDS)       # noqa: E731
            await cp.write_msg(writer, cp.VERSION)
            if await step(cp.read_msg(reader)) != cp.VERSION:
                raise cp.CopyError("the other device speaks another version of copying")
            await cp.write_msg(writer, x.message)
            x.finish(await step(cp.read_msg(reader)))
            await cp.write_msg(writer, x.confirmation())
            x.check_confirmation(await step(cp.read_msg(reader)))
        except (cp.CopyError, asyncio.TimeoutError, OSError, ConnectionError) as exc:
            writer.close()
            raise SessionError(_say_error(exc)) from exc
        return CopyReceive(self, x, reader, writer)

    async def _copy_open(self, onion: str):
        """A stream to the old device's one-time onion service (section 3.9)."""
        socks = await self._ensure_tor(self.say)
        try:
            return await open_connection(f"{onion}:{cp.PORT}", socks)
        except (OSError, ConnectionError) as exc:
            raise SessionError(f"The other device could not be reached: {exc}") from exc
