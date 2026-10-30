"""Shares (UN-RFC 0060): the rules a node checks with what it holds.

Belongs here: ``_check_share`` - a share of an encrypted article the node holds is
refused (section 12), as is one of an article whose author or group asked not to be
shared (section 4.4, a node MAY), and a fourth share of one article by one key in other
groups than its own feed (section 7.2).

Not here: the form of a share and ``share_into`` (core/shares.py, checked through
``check_permitted``), fetching targets (fetch_commands.py, fetching.py).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from ...core import shares as sh


class Shares:
    def _check_share(self, art: Article) -> None:
        """Raise ArticleError('permission') for a share the node must or may refuse.
        Only what the node holds is checked: a target it does not hold is not looked
        for here."""
        if "Encrypted" in art or not sh.is_share(art):
            return
        tgt_id, tgt_group = sh.target(art)
        raw = self.store.get(tgt_id)
        if raw is not None:
            try:
                tgt = Article.from_bytes(raw)
            except ArticleError:
                tgt = None
            if tgt is not None:
                m = self.store.manifest(tgt.group)
                if tgt.group != tgt_group:
                    raise ArticleError("permission", "Share-Group is not the group of the "
                                                     "article shared")
                why = sh.why_not(tgt, m.raw if m is not None else None)
                if why == "closed things are not shared":
                    raise ArticleError("permission", "an encrypted article cannot be shared")
                if why == "the author asked not to share this":
                    raise ArticleError("permission", why)
                if why is not None and why != "share the original instead":
                    raise ArticleError("permission", f"cannot be shared: {why}")
        own = sh.own_feed(art.author_key)
        if art.group == own:
            return
        others = [g for mid, g in self.store.shares_by(tgt_id, art["Author-Key"])
                  if g != own and g != art.group and mid not in parse_supersedes(art)]
        if len(set(others)) >= sh.MAX_INTO:
            raise ArticleError("permission", f"a key shares one article into at most "
                                             f"{sh.MAX_INTO} groups besides its own feed")
