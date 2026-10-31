"""Nodes' announcements (UN-RFC 0055 section 5): what a node checks when it takes one.

Belongs here: an announcement must follow section 5.2; one per node key per day; the
node keeps only the newest per key (5.4).

Not here: the rules (``core/announcements.py``), posting this node's own
(``node/announcing.py``).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Announcements:
    def _check_announcement(self, art: Article) -> list[str]:
        """An article in the announcement group: refused unless it is a valid
        announcement, at most one a day per key, and not older than the one held.
        Returns the Message-IDs of the older ones by the same key, to delete once this
        one is stored."""
        from ...core import announcements as an
        from ...known_nodes import NODES_ANNOUNCE_GROUP
        if art.group != NODES_ANNOUNCE_GROUP or art.control:
            return []
        key, date = art["Author-Key"], parse_date(art["Date"])
        if not (art.get("Subject") or "").startswith(an.SUBJECT_PREFIX):
            raise ArticleError("syntax", "an announcement's subject is: node <name>")
        try:
            an.parse(art.body, key=key, date=date)
        except an.AnnouncementProblem as exc:
            raise ArticleError("syntax", f"not an announcement (UN-RFC 0055 5.2): {exc}") from exc
        older = []
        for n in self.store.numbers(art.group):
            found = self.store.by_number(art.group, n)
            if not found:
                continue
            try:
                other = Article.from_bytes(found[1])
                if other["Author-Key"] != key:
                    continue
                when = parse_date(other["Date"])
            except (ArticleError, KeyError, ValueError):
                continue
            if when >= date:
                raise ArticleError("date", "this node holds a newer announcement by this key")
            if date - when < an.ONE_PER:
                raise ArticleError("rate", "one announcement per node a day (UN-RFC 0055 5.4)")
            older.append(found[0])
        return older
