"""The ``LocalAPI`` object: one session - a person's vault, or a service's key (UN-RFC 0046
section 3.2) - and its ``ClientRuntime``.

Belongs here: ``LocalAPI.__init__`` only. Every request of section 4 and the events of
section 5 are in the file named after their section.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class ApiBase:
    def __init__(self, vault_path: Path | None = None, *, session: Session | None = None,
                 service: bool = False, refresh_seconds: float | None = None,
                 ripen_to: int | None = None):
        if (vault_path is None) == (session is None):
            raise ValueError("give a vault path or a session")
        self.vault_path = Path(vault_path) if vault_path is not None else None
        self.service = service
        self.session: Session | None = None
        self.runtime: ClientRuntime | None = None
        self.status = "Locked"
        self.status_idle = False          # status only names the node (#518)
        self.connected = False
        self._refresh_seconds = refresh_seconds
        self._ripen_to = ripen_to if ripen_to is not None else (
            SERVICE_RIPEN_TO if service else RIPEN_TO)
        self._listeners: set[asyncio.Queue] = set()
        self._tasks: set[asyncio.Task] = set()
        self._jobs = 0
        self._send = asyncio.Lock()          # one job at a time: progress belongs to it
        self._job: tuple[str, str] | None = None
        self._off = None
        if session is not None:
            self._attach(session)
