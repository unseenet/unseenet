"""Kept articles (UN-RFC 0017 section 2.1): what a node keeps beyond a group's window.

Belongs here: pins and unpins (UN-RFC 0033), page articles of sites (UN-RFC 0035),
and ``_keep_old``, which lets an article older than the window in when it would be
kept. Which articles are kept is worked out in the store (``Store.kept_ids``).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Kept:
    # --- sites (UN-RFC 0035) ---
    def _check_page(self, art: Article, manifest: Manifest, blobs) -> tuple:
        """Section 4.3: valid in a site, by a writer, with the headers of 4.2 and a
        Supersedes that names only pages of the same path (4.4). Its blobs must
        not take the site's kept blobs above 8 MiB (UN-RFC 0017 2.2)."""
        if manifest.view != "pages":
            raise ArticleError("permission", "a page article belongs in a site")
        author = art.author_key
        if author != manifest.owner and author not in manifest.moderators \
                and author not in manifest.posters:
            raise ArticleError("permission", "only the site's writers write pages")
        path, removed, sup = pg.parse_page(art)
        for old in sup:
            held = self.store.page(old)
            if held is not None and held != (art.group, path):
                raise ArticleError("permission", "a new version names pages of its own path")
        if blobs:
            kept = self.store.kept_blobs(art.group)
            extra = sum(n for b, n in blobs if b not in kept)
            if extra and sum(kept.values()) + extra > bl.MAX_KEPT_PER_GROUP:
                raise ArticleError("permission", "the site's kept blobs would pass 8 MiB")
        return path, removed, tuple(sup)

    # --- pins (UN-RFC 0033): the first kind of kept articles (UN-RFC 0017, 2.1) ---
    def _accept_pin(self, art: Article, manifest: Manifest, raw: bytes, action: str,
                    target: str) -> None:
        """Section 3: valid when by the owner or a moderator, in a group that can
        have pins, with a short note (none in closed groups), and - if we hold the
        target - in its group and not of a control article. One that comes before
        its target is kept as pending (UN-RFC 0017 section 2.1)."""
        if not (target.startswith("<") and target.endswith(">")):
            raise ArticleError("syntax", "a pin names a Message-ID")
        if manifest.type == "inbox" or manifest.local:
            raise ArticleError("permission", "no pins in inboxes or local groups")
        author = art.author_key
        if author != manifest.owner and author not in manifest.moderators:
            raise ArticleError("permission", "only the owner or a moderator may pin")
        note = art.body.strip()
        if manifest.type == "closed" and note:
            raise ArticleError("syntax", "a pin in a closed group has no note")
        if len(note) > pn.MAX_NOTE:
            raise ArticleError("syntax", f"a pin's note is at most {pn.MAX_NOTE} characters")
        meta = self.store.get_meta(target)
        if meta is not None:
            if meta[0] != art.group:
                raise ArticleError("permission", "a pin is in the group of its target")
            if Article.from_bytes(self.store.get(target)).control:
                raise ArticleError("permission", "control articles cannot be pinned")
        if action == pn.PIN and meta is not None:        # UN-RFC 0017 2.2: 8 MiB kept per group
            kept = self.store.kept_blobs(art.group)
            extra = sum(n for b, n in self.store.blob_refs(self.store.current_version(target))
                        if b not in kept)
            if extra and sum(kept.values()) + extra > bl.MAX_KEPT_PER_GROUP:
                raise ArticleError("permission", "the group's kept blobs would pass 8 MiB")
        replaces = parse_supersedes(art, control_ok=True)     # section 3.1
        for old in replaces:
            held = self.store.marker(old)
            if held is not None and held != (art.group, target):
                raise ArticleError("permission", "a pin replaces a pin or unpin of the same target")
        self.store.add(art, raw)
        self.store.add_marker(art, action, target, replaces)

    # --- closing comments on one entry (UN-RFC 0030 section 3.2) ---
    def _accept_comment_marker(self, art: Article, manifest: Manifest, raw: bytes,
                               action: str, target: str) -> None:
        """Valid in the group of its target, which is a thread root, by the target's
        author or the owner or a moderator now; never encrypted, a note of at most 256
        characters (none in a closed group); replacing only markers of the same target.
        One that comes before its target is a temporary failure, as a comment is (4.1)."""
        if not (target.startswith("<") and target.endswith(">")):
            raise ArticleError("syntax", "a comments marker names a Message-ID")
        if manifest.type == "inbox" or manifest.local:
            raise ArticleError("permission", "no comments to close in inboxes or local groups")
        if "Encrypted" in art:
            raise ArticleError("syntax", "a comments marker is never encrypted")
        note = art.body.strip()
        if manifest.type == "closed" and note:
            raise ArticleError("syntax", "a comments marker in a closed group has no note")
        if len(note) > cm.MAX_NOTE:
            raise ArticleError("syntax", f"a note is at most {cm.MAX_NOTE} characters")
        root = self._thread_root(target)
        if root is None:
            raise ArticleError("later", "the entry is not on this node yet")
        if root.group != art.group or root.control is not None \
                or (root.get("References") or "").strip():
            raise ArticleError("permission", "comments are closed and opened on a thread root "
                                             "in the same group")
        author = art.author_key
        if author != root.author_key and author != manifest.owner \
                and author not in manifest.moderators:
            raise ArticleError("permission", "only the entry's author, the owner or a moderator "
                                             "closes or opens its comments")
        replaces = parse_supersedes(art, control_ok=True)
        for old in replaces:
            held = self.store.marker(old)
            if held is not None and (held != (art.group, target)
                                     or self.store.marker_action(old) not in cm.ACTIONS):
                raise ArticleError("permission", "a comments marker replaces one of the same entry")
        self.store.add(art, raw)
        self.store.add_marker(art, action, target, replaces)

    def _thread_closed(self, root: Article):
        """The close keeping comments on ``root`` closed, or None (section 3.2)."""
        return self.store.comments_closed(root.group, root.message_id,
                                          crypto.key_to_text(root.author_key))

    def _keep_old(self, art: Article, manifest: Manifest) -> bool:
        """An article older than the window that would be kept (UN-RFC 0017 section
        2.1): a pin that would be in force, or a target a pin in force names."""
        ctl = art.control or []
        if ctl and ctl[0] == pn.PIN and len(ctl) == 2:
            try:
                me = pn.Marker(art.message_id, ctl[1], pn.PIN, art["Author-Key"],
                               int(parse_date(art["Date"]).timestamp()),
                               tuple(parse_supersedes(art, control_ok=True)))
            except (KeyError, ValueError):
                return False
            return any(p.message_id == art.message_id
                       for p in self.store.pins_in_force(art.group, manifest, [me]))
        if ctl:
            return False
        if art.get("Page") is not None and manifest.view == "pages":   # UN-RFC 0035 6.1
            try:
                path, removed, sup = pg.parse_page(art)
            except ArticleError:
                return False
            me = pg.Version(art.message_id, path, art["Author-Key"],
                            int(parse_date(art["Date"]).timestamp()), removed, tuple(sup))
            return art.message_id in self.store.site_kept(art.group, manifest, extra=[me])
        # a pinned post, or an edit of one (UN-RFC 0033 section 4.2, step 2)
        pinned = {p.target for p in self.store.pins_in_force(art.group, manifest)}
        pinned |= {self.store.current_version(t) for t in pinned}
        return art.message_id in pinned or any(v in pinned for v in parse_supersedes(art))
