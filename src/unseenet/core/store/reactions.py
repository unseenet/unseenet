"""Reactions (UN-RFC 0048): which article each reaction is to, and by whom.

Belongs here: the ``reactions`` index kept beside ``articles`` - filled by ``add`` -,
finding a key's reaction to an article (section 5) and dropping reactions whose
article is gone (section 6.2).

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import reactions as rx


class Reactions:
    def _index_reaction(self, art: Article) -> None:
        """Called by ``add``: remember a plain reaction's target and author."""
        if "Encrypted" in art or not rx.is_reaction(art):
            return
        tgt = rx.target(art)
        if tgt:
            self.db.execute("INSERT OR IGNORE INTO reactions VALUES (?, ?, ?, ?)",
                            (art.message_id, art.group, tgt, art["Author-Key"]))

    def reaction_by(self, target: str, author_key: str) -> str | None:
        """The Message-ID of this key's reaction to ``target`` that we hold, or None."""
        row = self.db.execute(
            "SELECT r.message_id FROM reactions r JOIN articles a USING(message_id)"
            " WHERE r.target=? AND r.author_key=?", (target, author_key)).fetchone()
        return row[0] if row else None

    def drop_orphan_reactions(self) -> int:
        """Delete reactions whose article this node no longer holds (section 6.2).
        An article replaced by an edit (UN-RFC 0042) is not gone: its reactions stay
        while the edit is here. Answers how many."""
        cur = self.db.execute(
            "DELETE FROM articles WHERE message_id IN (SELECT message_id FROM reactions"
            " WHERE target NOT IN (SELECT message_id FROM articles) AND target NOT IN"
            " (SELECT s.old FROM supersedes s JOIN articles a ON a.message_id = s.new))")
        self.db.execute("DELETE FROM reactions WHERE message_id NOT IN"
                        " (SELECT message_id FROM articles)")
        return cur.rowcount
