"""Kept articles (UN-RFC 0017 section 2.1): what a group keeps beyond its window.

Belongs here: working out the kept articles of a group from what the node holds and
the current manifest (``kept_ids``): pins and unpins (UN-RFC 0033: ``markers``,
``pins_in_force``, a pin following an edit) and the pages of sites (UN-RFC 0035:
``page_versions``, ``site``, ``site_kept`` - current and previous versions). A new kind
of kept article adds its table to the schema and its part to ``kept_ids``.

Part of ``Store`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file


class Kept:
    def add_marker(self, art: Article, action: str, target: str, replaces=()) -> None:
        """Remember a pin or unpin of ``target`` (UN-RFC 0033), with the markers it
        replaces (``Supersedes``)."""
        self.db.execute("INSERT OR IGNORE INTO markers VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (art.message_id, art.group, target, action, art["Author-Key"],
                         int(parse_date(art["Date"]).timestamp()), " ".join(replaces)))
        self.db.commit()

    def markers(self, group_id: str, actions=(pn.PIN, pn.UNPIN)) -> list[pn.Marker]:
        """Every marker held for a group of the given ``actions``: pins and unpins
        (UN-RFC 0033) by default; ``comments-close``/``comments-open`` (UN-RFC 0030 3.2)
        live in the same table."""
        marks = ",".join("?" * len(actions))
        return [pn.Marker(mid, target, action, author, date, tuple(sup.split()))
                for mid, target, action, author, date, sup in self.db.execute(
                    "SELECT message_id, target, action, author_key, date, supersedes "
                    f"FROM markers WHERE group_id=? AND action IN ({marks})",
                    (group_id, *actions))]

    def marker_action(self, message_id: str) -> str | None:
        """The action of a marker we hold (pin, unpin, comments-close, comments-open)."""
        row = self.db.execute("SELECT action FROM markers WHERE message_id=?",
                              (message_id,)).fetchone()
        return row[0] if row else None

    # --- comments on one entry (UN-RFC 0030 sections 3.1, 3.2) ---
    def comments_closed(self, group_id: str, target: str, target_author: str,
                        manifest: Manifest | None = None) -> pn.Marker | None:
        """The close that keeps comments on ``target`` closed, or None (section 3.2)."""
        from ..comments import ACTIONS, deciding_close
        m = manifest or self.manifest(group_id)
        if m is None:
            return None
        return deciding_close(self.markers(group_id, ACTIONS), target, target_author,
                              {crypto.key_to_text(k) for k in (m.owner, *m.moderators)})

    def root_days(self, root: str) -> int | None:
        """The shortest ``Comment-Days`` an edit of the thread root ``root`` gave it."""
        row = self.db.execute("SELECT days FROM root_days WHERE root=?", (root,)).fetchone()
        return row[0] if row else None

    def set_root_days(self, root: str, group_id: str, days: int) -> None:
        """An edit of a root shortened its time for comments (section 3.1): kept shortest."""
        self.db.execute("INSERT INTO root_days VALUES (?, ?, ?) ON CONFLICT(root) DO UPDATE "
                        "SET days=MIN(days, excluded.days)", (root, group_id, days))
        self.db.commit()

    def marker(self, message_id: str) -> tuple[str, str] | None:
        """(group, target) of a pin or unpin we hold."""
        row = self.db.execute("SELECT group_id, target FROM markers WHERE message_id=?",
                              (message_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def current_version(self, message_id: str) -> str:
        """An edited post's current version (UN-RFC 0042); the post itself otherwise."""
        row = self.db.execute("SELECT new FROM supersedes WHERE old=?", (message_id,)).fetchone()
        return row[0] if row else message_id

    def withdrawn(self, group_id: str) -> set[str]:
        """Targets withdrawn by a valid cancel (UN-RFC 0033 section 4.2, step 2)."""
        return {r[0] for r in self.db.execute("SELECT target FROM cancels WHERE group_id=?",
                                              (group_id,))}

    def pins_in_force(self, group_id: str, manifest: Manifest | None = None,
                      extra: list[pn.Marker] = ()) -> list[pn.Marker]:
        """The pins in force (UN-RFC 0033 section 4.2), newest first, also those whose
        target has not arrived yet (pending). ``extra``: markers not stored yet."""
        m = manifest or self.manifest(group_id)
        if m is None or m.type in ("inbox",) or m.local:
            return []
        try:
            limit = pn.max_pins(m.raw)
        except ValueError:
            return []
        return pn.in_force([*self.markers(group_id), *extra], owner=crypto.key_to_text(m.owner),
                           moderators=[crypto.key_to_text(k) for k in m.moderators],
                           limit=limit, withdrawn=self.withdrawn(group_id))

    # --- council groups (UN-RFC 0054 section 6): the copies that make the chain ---
    def add_council_copy(self, art: Article, seq: int) -> None:
        """Remember a member's copy of a council manifest, for counting the chain."""
        self.db.execute("INSERT OR IGNORE INTO council_copies VALUES (?, ?, ?, ?)",
                        (art.message_id, art.group, seq, art["Author-Key"]))
        self.db.commit()

    def council_copies(self, group_id: str) -> list[tuple[bytes, str, str]]:
        """(author key, body, Message-ID) of every council manifest copy held, by seq."""
        out = []
        for mid, author in list(self.db.execute(
                "SELECT message_id, author_key FROM council_copies WHERE group_id=? "
                "ORDER BY seq, message_id", (group_id,))):
            raw = self.get(mid)
            if raw is not None:
                out.append((crypto.key_from_text(author), Article.from_bytes(raw).body, mid))
        return out

    def council_chain(self, group_id: str):
        """The counted chain of a council group (core.council.count_chain)."""
        from ..council import count_chain
        return count_chain(group_id, [(a, b) for a, b, _ in self.council_copies(group_id)])

    def council_kept(self, group_id: str) -> list[str]:
        """Section 6: enough identical copies of every counted manifest to make it
        count, kept whatever the retention - oldest first, so a node catching up
        can count the chain as it goes."""
        if self.db.execute("SELECT 1 FROM council_copies WHERE group_id=? LIMIT 1",
                           (group_id,)).fetchone() is None:
            return []
        from ..council import copies_to_keep
        copies = self.council_copies(group_id)
        keep = copies_to_keep(self.council_chain(group_id), copies)
        return [mid for _, _, mid in copies if mid in keep]

    def kept_ids(self, group_id: str, *, window_days: int | None = None,
                 now: float | None = None) -> list[str]:
        """The group's kept articles in listing order (UN-RFC 0017 sections 2.1, 3):
        pins in force, the latest unpin of a target while inside the window, then
        the pinned targets. At most 256 targets (section 2.2)."""
        has_markers = self.db.execute("SELECT 1 FROM markers WHERE group_id=? LIMIT 1",
                                      (group_id,)).fetchone() is not None
        has_pages = self.db.execute("SELECT 1 FROM pages WHERE group_id=? LIMIT 1",
                                    (group_id,)).fetchone() is not None
        council = self.council_kept(group_id)
        if not has_markers and not has_pages:
            return council               # most groups: nothing kept, nothing to work out
        m = self.manifest(group_id)
        if m is None:
            return []
        days = m.retention_days if window_days is None else window_days
        since = (now or time.time()) - days * 86400
        site = self.site_kept(group_id, m, since) if has_pages else []
        if not has_markers:
            return council + site
        pins = self.pins_in_force(group_id, m)
        allowed = {crypto.key_to_text(m.owner), *(crypto.key_to_text(k) for k in m.moderators)}
        unpins = sorted((u for u in pn.current(self.markers(group_id), allowed).values()
                         if u.action == pn.UNPIN and u.date >= since),
                        key=lambda u: u.newest_first)
        # an edited post is kept as its current version (UN-RFC 0033 section 5.1)
        targets = [self.current_version(p.target) for p in pins][:pn.KEPT_PER_GROUP]
        out = council + [p.message_id for p in pins] + [u.message_id for u in unpins] + targets
        return out + [s for s in site if s not in out][:max(0, pn.KEPT_PER_GROUP - len(targets))]

    # --- sites (UN-RFC 0035): page versions as kept articles ---
    def add_page(self, art: Article, path: str, removed: bool, supersedes=()) -> None:
        """Remember a page article of a site: its path, whether it is a removal, and the
        versions it replaces (UN-RFC 0035)."""
        self.db.execute("INSERT OR IGNORE INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (art.message_id, art.group, path, art["Author-Key"],
                         int(parse_date(art["Date"]).timestamp()), int(removed), " ".join(supersedes)))
        self.db.commit()

    def page(self, message_id: str) -> tuple[str, str] | None:
        """(group, path) of a page article we hold."""
        row = self.db.execute("SELECT group_id, path FROM pages WHERE message_id=?",
                              (message_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def page_versions(self, group_id: str) -> list[pg.Version]:
        """The page versions of a site that count: held, and not cancelled
        (UN-RFC 0035 section 5.1)."""
        gone = self.withdrawn(group_id)                  # cancelled: they do not count (5.1)
        return [pg.Version(mid, path, author, date, bool(removed), tuple(sup.split()))
                for mid, path, author, date, removed, sup in self.db.execute(
                    "SELECT message_id, path, author_key, date, removed, supersedes FROM pages "
                    "WHERE group_id=? AND message_id IN (SELECT message_id FROM articles)",
                    (group_id,))
                if mid not in gone]

    def site(self, group_id: str, manifest: Manifest | None = None,
             extra: list[pg.Version] = ()) -> tuple[dict, list[str]]:
        """(current versions by path, paths in force) of a site (sections 5.1, 5.2)."""
        m = manifest or self.manifest(group_id)
        if m is None or m.view != "pages":
            return {}, []
        allowed = {crypto.key_to_text(k) for k in (m.owner, *m.moderators, *m.posters)}
        currents = pg.current_versions([*self.page_versions(group_id), *extra], allowed)
        force = pg.in_force(currents, max_pages=m.raw.get("max_pages", pg.MAX_PAGES_DEFAULT),
                            home=m.raw.get("home", pg.HOME_DEFAULT))
        return currents, force

    def site_kept(self, group_id: str, manifest: Manifest | None = None, since: float = 0,
                  extra: list[pg.Version] = ()) -> list[str]:
        """Section 6.1: the current and previous version of every page in force, by
        path, and a current removal while inside the window."""
        currents, force = self.site(group_id, manifest, extra)
        out = []
        for path in sorted(force):
            cur, prev = currents[path]
            out.append(cur.message_id)
            if prev is not None:
                out.append(prev.message_id)
        out += [cur.message_id for p, (cur, _) in sorted(currents.items())
                if cur.removed and cur.date >= since]
        return out
