"""Labels (UN-RFC 0019): how people and groups are shown, by name or key.

Belongs here: reading the registrar's lists (``refresh_naming``) and turning keys and
Group IDs into what a front end shows - a verified name, a contact's name, a short
form with the fingerprint (``label_of``, ``identity_label``, ``group_label``), so every
client names people alike.

Not here: claiming or giving names (``unseenet.names``), contacts (people.py).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class LabelsMixin:
    async def refresh_naming(self) -> bool:
        """Read the root list, hierarchy lists and names (UN-RFC 0018, 0019). True if changed."""
        return await naming.refresh(self)

    def group_label(self, group_id: str, also_known: set[str] = frozenset()) -> str:
        """The name to show for a group: without the fingerprint where UN-RFC 0018 allows."""
        return naming.group_label(self, group_id, also_known)

    def identity_label(self, key_text: str, from_name: str = "") -> str:
        """Petname, else @domain, else @name, else Name~abcd (UN-RFC 0019 section 8)."""
        return naming.identity_label(self, key_text, from_name)

    def seen_name(self, key_text: str | None) -> str:
        """The name someone gave themselves in a post we have, newest first, for
        naming a bare key (a chat partner, a moderator): "" if none is seen."""
        best, at = "", None
        for msgs in self.cache.values():
            for m in msgs.values():
                if m.author_key == key_text and m.from_name and (at is None or (m.date and m.date > at)):
                    best, at = m.from_name, m.date
        return best

    def label_of(self, key_text: str) -> str:
        """``identity_label`` for a bare key, with the name seen in its posts."""
        return self.identity_label(key_text, self.seen_name(key_text))

    def _identity_for_fingerprint(self, fp: str) -> crypto.Identity | None:
        for entry in self.data["identities"].values():
            ident = crypto.Identity.from_seed(bytes.fromhex(entry["seed"]))
            if ident.fingerprint == fp:
                return ident
        return None
