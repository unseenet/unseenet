"""The vault, identities, settings and events: what every other part stands on.

Belongs here: opening a session (``__init__``, ``from_key`` for services), saving the
vault and changing its passphrase; the identities in it (``identity``, ``new_identity``,
``act_as``, ``display_name``); the user's settings that are not about one area (the
signature, Markdown or plain text); and events (``on``, ``emit``, ``say``) that tell
front ends what happened (``client.events``).

Not here: anything that talks to a node (nodes.py), a group (groups.py) or a person
(people.py, private.py).
"""

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
        self._down_since: dict[str, float] = {}       # failing since (#603, #605)
        self._locks: dict[str, asyncio.Lock] = {}
        self.unreachable: list[str] = []               # nodes that did not answer last time
        # nodes asked but not answered yet, past the first answer's budget (#704): their
        # answer is still awaited, in the background, and the rest carry on without them
        self.slow: dict[str, asyncio.Task] = {}
        self.cache: dict[str, dict[int, Message]] = {}
        self.reaction_msgs: dict[str, dict[int, Message]] = {}   # beside cache (UN-RFC 0048)
        self._acting_as: str | None = None   # act_as(): an identity for this run only
        self.ripening_limit: int | None = None   # the level this machine can ripen to (#440)
        # a program, not a person (bot, gateway, help bot): it keeps its own names up
        # once a day when it posts (naming.keep_my_names), as clients do in refresh
        self.service = False
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
        """The vault's contents (a dict): identities, nodes, groups, settings. Change it
        and call ``save()``; clients should prefer the functions that do that for them."""
        return self.vault.data

    @classmethod
    def from_key(cls, identity: crypto.Identity, state_path, *, name: str = "service",
                 display: str | None = None, status=print) -> "Session":
        """A session for a service with only a key: a gateway, a bot, a registrar
        (client/headless.py). Everything but the key is kept in ``state_path``."""
        from ..headless import KeyStore
        s = cls(KeyStore(identity, state_path, name, display), status=status)
        s.service = True
        return s

    def save(self) -> None:
        """Write the vault to disk (encrypted, UN-RFC 0007)."""
        self.vault.save()

    def change_passphrase(self, old: str, new: str) -> None:
        """A new passphrase for the vault file (slow: runs the key derivation twice).

        Only this file changes; copies of it elsewhere still open with the old one.
        Raises VaultError if ``old`` is wrong."""
        self.vault.change_passphrase(old, new)

    def has_identity(self) -> bool:
        """True when the vault has at least one identity."""
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
        """Tell every listener (``on``) about an event (``client.events``). A listener
        that raises is logged and skipped, so a front end's bug cannot stop the session."""
        for callback in list(self._listeners):
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - a client's bug must not stop the session
                log.exception("event callback failed for %s", event.name)

    def say(self, text: str, idle: bool = False) -> None:
        """A status line: to the old ``status`` callback and as a ``Status`` event
        (``idle`` when it only says a node is reached)."""
        self.status(text)
        self.emit(ev.Status(text, idle))

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

    # --- key ripening (UN-RFC 0025) ---
    def _identity_named_by(self, key) -> str | None:
        """The name of our identity with this public key (bytes or text), if it is ours."""
        try:
            text = key if isinstance(key, str) else crypto.key_to_text(key)
        except (crypto.CryptoError, TypeError, ValueError):
            return None
        for name in self.data["identities"]:
            if self.identity(name).key_text == text:
                return name
        return None

    def default_identity_name(self) -> str:
        """The name of the identity in use: the one ``act_as`` chose for this run, else
        the vault's default, else the first. ``SessionError`` if there is none yet."""
        ids = self.data["identities"]
        if not ids:
            raise SessionError("no identity yet")
        name = self._acting_as or self.data.get("default_identity")
        return name if name in ids else next(iter(ids))

    def act_as(self, name: str | None) -> None:
        """Use the identity ``name`` for this run, without changing the vault's
        default (a command-line client's -i)."""
        if name is not None and name not in self.data["identities"]:
            raise SessionError(f"no identity {name!r} in this vault")
        self._acting_as = name

    def identity(self, name: str | None = None) -> crypto.Identity:
        """An identity's key pair (``crypto.Identity``), by name; by default the one in
        use (``default_identity_name``)."""
        entry = self.data["identities"][name or self.default_identity_name()]
        made = self.__dict__.setdefault("_identities_made", {})   # asked for every post shown (#724)
        if entry["seed"] not in made:
            made[entry["seed"]] = crypto.Identity.from_seed(bytes.fromhex(entry["seed"]))
        return made[entry["seed"]]

    def my_fingerprints(self) -> tuple[str, ...]:
        """The fingerprints of all your identities (owner:me in a group search, #13)."""
        return tuple(crypto.fingerprint(crypto.Identity.from_seed(bytes.fromhex(e["seed"])).public_key)
                     for e in self.data["identities"].values())

    def display_name(self, name: str | None = None) -> str:
        """The display name (``From``) of an identity, by default the one in use."""
        return self.data["identities"][name or self.default_identity_name()]["display"]

    def signature_template(self, name: str | None = None) -> str:
        # no "signature" yet: the default; one set to "" by the user: none
        """An identity's signature template: the default until the user sets one, and
        empty when they chose none."""
        return self.data["identities"][name or self.default_identity_name()].get(
            "signature", DEFAULT_SIGNATURE)

    def set_signature(self, template: str, name: str | None = None) -> None:
        """Set an identity's signature template (at most ``MAX_SIG_LINES`` lines;
        ``{name}`` and ``{key}`` are filled in). An empty template means none."""
        lines = template.strip("\n").split("\n") if template.strip() else []
        if len(lines) > MAX_SIG_LINES:
            raise SessionError(f"a signature has at most {MAX_SIG_LINES} lines")
        self.data["identities"][name or self.default_identity_name()]["signature"] = "\n".join(lines)
        self.save()

    def signature(self, name: str | None = None) -> str:
        """The signature with {name}, {key} and {fp} filled in ('' if none)."""
        template = self.signature_template(name)
        if not template:
            return ""
        ident = self.identity(name)
        for placeholder, value in (("{name}", self.display_name(name)), ("{key}", ident.key_text),
                                   ("{fp}", ident.fingerprint[:4])):
            template = template.replace(placeholder, value)
        return template

    def new_identity(self, name: str, display: str | None = None) -> crypto.Identity:
        """Make a new identity, with ``display`` as its name in ``From`` (default: its
        name) and the default signature. The first one becomes the vault's default."""
        ident = crypto.Identity.generate()
        self.data["identities"][name] = {"seed": ident.seed.hex(), "display": display or name,
                                         "signature": DEFAULT_SIGNATURE}
        self.data.setdefault("default_identity", name)
        self.save()
        return ident

    def text_type(self) -> str:
        """The Content-Type your posts get: Markdown, unless you turned it off (UN-RFC 0031)."""
        from ...core.markup import MARKDOWN_TYPE, PLAIN_TYPE
        return PLAIN_TYPE if self.data.get("plain_text") else MARKDOWN_TYPE

    def set_markdown(self, on: bool) -> None:
        """Whether you write in Markdown (UN-RFC 0031) or plain text."""
        self.data["plain_text"] = not on
        self.save()
