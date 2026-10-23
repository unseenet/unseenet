"""Opening the store, and its history: which Message-IDs the node has seen.

Belongs here: ``Store.__init__`` (the SQLite file, the schema in ``__init__.py``, small
migrations of older stores) and the history that makes a node take an article once
(``seen``, ``remember``), and the articles refused when pulled from a peer (#132).

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class StoreBase:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = None if str(path) == ":memory:" else Path(path)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()
        self._backfill_epoch_articles()
        if not self.db.execute("SELECT 1 FROM kb_meta").fetchone():
            self.kb_rebuild()                 # stores from before UN-RFC 0040

    def _backfill_epoch_articles(self) -> None:
        """Stores from before UN-RFC 0017 did not record which articles define epochs."""
        if self.db.execute("SELECT 1 FROM epoch_articles LIMIT 1").fetchone():
            return
        if not self.db.execute("SELECT 1 FROM epochs LIMIT 1").fetchone():
            return
        from ..groups import parse_key_update
        for msgid, gid, raw in list(self.db.execute(
                "SELECT message_id, group_id, raw FROM articles WHERE instr(raw, ?) > 0",
                (b"Control: key-update",))):
            try:
                epoch, member_key, _ = parse_key_update(Article.from_bytes(raw))
            except Exception:  # noqa: BLE001
                continue
            if member_key is not None:
                self.db.execute("INSERT OR IGNORE INTO epoch_articles VALUES (?, ?, ?)",
                                (gid, epoch, msgid))
        self.db.commit()

    # --- history ---
    def seen(self, message_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM history WHERE message_id=?",
                               (message_id,)).fetchone() is not None

    def refuse(self, message_id: str, peer: str, reason: str) -> None:
        """Note that an article pulled from ``peer`` was refused, so it is not fetched
        from that peer again. Unlike history, this never refuses the article itself:
        it may still be posted by a client, or arrive once our policy allows it."""
        self.db.execute("INSERT OR REPLACE INTO refused VALUES (?, ?, ?, ?)",
                        (message_id, peer, reason, int(time.time())))

    def refused_from(self, message_id: str, peer: str) -> bool:
        return self.db.execute("SELECT 1 FROM refused WHERE message_id=? AND peer=?",
                               (message_id, peer)).fetchone() is not None

    def remember(self, message_id: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO history VALUES (?, ?)",
                        (message_id, int(time.time())))
