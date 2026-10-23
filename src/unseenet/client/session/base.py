"""The vault, identities, settings and events. Part of Session (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class BaseMixin:
    def __init__(self, vault: Vault, status=print):
        self.vault = vault
        self.status = status            # callback for progress messages (one line of text)
        self._listeners: list = []      # typed events (unseenet #139): Session.on()
        self._ripe_locks: dict[str, asyncio.Lock] = {}   # one ripening per identity
        self._sender_chains: dict[str, tuple] = {}       # senders' verified chains (0025, 3.5)
        self._sender_levels: dict[str, int | None] = {}  # private post -> its sender's level
        self.tor: _s.TorProcess | None = None
        self._tor_lock = asyncio.Lock()   # one Tor per session, however many connect at once
        self._checked_socks: Socks | None = None        # an existing Tor that answered
        self._clients: dict[str, Client] = {}          # one connection per node
        # a node that failed or refused is tried again only after a random, growing
        # wait (UN-RFC 0043 section 4.4, #297): not everyone at once after a restart
        self._backoff: dict[str, Backoff] = {}
        self._retry_at: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.unreachable: list[str] = []               # nodes that did not answer last time
        self.cache: dict[str, dict[int, Message]] = {}
        self._acting_as: str | None = None   # act_as(): an identity for this run only
        self._raw: dict[str, dict[int, bytes]] = {}   # what the offline cache stores
        self._high: dict[str, int] = {}               # highest article number fetched
        d = self.vault.data
        d.setdefault("identities", {})
        d.setdefault("groups", {})
        d.setdefault("nodes", [])
        d.setdefault("subscribed", [])
        d.setdefault("read", {})
        d.setdefault("contacts", {})
        d.setdefault("ignored", {})                    # keys you do not want to see (#72)
        if d["nodes"]:          # groups from before several nodes: they live on the first
            for entry in d["groups"].values():
                entry.setdefault("node", d["nodes"][0])
        self.sent: list[dict] = self._load_sent()
        self._notice_tasks: dict[str, asyncio.Task] = {}   # approved notices being posted

    # ------------------------------------------------------------------
    # identities & settings
    # ------------------------------------------------------------------
    @property
    def data(self) -> dict:
        return self.vault.data

    @classmethod
    def from_key(cls, identity: crypto.Identity, state_path, *, name: str = "service",
                 display: str | None = None, status=print) -> "Session":
        """A session for a service with only a key: a gateway, a bot, a registrar
        (client/headless.py). Everything but the key is kept in ``state_path``."""
        from ..headless import KeyStore
        return cls(KeyStore(identity, state_path, name, display), status=status)

    def save(self) -> None:
        self.vault.save()

    def change_passphrase(self, old: str, new: str) -> None:
        """A new passphrase for the vault file (slow: runs the key derivation twice).

        Only this file changes; copies of it elsewhere still open with the old one.
        Raises VaultError if ``old`` is wrong."""
        self.vault.change_passphrase(old, new)

    def has_identity(self) -> bool:
        return bool(self.data["identities"])

    # --- events (unseenet #139) ---
    def on(self, callback):
        """Call ``callback(event)`` for every event (``client.events``); returns a
        function that stops it. Callbacks run on the event loop and must not block."""
        self._listeners.append(callback)

        def off() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)
        return off

    def emit(self, event: ev.Event) -> None:
        for callback in list(self._listeners):
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - a client's bug must not stop the session
                log.exception("event callback failed for %s", event.name)

    def say(self, text: str) -> None:
        """A status line: to the old ``status`` callback and as a ``Status`` event."""
        self.status(text)
        self.emit(ev.Status(text))

    async def _compute(self, fn):
        """Run ``fn`` (building and stamping an article) in a worker thread,
        reporting postage progress as ``PowProgress`` events."""
        loop = asyncio.get_running_loop()

        def progress(attempts: int, expected: int, done: bool) -> None:
            loop.call_soon_threadsafe(self.emit, ev.PowProgress(attempts, expected, done))

        def run():
            with postage.reporting(progress):
                return fn()
        return await loop.run_in_executor(None, run)
