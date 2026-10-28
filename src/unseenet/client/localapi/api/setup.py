"""Unlocking and setting up (UN-RFC 0046 section 4.2): a vault opened, created or imported.

Belongs here: whether the vault needs setting up, unlocking it with its passphrase,
the first setup (an identity, a node), starting the runtime and closing it, and the
``Locked`` answer while there is no session.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class Setup:
    # --- unlocking and setting up (section 4.2) --------------------------------
    def _attach(self, session: Session) -> None:
        self.session = session
        session.status = lambda text: None           # Status events carry it
        self._off = session.on(self._on_event)
        if self.service:
            self.status = "Starting"

    def needs_setup(self) -> bool:
        """True when the vault is open but has no identity or no node yet: the front
        end shows the setup (section 4.2)."""
        s = self.session
        return s is not None and (not s.has_identity() or not s.node)

    async def unlock(self, passphrase: str, device: str = "", secret: str = "") -> dict:
        """``POST /api/unlock`` (section 4.2): open the vault with its passphrase (made if
        it does not exist yet) - or with a device's secret (``device``, ``secret`` in b64,
        UN-RFC 0050 section 5) - and start the runtime. A service has no vault to unlock."""
        if self.service:
            raise SessionError("a service has no vault to unlock")
        if self.session is None:
            fast = os.environ.get("UNSEENET_INSECURE_FAST_KDF") == "1"
            kdf = {"ops": 1, "mem": 8192 * 1024} if fast else {}
            self._say("Unlocking vault ...")
            try:
                if device:
                    if not self.vault_path.exists():
                        raise VaultError("there is no vault yet: choose a passphrase")
                    vault = await asyncio.to_thread(Vault.open_with_device, self.vault_path,
                                                    device, _b64(secret))
                else:
                    vault = await asyncio.to_thread(Vault.open, self.vault_path, passphrase, **kdf)
            except VaultError as exc:
                self._say("Locked")
                raise SessionError(str(exc) or "wrong passphrase") from exc
            self._attach(Session(vault))
            if self.needs_setup():
                self._say("Choose a name and a node")
            else:
                await self.start()
        return self.state()

    async def setup(self, display: str, node: str) -> dict:
        """``POST /api/setup`` (section 4.2): the first setup of a new vault - your display
        name and a node (an address, or one from the known nodes). Starts the runtime."""
        if self.service:
            raise SessionError("a service is set up with its key file")
        s = self._unlocked()
        display, node = display.strip(), node.strip()
        if self.needs_setup():
            if not s.has_identity():
                if not display:
                    raise SessionError("choose a name")
                s.new_identity(display.lower().replace(" ", "-"), display)
            if not s.node:
                if not node:
                    raise SessionError("choose a node")
                s.add_node(node)
            await self.start()
        return self.state()

    async def start(self) -> None:
        """Run the client runtime: saved posts at once, then the network."""
        s = self._unlocked()
        if self.runtime is not None:
            return
        kw = {} if self._refresh_seconds is None else {"refresh_seconds": self._refresh_seconds}
        self.runtime = ClientRuntime(s, ripen_to=self._ripen_to, **kw)
        loaded = await self.runtime.start()
        self._say(f"{loaded} saved posts available offline - connecting ...")

    async def close(self) -> None:
        """Stop the runtime and every task, and close the session. The server calls it on
        shutdown; a test or another transport calls it when done."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.runtime is not None:
            await self.runtime.stop()
            self.runtime = None
        if self.session is not None:
            with contextlib.suppress(Exception):
                await self.session.close()
            if self._off:
                self._off()
                self._off = None
        if not self.service:
            self.session = None
            self.status = "Locked"

    def _unlocked(self) -> Session:
        if self.session is None:
            raise Locked("locked")
        return self.session

    def _ready(self) -> Session:
        s = self._unlocked()
        if self.needs_setup():
            raise Locked("set up first")
        return s


def _b64(text: str) -> bytes:
    import base64
    import binascii
    try:
        return base64.b64decode(str(text), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SessionError("secret is b64") from exc


class DeviceUnlock:
    def device_unlocks(self) -> dict:
        """``GET /api/device-unlock`` (section 4.2, UN-RFC 0050 section 5): the devices that
        can open this vault without its passphrase - ``id`` (a passkey's credential ID),
        ``label``, ``created``; never what they hold. Also when locked, so the page knows
        which passkey to ask for. ``possible``: false for a service."""
        from ....core.vault import device_unlocks_of
        if self.service or self.vault_path is None:
            return {"possible": False, "devices": []}
        return {"possible": True, "devices": device_unlocks_of(self.vault_path)}

    async def add_device_unlock(self, data: dict) -> dict:
        """``POST /api/device-unlock`` ``{"passphrase", "id", "secret", "label"}``: let this
        device open the vault with ``secret`` (b64, 32 octets or more), which its secure
        hardware releases only after its PIN or unlock - a passkey's PRF output. Needs the
        vault's passphrase. The passphrase still opens the vault, everywhere."""
        s = self._unlocked()                      # set up or not: it is the vault's
        if self.service:
            raise SessionError("a service has no vault passphrase")
        if not s.vault.path.exists():
            s.vault.save()                        # a new vault: on disk first, to open later
        try:
            await asyncio.to_thread(s.vault.add_device_unlock, str(data.get("passphrase", "")),
                                    str(data.get("id", "")), _b64(data.get("secret", "")),
                                    str(data.get("label", "")))
        except VaultError as exc:
            raise SessionError("The passphrase is not right." if "wrong passphrase" in str(exc)
                               else str(exc)) from exc
        return self.device_unlocks()

    def remove_device_unlock(self, data: dict) -> dict:
        """``POST /api/device-unlock/remove`` ``{"id"}``, or ``{"all": true}``: that device,
        or every one, no longer opens the vault without its passphrase."""
        s = self._unlocked()
        if data.get("all") is True:
            s.vault.remove_device_unlock()
        elif data.get("id"):
            s.vault.remove_device_unlock(str(data["id"]))
        else:
            raise SessionError('give "id", or "all": true')
        return self.device_unlocks()
