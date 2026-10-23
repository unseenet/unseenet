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
        self.db.execute("INSERT OR IGNORE INTO markers VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (art.message_id, art.group, target, action, art["Author-Key"],
                         int(parse_date(art["Date"]).timestamp()), " ".join(replaces)))
        self.db.commit()

    def markers(self, group_id: str) -> list[pn.Marker]:
        return [pn.Marker(mid, target, action, author, date, tuple(sup.split()))
                for mid, target, action, author, date, sup in self.db.execute(
                    "SELECT message_id, target, action, author_key, date, supersedes "
                    "FROM markers WHERE group_id=?", (group_id,))]

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

    def kept_ids(self, group_id: str, *, window_days: int | None = None,
                 now: float | None = None) -> list[str]:
        """The group's kept articles in listing order (UN-RFC 0017 sections 2.1, 3):
        pins in force, the latest unpin of a target while inside the window, then
        the pinned targets. At most 256 targets (section 2.2)."""
        has_markers = self.db.execute("SELECT 1 FROM markers WHERE group_id=? LIMIT 1",
                                      (group_id,)).fetchone() is not None
        has_pages = self.db.execute("SELECT 1 FROM pages WHERE group_id=? LIMIT 1",
                                    (group_id,)).fetchone() is not None
        if not has_markers and not has_pages:
            return []                    # most groups: nothing kept, nothing to work out
        m = self.manifest(group_id)
        if m is None:
            return []
        days = m.retention_days if window_days is None else window_days
        since = (now or time.time()) - days * 86400
        site = self.site_kept(group_id, m, since) if has_pages else []
        if not has_markers:
            return site
        pins = self.pins_in_force(group_id, m)
        allowed = {crypto.key_to_text(m.owner), *(crypto.key_to_text(k) for k in m.moderators)}
        unpins = sorted((u for u in pn.current(self.markers(group_id), allowed).values()
                         if u.action == pn.UNPIN and u.date >= since),
                        key=lambda u: u.newest_first)
        # an edited post is kept as its current version (UN-RFC 0033 section 5.1)
        targets = [self.current_version(p.target) for p in pins][:pn.KEPT_PER_GROUP]
        out = [p.message_id for p in pins] + [u.message_id for u in unpins] + targets
        return out + [s for s in site if s not in out][:max(0, pn.KEPT_PER_GROUP - len(targets))]

    # --- sites (UN-RFC 0035): page versions as kept articles ---
    def add_page(self, art: Article, path: str, removed: bool, supersedes=()) -> None:
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
