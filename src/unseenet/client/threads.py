"""Threads and views: how a client lays out a group, the same in every client.

Moved here from the TUI (unseenet #139), which every other client had to copy.
The pure part (``threaded``) needs no session; ``Session.threads()`` and
``Session.view_of()`` use it with the session's own state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..core.groups import KIND_CHAT

if TYPE_CHECKING:
    from .session import Message

# Pseudo group IDs a client can show next to real groups.
CONTACT = "contact:"     # + a key: the chat with one person (UN-RFC 0028, 6.2)
FOR_YOU = "for-you:"     # replies to you and posts naming you, from all groups (#109)
TIMELINE = "timeline:"   # the feeds you follow, newest first (UN-RFC 0034 section 7)
TAGGED = "tag:"          # + a tag: everything with it in your groups and feeds (UN-RFC 0052)
FEED_DEPTH = 2           # a feed shows comments two levels deep (UN-RFC 0034 section 4)

MAX_DEPTH = 4            # deeper replies are drawn at this depth


_EPOCH = datetime.min.replace(tzinfo=timezone.utc)   # for what has no date

def threaded(msgs: list[Message]) -> list[tuple[Message, int]]:
    """Threads newest first, each thread in the order its posts came.

    ``msgs`` is in the order the messages came. A reply goes under the first
    post it references that is in ``msgs``; a reply to a post we don't have
    starts a thread of its own. Consecutive chat lines in a post group stay
    together as one run rather than a thread each (UN-RFC 0028). Each row is
    ``(message, depth)``, depth 0 for a thread's first post.
    """
    pos = {m.message_id: i for i, m in enumerate(msgs)}
    by_id = {m.message_id: m for m in msgs}
    threads: dict[str, list[Message]] = {}
    run = None
    for m in msgs:
        root = next((r for r in m.references if r in by_id), None)
        if root is None and m.kind == KIND_CHAT and not m.private:
            root = run = run or m.message_id
        else:
            run = None
        root = root or m.message_id
        threads.setdefault(root, []).append(m)
    out = []
    for root, items in sorted(threads.items(),
                              key=lambda kv: max(pos[x.message_id] for x in kv[1]), reverse=True):
        if any(x.origin_date for x in items):    # imports: by origin date (UN-RFC 0049 5.3)
            ordered = sorted(items, key=lambda x: (x.sort_date or _EPOCH, pos[x.message_id]))
        else:
            ordered = sorted(items, key=lambda x: pos[x.message_id])
        for m in ordered:
            depth = 0 if m.message_id == root else min(len(m.references), MAX_DEPTH)
            out.append((m, depth))
    return out


def feed_threaded(msgs: list[Message]) -> list[tuple[Message, int]]:
    """A group shown as a feed (UN-RFC 0034 section 4): every post or chat line that
    answers nothing here is an entry - consecutive chat lines too, each a note of its
    own - entries newest first by ``Date``, each followed by its comments in the
    order they came. ``(message, depth)``, depth 0 for an entry and the comment's
    depth under it (at most ``MAX_DEPTH``); a front end shows two levels."""
    from datetime import datetime, timezone
    pos = {m.message_id: i for i, m in enumerate(msgs)}
    by_id = {m.message_id: m for m in msgs}
    entries: dict[str, list[Message]] = {}
    for m in msgs:
        root = next((r for r in m.references if r in by_id), None)
        if root is not None:                    # under the entry its first reference is in
            while True:
                up = next((r for r in by_id[root].references if r in by_id), None)
                if up is None:
                    break
                root = up
        entries.setdefault(root or m.message_id, [])
        if root is not None:
            entries[root].append(m)
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    out = []
    # by the origin date of an import, else Date (UN-RFC 0049 section 5.3)
    for root in sorted(entries, key=lambda r: (by_id[r].sort_date or epoch, pos[r]), reverse=True):
        out.append((by_id[root], 0))
        for m in entries[root]:
            refs = m.references
            depth = len(refs) - refs.index(root) if root in refs else 1
            out.append((m, max(1, min(depth, MAX_DEPTH))))
    return out
