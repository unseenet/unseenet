"""Withdrawn articles: cancels (UN-RFC 0004 section 7) and edits (UN-RFC 0042).

Belongs here: remembering cancels (also of articles still to come, and of targets we
held, so a pin of them stops counting) and which version replaced which, with the date
of the earliest version for comments in channels (0042 section 3.2).

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class Withdrawals:
    # --- cancels ---
    def add_cancel(self, target: str, author_key: str, group_id: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO cancels VALUES (?, ?, ?)", (target, author_key, group_id))
        self.db.commit()

    def cancel_for(self, target: str) -> tuple[str, str] | None:
        row = self.db.execute("SELECT author_key, group_id FROM cancels WHERE target=?",
                              (target,)).fetchone()
        return (row[0], row[1]) if row else None

    # --- edits (UN-RFC 0042) ---
    def add_supersede(self, old: str, new: str, author_key: str, group_id: str, kind: str,
                      first_date: int | None) -> None:
        """Record that ``new`` replaces ``old`` - held and withdrawn, or not seen yet
        (a pending supersede, section 3.1). The newest edit wins."""
        self.db.execute("INSERT OR REPLACE INTO supersedes VALUES (?, ?, ?, ?, ?, ?)",
                        (old, new, author_key, group_id, kind, first_date))

    def supersede_for(self, old: str) -> tuple[str, str, str, str] | None:
        """(edit, author_key, group_id, kind) for a replaced version, or None."""
        row = self.db.execute("SELECT new, author_key, group_id, kind FROM supersedes WHERE old=?",
                              (old,)).fetchone()
        return tuple(row) if row else None

    def first_date(self, message_id: str) -> int | None:
        """The Date of the earliest version known of a post, given any version of it
        (section 3.2); None if it was never edited or no date is known."""
        row = self.db.execute(
            "SELECT MIN(first_date) FROM supersedes WHERE new=? OR old=? OR new IN "
            "(SELECT new FROM supersedes WHERE old=?)", (message_id, message_id, message_id)
        ).fetchone()
        return row[0] if row else None

    def date_of(self, message_id: str) -> int | None:
        row = self.db.execute("SELECT date FROM articles WHERE message_id=?",
                              (message_id,)).fetchone()
        return row[0] if row else None
