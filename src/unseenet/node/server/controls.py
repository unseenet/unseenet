"""Control articles: key updates and cancels (UN-RFC 0004 sections 6, 7).

Belongs here: ``_accept_control`` (key updates of closed groups, cancels by their
author, the owner or a moderator, and handing pins to kept.py) and a post that arrives
after its cancel.

Not here: pins and pages (kept.py), edits (edits.py).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Controls:
    def _accept_control(self, art: Article, manifest: Manifest, raw: bytes) -> None:
        ctl = art.control or []
        author = art.author_key
        if ctl[0] in ("key-update", "key-grant"):
            if manifest.type != "closed" or author != manifest.owner:
                raise ArticleError("permission", "only the owner of a closed group may issue keys")
            epoch, member_key, _ = parse_key_update(art)
            self.store.add(art, raw)
            if member_key is not None:
                self.store.set_epoch(art.group, epoch, member_key, art.message_id)
                if parse_canonical_json(art.body).get("closes_previous") is True:
                    self.store.close_previous(art.group, epoch)
        elif ctl[0] == "cancel" and len(ctl) == 2:
            if manifest.is_council:                       # UN-RFC 0054 section 6
                raise ArticleError("permission", "cancels are not defined for council groups")
            target = ctl[1]
            meta = self.store.get_meta(target)
            privileged = author == manifest.owner or author in manifest.moderators
            if meta is not None:
                group_id, target_author = meta
                if group_id != art.group:
                    raise ArticleError("permission", "cancel for another group")
                if not privileged and crypto.key_from_text(target_author) != author:
                    raise ArticleError("permission", "not allowed to cancel")
                stored = self.store.get(target)
                if stored is not None and Article.from_bytes(stored).control:
                    # manifests, key updates, cancels: never cancelled (UN-RFC 0004, 7.1)
                    raise ArticleError("permission", "control articles cannot be cancelled")
                self.store.delete(target)
            # remembered also when the target was held: a pin of it is then not in
            # force (UN-RFC 0033 section 4.2, step 2)
            self.store.add_cancel(target, art["Author-Key"], art.group)
            self.store.add(art, raw)
            if meta is not None:
                self.sweep_blobs(retention=False)        # its blobs go too (UN-RFC 0027 7.2)
        elif ctl[0] in (pn.PIN, pn.UNPIN) and len(ctl) == 2:
            self._accept_pin(art, manifest, raw, ctl[0], ctl[1])
        elif ctl[0] in cm.ACTIONS and len(ctl) == 2:            # UN-RFC 0030 section 3.2
            self._accept_comment_marker(art, manifest, raw, ctl[0], ctl[1])
        else:
            raise ArticleError("syntax", f"unknown control {ctl[0]!r}")

    def _check_cancelled(self, art: Article, manifest: Manifest) -> None:
        pending = self.store.cancel_for(art.message_id)
        if not pending:
            return
        author_key, group_id = pending
        canceller = crypto.key_from_text(author_key)
        if group_id == art.group and (canceller == art.author_key or canceller == manifest.owner
                                      or canceller in manifest.moderators):
            self.store.remember(art.message_id)
            raise ArticleError("permission", "article was cancelled")
