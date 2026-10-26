"""Session: notifications - what new has landed in For you, for a client to tell the
reader (unseenet-gui#126, unseenet-tui#4).

The core decides *what* is new, so every client notifies alike: private chats and
private posts sent to you, and replies and mentions in For you - not your own, not
reactions, not what was old on arrival (UN-RFC 0049 section 5.2), and nothing it has
already given. How to tell (a system notification, a terminal's OSC 9 or bell) is the
client's. There is no push: only a running client asks.

The choice - ``on`` (true, false, or None: ask the first time) and ``content`` (show
the sender and an excerpt; off by default, since notifications show on lock screens and
stay in notification histories) - is a setting kept with your state (UN-RFC 0044), so
it is the same in every client on every device. The first time anything asks, what is
unread then is noted as given, so turning notifications on brings no flood of old ones.

Belongs here: the choice, and what to tell. Not here: showing it (the clients).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names: SessionError, ...

MAX_NOTIFIED = 2000               # Message-IDs remembered as given
EXCERPT = 80


class NotifyMixin:
    # --- the choice ---
    def notification_settings(self) -> dict:
        """``{"on": True | False | None, "content": bool}`` - None: ask once."""
        n = self.data.get("notifications") or {}
        on = n.get("on")
        return {"on": on if isinstance(on, bool) else None, "content": bool(n.get("content"))}

    def set_notification_settings(self, on=..., content=...) -> dict:
        """Change the choice; leave out what stays. ``on`` None asks again."""
        n = dict(self.notification_settings())
        if on is not ...:
            if on is not None and not isinstance(on, bool):
                raise SessionError("on is true, false or null")
            n["on"] = on
        if content is not ...:
            n["content"] = bool(content)
        self.data["notifications"] = n
        self.save()
        return n

    # --- what to tell ---
    def _notifiable(self) -> list[tuple[str, "Message"]]:
        """(why, message) for everything that would notify now, unread: private chats
        and posts to you, and For you's replies and mentions."""
        me = {self.identity(n).key_text for n in self.data["identities"]}
        out, seen = [], set()
        for m in self.cache.get(self.my_inbox, {}).values():
            if (m.readable and m.kind != "reaction" and m.author_key not in me
                    and not self.is_read(m) and not m.old_on_arrival
                    and not getattr(m, "notices_for", None)):
                out.append(("mention" if self.is_notice(m) else "private", m))
                seen.add(m.message_id)
        for m in self.for_you(unread_only=True):
            if m.message_id not in seen and not m.old_on_arrival and m.author_key not in me:
                why = "mention" if (m.private or self.for_me(m) == "mention") else "reply"
                out.append((why, m))
                seen.add(m.message_id)
        return out

    def notifications(self, mark: bool = True) -> dict:
        """What is new to tell about, not told before: ``{"settings", "count", "items"}``,
        each item ``{"id", "group", "why", "chat", "who", "text"}`` - ``who`` and ``text``
        only when the reader chose to see content. ``mark`` notes them as told. The
        first call ever only notes what is unread then, and answers nothing."""
        told = self.data.get("notified")
        now = self._notifiable()
        if told is None:                              # the first time: a baseline
            self.data["notified"] = [m.message_id for _, m in now][-MAX_NOTIFIED:]
            self.save()
            return {"settings": self.notification_settings(), "count": 0, "items": []}
        known = set(told)
        new = [(why, m) for why, m in now if m.message_id not in known]
        content = self.notification_settings()["content"]
        items = []
        for why, m in new:
            item = {"id": m.message_id, "group": m.group, "why": why, "chat": m.kind == "chat"}
            if content:
                item["who"] = self.identity_label(m.author_key, m.from_name) if m.author_key \
                    else "anonymous"
                words = (m.subject or "") if m.kind != "chat" else ""
                body = " ".join((m.body or "").split())
                item["text"] = ((words + ": ") if words else "") + body[:EXCERPT]
            items.append(item)
        if mark and new:
            told.extend(m.message_id for _, m in new)
            del told[:-MAX_NOTIFIED]
            self.save()
        return {"settings": self.notification_settings(), "count": len(items), "items": items}
