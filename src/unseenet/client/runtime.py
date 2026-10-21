"""The client runtime: startup, refresh and push, the same for every client.

Moved here from the TUI (unseenet #139). The order matters and is easy to
get subtly wrong, so every client (TUI, unseenet-gui, unseenet-mcp, bots)
uses this one:

1. follow the project's starter groups (once per vault);
2. show what is saved offline;
3. list the groups on your nodes, and make sure your inbox exists (once);
4. then open one push connection per node (UN-RFC 0008), and read the
   known-node list, releases, renewals and names in the background;
5. fetch every group you follow, and again every ``refresh_seconds`` as a
   fallback for push.

Run it on its own with ``start()`` and ``stop()``, or call ``open()``,
``refresh()``, ``maintain()`` and ``watch_node()`` from your own scheduler,
as the TUI does with its workers. What it learns is reported as events on
the session (``Session.on``, ``client.events``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ..nntp import NNTPError
from . import events as ev
from .session import GroupInfo, Session, SessionError

log = logging.getLogger(__name__)

REFRESH_SECONDS = 60          # a fallback: push brings new posts at once
WATCH_RETRY_SECONDS = 15      # reconnect a push connection after this pause
NETWORK_ERRORS = (SessionError, OSError, ConnectionError, NNTPError, ValueError,
                  asyncio.IncompleteReadError, asyncio.TimeoutError)


@dataclass
class Maintained:
    """What ``maintain()`` found, for clients that act on it themselves."""
    known_nodes: bool = False          # the node list changed
    release: str | None = None         # a newer release, not offered before
    renewed: tuple[str, ...] = ()      # key-bound groups renewed
    names: bool = False                # hierarchy lists or names changed


class ClientRuntime:
    """Keeps a session's groups up to date. See the module docstring for the order."""

    def __init__(self, session: Session, *, refresh_seconds: float = REFRESH_SECONDS,
                 watch_retry: float = WATCH_RETRY_SECONDS):
        self.session = session
        self.refresh_seconds = refresh_seconds
        self.watch_retry = watch_retry
        self.inbox_ready = False
        self.available: dict[str, GroupInfo] = {}     # what your nodes listed last time
        self._lock = asyncio.Lock()                   # one refresh at a time
        self._offered: str | None = None
        self._tasks: set[asyncio.Task] = set()
        self._watching: dict[str, asyncio.Task] = {}
        self._background_started = False

    # --- the steps, for clients with their own scheduler ---
    def open(self) -> int:
        """Steps 1 and 2: follow the starter groups, load the offline cache.
        Returns the number of saved posts that can be read now."""
        s = self.session
        s.subscribe_starter_groups()
        loaded = s.load_offline()
        s.emit(ev.GroupsChanged())
        return loaded

    async def refresh(self) -> ev.Refreshed:
        """Steps 3 and 5: list groups, set up the inbox once, fetch every group
        you follow. Sends ``InboxReady`` the first time, a ``GroupUpdated`` per
        group with new posts, and ``Refreshed`` at the end, which it also returns.
        A second call while one runs waits for it, then runs again."""
        async with self._lock:
            s = self.session
            try:
                available = {g.group_id: g for g in await s.list_groups()}
            except NETWORK_ERRORS as exc:
                return self._emit_refreshed(error=str(exc) or type(exc).__name__)
            if not self.inbox_ready:
                try:
                    await s.ensure_inbox()
                    self.inbox_ready = True
                    s.emit(ev.InboxReady(s.my_inbox))
                    available = {g.group_id: g for g in await s.list_groups()}
                except NETWORK_ERRORS as exc:
                    s.say(f"Could not set up your inbox: {exc}")
            self.available = available
            for gid in list(s.data["subscribed"]):
                try:
                    await s.fetch_group(gid)
                except NETWORK_ERRORS:
                    pass                          # shown as not reachable; saved posts stay
            return self._emit_refreshed(available=len(available))

    def _emit_refreshed(self, available: int = 0, error: str | None = None) -> ev.Refreshed:
        s = self.session
        c = s.for_you_counts()
        result = ev.Refreshed(available=available, subscribed=len(s.data["subscribed"]),
                              unreachable=tuple(s.unreachable), replies=c.replies,
                              mentions=c.mentions, error=error)
        s.emit(result)
        return result

    async def maintain(self) -> Maintained:
        """Step 4, the background part: the known-node list, a newer release
        (``ReleaseOffer``, once per version), renewing key-bound groups that are
        due, and names (``GroupsChanged`` when they changed). Quiet on failure:
        each part is tried again next time."""
        s, out = self.session, Maintained()
        try:
            out.known_nodes = bool(await s.refresh_known_nodes())
        except NETWORK_ERRORS:
            pass
        try:
            offer = await s.refresh_releases()
            if offer and offer["version"] != self._offered:
                self._offered = out.release = offer["version"]
                s.emit(ev.ReleaseOffer(offer["version"]))
        except NETWORK_ERRORS:
            pass
        try:
            out.renewed = tuple(await s.renew_key_bound() or ())
        except NETWORK_ERRORS:
            pass
        try:
            if await s.refresh_naming():
                out.names = True
                s.emit(ev.GroupsChanged())
        except NETWORK_ERRORS:
            pass
        return out

    async def watch_node(self, node: str, on_new=None, keep_going=None) -> None:
        """Step 4, push: keep a connection to ``node`` open so new posts come at once.

        For a new post in a group you follow (or your inbox) that is read from
        this node, ``on_new(group_id, message_id)`` is awaited if given;
        otherwise the group is fetched, which sends ``GroupUpdated``.
        Reconnects after ``watch_retry`` seconds; returns when the node cannot
        push (polling only, then), when it is no longer one of your nodes, or
        when ``keep_going()`` says so.
        """
        s = self.session

        async def pushed(gid: str, message_id: str) -> None:
            if s.node_for(gid) != node:              # read from another of your nodes
                return
            if gid not in s.data["subscribed"] and gid != s.my_inbox:
                return
            if on_new is not None:
                await on_new(gid, message_id)
            else:
                self._spawn(self._fetch_quietly(gid))

        while node in s.nodes and (keep_going is None or keep_going()):
            try:
                if await s.watch(pushed, node=node) is False:
                    return
            except NETWORK_ERRORS:
                pass
            await asyncio.sleep(self.watch_retry)

    async def _fetch_quietly(self, gid: str) -> None:
        try:
            await self.session.fetch_group(gid)
        except NETWORK_ERRORS:
            pass

    # --- or let it run on its own ---
    async def start(self) -> int:
        """Run every step by itself until ``stop()``. Returns the saved posts loaded."""
        loaded = self.open()
        self._spawn(self._run())
        return loaded

    async def stop(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._watching.clear()

    async def _run(self) -> None:
        while True:
            await self.refresh()
            if self.inbox_ready:
                for node in self.session.nodes:          # nodes added later get one too
                    if node not in self._watching:
                        self._watching[node] = self._spawn(self.watch_node(node))
                if not self._background_started:
                    self._background_started = True
                    self._spawn(self.maintain())
            await asyncio.sleep(self.refresh_seconds)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        for node, t in list(self._watching.items()):
            if t is task:
                del self._watching[node]
        if not task.cancelled() and task.exception() is not None:
            log.error("client runtime task failed", exc_info=task.exception())
