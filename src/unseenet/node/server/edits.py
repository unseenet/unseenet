"""Edits (UN-RFC 0042): a new version of a post that replaces earlier ones.

Belongs here: checking an edit (same author, group, kind and place in its thread),
withdrawing the versions it names, and a version that arrives after its edit.

Not here: new versions of pages (kept.py: they are kept, not withdrawn).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Edits:
    # --- edits (UN-RFC 0042) ---
    @staticmethod
    def _kind(art: Article) -> str:
        # in a closed group the kind is in the encrypted inner article: unknown here
        return "" if "Encrypted" in art else message_kind(art)

    def _check_edit(self, art: Article, manifest: Manifest, versions: list[str]) -> dict:
        """Section 3.1: every version we hold must be the same author's, in this group,
        of the same kind and place in its thread, and no control article. Returns
        {Message-ID: Date} of the versions held."""
        if manifest.type == "inbox":
            raise ArticleError("permission", "private posts cannot be edited")
        author, kind = art["Author-Key"], self._kind(art)
        refs = art.get("References", "").split()
        held: dict[str, int] = {}
        for v in versions:
            meta = self.store.get_meta(v)
            if meta is None:
                continue
            group_id, v_author = meta
            old = Article.from_bytes(self.store.get(v))
            if group_id != art.group or v_author != author:
                raise ArticleError("permission", "only its author can edit a post")
            if old.control:
                raise ArticleError("permission", "control articles cannot be edited")
            if kind and self._kind(old) and self._kind(old) != kind:
                raise ArticleError("permission", "an edit keeps the kind of the post")
            if old.get("References", "").split() != refs:
                raise ArticleError("permission", "an edit keeps the post's place in its thread")
            held[v] = int(parse_date(old["Date"]).timestamp())
        return held

    def _apply_edit(self, art: Article, versions: list[str], held: dict) -> None:
        """Withdraw the versions held, remember the rest as pending (section 3.1)."""
        store = self.store
        dates = list(held.values()) + [d for d in (store.first_date(v) for v in versions)
                                       if d is not None]
        first = min(dates) if dates else None
        for v in versions:
            if v in held:
                store.delete(v)                    # as a valid cancel (UN-RFC 0004, 7.2)
            store.add_supersede(v, art.message_id, art["Author-Key"], art.group,
                                self._kind(art), first)
        store.db.execute("UPDATE supersedes SET new=? WHERE new IN (%s)" % ",".join("?" * len(versions)),
                         (art.message_id, *versions))
        store.db.commit()
        if held:
            self.sweep_blobs(retention=False)            # an edit withdraws like a cancel

    def _check_superseded(self, art: Article) -> None:
        """A version that arrives after its edit is refused (section 3.1)."""
        pending = self.store.supersede_for(art.message_id)
        if not pending or art.control:
            return
        _, author, group_id, kind = pending
        if group_id == art.group and author == art["Author-Key"] and (
                not kind or not self._kind(art) or kind == self._kind(art)):
            self.store.remember(art.message_id)
            raise ArticleError("permission", "article was replaced by an edit")
