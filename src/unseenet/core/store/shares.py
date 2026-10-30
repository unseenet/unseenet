"""Shares (UN-RFC 0060): which article each share refers to, and by whom.

Belongs here: the ``shares`` index kept beside ``articles`` - filled by ``add`` -, and
finding a key's shares of an article (section 7.2: at most three groups besides the
sharer's own feed).

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import shares as sh


class Shares:
    def _index_share(self, art: Article) -> None:
        """Called by ``add``: remember a plain share's or a share with a comment's
        target and author."""
        if "Encrypted" in art or not sh.is_share(art):
            return
        tgt = sh.target(art)
        if tgt:
            self.db.execute("INSERT OR IGNORE INTO shares VALUES (?, ?, ?, ?)",
                            (art.message_id, art.group, tgt[0], art["Author-Key"]))

    def shares_by(self, target: str, author_key: str) -> list[tuple[str, str]]:
        """``(Message-ID, group)`` of every share of ``target`` by this key that we
        still hold."""
        return [tuple(r) for r in self.db.execute(
            "SELECT s.message_id, s.group_id FROM shares s JOIN articles a USING(message_id)"
            " WHERE s.target=? AND s.author_key=?", (target, author_key))]
