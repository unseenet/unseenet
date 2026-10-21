"""A session for a service that has only a key: a gateway, a bot, a registrar.

Every program that posts uses ``Session``, so ripening (UN-RFC 0025), postage,
headers and retries are one piece of code. A service often has no vault, only
a key file. ``KeyStore`` gives ``Session`` what it needs from a vault:

- the identity lives in memory only, from the key; it is never written;
- everything else (nodes, groups, the ripening chain) is kept in a plain
  state file next to it. That holds nothing secret: the chain is public
  (it is published in ``ripe@``), and the rest is what the service follows;
- no offline cache: a service reads what it needs from its node.

    session = Session.from_key(identity, "/var/lib/gateway/state.json")
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..core import crypto

STATE_VERSION = 1


class KeyStore:
    """The parts of ``Vault`` a ``Session`` uses, for one key and a state file."""

    def __init__(self, identity: crypto.Identity, state_path: str | Path,
                 name: str = "service", display: str | None = None):
        self.path = Path(state_path)
        self.data: dict = {}
        if self.path.exists():
            loaded = json.loads(self.path.read_text())
            if loaded.get("v") != STATE_VERSION:
                raise ValueError(f"{self.path}: unknown state version {loaded.get('v')!r}")
            self.data = loaded.get("data", {})
            known = self.data.get("key")
            if known and known != identity.key_text:
                raise ValueError(f"{self.path} belongs to another key ({known})")
        self.data["key"] = identity.key_text
        self.data["identities"] = {name: {"seed": identity.seed.hex(),
                                          "display": display or name, "signature": ""}}
        self.data["default_identity"] = name

    def save(self) -> None:
        """Write everything but the identity, atomically."""
        public = {k: v for k, v in self.data.items() if k != "identities"}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"v": STATE_VERSION, "data": public}, f, separators=(",", ":"))
        os.replace(tmp, self.path)

    # no offline cache for services
    def read_sidecar(self, name: str) -> bytes | None:
        return None

    def write_sidecar(self, name: str, payload: bytes) -> None:
        pass

    def sidecar_path(self, name: str) -> Path:
        return self.path.with_name(f"{self.path.name}.{name}")

    def close(self) -> None:
        pass
