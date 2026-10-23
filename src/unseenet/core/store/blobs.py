"""Blobs (UN-RFC 0027): which articles reference which blobs, and the operator's limits.

Belongs here: the blobs a node stores and since when, the references from articles,
what may be deleted (nothing references it, refused, past retention unless kept),
refused blobs (section 7.3), and the day's octets per key and group (section 8.1).
The octets themselves are files (``core.blobs.BlobStore``).

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class Blobs:
    # --- blobs (UN-RFC 0027 sections 7, 8) ---
    def note_blob(self, bid: str, size: int) -> None:
        """Note that the node stores a blob, and since when (for retention)."""
        self.db.execute("INSERT OR IGNORE INTO blob_meta VALUES (?, ?, ?)", (bid, int(time.time()), size))
        self.db.commit()

    def forget_blob(self, bid: str) -> None:
        """Forget that the node stores a blob (after its file was deleted)."""
        self.db.execute("DELETE FROM blob_meta WHERE blob_id=?", (bid,))
        self.db.commit()

    def blob_refs(self, message_id: str) -> list[tuple[str, int]]:
        """The blobs an article references: ``(blob id, size)``."""
        return list(self.db.execute("SELECT blob_id, size FROM blob_refs WHERE message_id=?",
                                    (message_id,)))

    def blobs_to_delete(self, retention_days: int | None, now: float | None = None) -> list[str]:
        """Section 7.1: stored blobs no stored article references, refused ones, and
        - beyond the node's blob retention - those no kept article references."""
        now = now or time.time()
        self.db.execute("DELETE FROM blob_refs WHERE message_id NOT IN (SELECT message_id FROM articles)")
        self.db.commit()
        out = [r[0] for r in self.db.execute(
            "SELECT blob_id FROM blob_meta WHERE blob_id NOT IN (SELECT blob_id FROM blob_refs) "
            "OR blob_id IN (SELECT blob_id FROM refused_blobs)")]
        if retention_days is not None:
            kept = self.kept_blobs()
            out += [r[0] for r in self.db.execute(
                "SELECT blob_id FROM blob_meta WHERE stored_at < ?", (now - retention_days * 86400,))
                if r[0] not in kept and r[0] not in out]
        return out

    def kept_blobs(self, group_id: str | None = None) -> dict[str, int]:
        """Blobs referenced by kept articles (UN-RFC 0017 2.1), {blob ID: octets}."""
        groups = [group_id] if group_id else [r[0] for r in self.db.execute(
            "SELECT DISTINCT group_id FROM markers")]
        out: dict[str, int] = {}
        for g in groups:
            for mid in self.kept_ids(g):
                out.update(self.blob_refs(mid))
        return out

    def blob_stats(self) -> dict:
        """For the monitor: stored blobs, their octets, refused ones, today's use."""
        count, octets = self.db.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM blob_meta").fetchone()
        refused = self.db.execute("SELECT COUNT(*) FROM refused_blobs").fetchone()[0]
        day = time.strftime("%Y-%m-%d", time.gmtime())
        today = self.db.execute("SELECT COALESCE(SUM(octets), 0) FROM blob_usage WHERE day=? AND kind='group'",
                                (day,)).fetchone()[0]
        return {"count": count, "bytes": octets, "refused": refused, "today": today}

    def refuse_blob(self, bid: str, reason: str = "", source: str = "operator") -> None:
        """Refuse a blob: it is deleted and never taken again (UN-RFC 0027 section 7.3).
        ``source`` is who refused it: the operator, or a key whose refusal list the node
        follows."""
        self.db.execute("INSERT OR IGNORE INTO refused_blobs VALUES (?, ?, ?, ?)",
                        (bid, int(time.time()), reason[:200], source))
        self.db.commit()

    def blob_refused(self, bid: str) -> bool:
        """True when this node refused the blob (UN-RFC 0027 section 7.3)."""
        return self.db.execute("SELECT 1 FROM refused_blobs WHERE blob_id=?", (bid,)).fetchone() is not None

    def blob_usage(self, kind: str, who: str, day: str | None = None) -> int:
        """The octets of blobs taken today (UTC) from one key or for one group
        (``kind`` ``key`` or ``group``), for the daily quotas (UN-RFC 0027 section 8.1)."""
        day = day or time.strftime("%Y-%m-%d", time.gmtime())
        row = self.db.execute("SELECT octets FROM blob_usage WHERE day=? AND kind=? AND who=?",
                              (day, kind, who)).fetchone()
        return row[0] if row else 0

    def charge_blobs(self, key: str, group: str, octets: int) -> None:
        """Count the octets of an article's new blobs against today's quotas of its
        author and its group; counts older than three days are dropped."""
        day = time.strftime("%Y-%m-%d", time.gmtime())
        for kind, who in (("key", key), ("group", group)):
            self.db.execute("INSERT INTO blob_usage VALUES (?, ?, ?, ?) ON CONFLICT(day, kind, who) "
                            "DO UPDATE SET octets = octets + excluded.octets", (day, kind, who, octets))
        self.db.execute("DELETE FROM blob_usage WHERE day < ?",
                        (time.strftime("%Y-%m-%d", time.gmtime(time.time() - 3 * 86400)),))
        self.db.commit()
