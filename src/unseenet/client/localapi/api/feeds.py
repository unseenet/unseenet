"""Feeds in the local client API (UN-RFC 0046 section 4.14, UN-RFC 0034): the timeline
as the pseudo-group ``timeline:``, following feeds and people, and starting your own
personal feed. What a feed is and whom you follow are ``Session``'s (following.py,
personal.py), as in every client; a feed itself is read like any group (section 4.3).

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from . import addresses as _addr

TIMELINE_LIMIT = 100               # entries in the timeline at a time


class Feeds:
    # --- the timeline (UN-RFC 0034 section 7) ------------------------------------
    @staticmethod
    def _timeline_head(s: Session) -> dict:
        g = GroupInfo(TIMELINE, "The entries of every feed you follow, newest first",
                      view="feed")
        return {**g.to_dict(), "label": "Timeline", "hierarchy": "", "may_post": False,
                "feeds": len(s.feeds_followed())}

    def _timeline_group(self, s: Session) -> dict:
        """``GET /api/groups/timeline:``: the entries of the timeline in its order, each
        followed by its comments as its own feed has them, each row with ``reply`` and
        ``comment`` for the entry's own feed - writing goes to that feed."""
        head = self._timeline_head(s)
        entries = s.timeline(limit=TIMELINE_LIMIT)
        under: dict[str, list] = {}
        for gid in {m.group for m in entries}:
            current = None
            for m, depth in s.feed_rows(gid):
                if depth == 0:
                    current = under.setdefault(m.message_id, [])
                elif current is not None:
                    current.append((m, depth))
        rows = [r for m in entries for r in [(m, 0), *under.get(m.message_id, [])]]
        mine, patterns = s.my_message_ids(), s._mention_patterns()
        keys = {s.identity(n).key_text for n in s.data["identities"]}
        out = []
        for m, depth in rows:
            row = self._row(s, m, depth, mine, patterns, keys)
            row.update(self._feed_row(s, m.group, m), group_label=s.group_label(m.group),
                       address=_addr.post_address(s, m.group, m.message_id))
            out.append(row)
        if self.runtime is not None:            # a feed followed but not read yet
            self.spawn(self._unknown_manifests())
        return {"group": head, "rows": out}

    @staticmethod
    def _feed_row(s: Session, gid: str, m: Message) -> dict:
        """What a feed's row adds (UN-RFC 0034 section 4.2): may you answer it with a post
        (``reply``) or with a comment, a chat line (``comment``)."""
        return {"reply": _perm(s.write_permission(gid, reply_to=m, kind=KIND_POST)),
                "comment": _perm(s.write_permission(gid, reply_to=m, kind=KIND_CHAT))}

    async def _unknown_manifests(self) -> None:
        with contextlib.suppress(*NETWORK_ERRORS):
            if await self.session.fetch_unknown_manifests():
                self.session.emit(ev.GroupsChanged())

    # --- following (UN-RFC 0034 section 6) --------------------------------------
    def following(self) -> dict:
        """``GET /api/following`` (section 4.14): the people you follow, each with the
        feeds followed because of them, and every feed you follow. Never sent anywhere."""
        s = self._ready()
        people = s.following()
        for p in people:
            p["feeds"] = [self._feed_info(s, g) for g in p["feeds"]]
        return {"people": people, "feeds": [self._feed_info(s, g) for g in s.feeds_followed()]}

    @staticmethod
    def _feed_info(s: Session, gid: str) -> dict:
        data = s.manifest_data(gid)
        return {"id": gid, "label": s.group_label(gid), "title": data.get("title", ""),
                "type": data.get("type"), "personal": gid.split("@", 1)[0] in ("feed", "site")}

    async def set_following(self, data: dict) -> dict:
        """``POST /api/following`` (section 4.14): follow a person
        (``{"person": "<key, name, fingerprint or address>", "on": true}``) or a feed
        (``{"feed": "<group ID>", "on": true}``), or stop; ``{"refresh": true}`` reads
        the profiles of those you follow again. Nobody is told."""
        s = self._ready()
        on = bool(data.get("on", True))
        if data.get("refresh"):
            new = await s.refresh_following()
            result: dict = {"new": new}
        elif data.get("feed"):
            gid = str(data["feed"]).strip()
            try:
                s.follow_feed(gid, on)
            except ValueError as exc:
                raise SessionError(f"not a group ID: {exc}") from None
            new = [gid] if on else []
            result = {"feed": gid, "on": on}
        elif data.get("person"):
            target = str(data["person"])
            if on:
                result = await s.follow_person(target)
                new = result["new"]
            else:
                result = {"unsubscribed": await s.unfollow_person(target)}
                new = []
        else:
            raise SessionError("give person, feed or refresh")
        for gid in new:
            self.spawn(self._fetch(gid))
        s.emit(ev.GroupsChanged())
        return {"ok": True, **result}

    # --- your own feed (UN-RFC 0034 section 5, UN-RFC 0029 section 2.1) ------------
    def my_feed(self, kind: str = "feed") -> dict:
        """``GET /api/feed`` (section 4.14), ``GET /api/site`` (section 4.15): your
        personal feed's or site's Group ID, whether you have started it, and what to
        tell before you do."""
        s = self._ready()
        gid = s.personal_group(kind)
        entry = s.data["groups"].get(gid, {})
        return {"id": gid, "started": bool(entry.get("owner") and entry.get("manifest")),
                "followed": gid in s.data["subscribed"],
                "warning": s.personal_group_warning(kind)}

    async def start_feed(self, data: dict, kind: str = "feed") -> dict:
        """``POST /api/feed`` ``{"comments": "open" | "none", "title": "..."}`` (section
        4.14), ``POST /api/site`` ``{"title": "..."}`` (section 4.15): start your
        personal feed or site - only when the user asked, after the warning."""
        s = self._ready()
        comments = str(data.get("comments", "open"))
        if comments not in ("open", "none"):
            raise SessionError("comments is open or none")
        gid = await s.start_personal_group(kind, comments=comments,
                                           title=str(data.get("title", ""))[:200])
        s.emit(ev.GroupsChanged())
        return {"ok": True, "id": gid}
