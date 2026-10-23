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
        s = self.session
        return s is not None and (not s.has_identity() or not s.node)

    async def unlock(self, passphrase: str) -> dict:
        if self.service:
            raise SessionError("a service has no vault to unlock")
        if self.session is None:
            fast = os.environ.get("UNSEENET_INSECURE_FAST_KDF") == "1"
            kdf = {"ops": 1, "mem": 8192 * 1024} if fast else {}
            self._say("Unlocking vault ...")
            try:
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
