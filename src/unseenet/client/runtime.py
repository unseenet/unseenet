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
import os
from dataclasses import dataclass

from ..core.backoff import Backoff
from ..nntp import NNTPError
from . import events as ev
from .session import GroupInfo, Session, SessionError

log = logging.getLogger(__name__)

REFRESH_SECONDS = 60          # a fallback: push brings new posts at once
RIPEN_TO = 4                  # ripen keys up to this level while running (UN-RFC 0025, 7)
SERVICE_RIPEN_TO = 3          # services: no surcharge from level 3, and a core is spared
RIPEN_RECHECK = 3600.0        # a node that says "-" is asked again this often (#314)
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
                 watch_retry: float | None = None, ripen_to: int | None = RIPEN_TO):
        self.session = session
        self.ripen_to = ripen_to                      # None: don't ripen in the background
        self._run_file = None                         # removing it stops a segment at once
        self._ripen_stop: asyncio.Event | None = None  # set: stop waiting for a node (#314)
        self.refresh_seconds = refresh_seconds
        self.watch_retry = watch_retry                # None: a random, growing wait (#297)
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
        A second call while one runs waits for it, then runs again.

        The inbox is set up while the groups are fetched: for a brand-new key
        it is a post that waits for the key to ripen, minutes, and the groups'
        posts should not wait for that (#328)."""
        async with self._lock:
            s = self.session
            try:
                available = {g.group_id: g for g in await s.list_groups()}
            except NETWORK_ERRORS as exc:
                return self._emit_refreshed(error=str(exc) or type(exc).__name__)
            self.available = available
            inbox = None if self.inbox_ready else asyncio.ensure_future(self._set_up_inbox())
            fetched = await self._fetch(s.data["subscribed"])
            if inbox is not None and (listed := await inbox) is not None:
                self.available = available = listed
                await self._fetch(g for g in s.data["subscribed"] if g not in fetched)  # the inbox
            return self._emit_refreshed(available=len(available))

    async def _fetch(self, group_ids) -> set[str]:
        done = set()
        for gid in list(group_ids):
            try:
                await self.session.fetch_group(gid)
            except NETWORK_ERRORS:
                pass                              # shown as not reachable; saved posts stay
            done.add(gid)
        return done

    async def _set_up_inbox(self) -> dict[str, GroupInfo] | None:
        """Set up the inbox once; the groups listed again (with it), or None."""
        s = self.session
        try:
            await s.ensure_inbox()
            self.inbox_ready = True
            s.emit(ev.InboxReady(s.my_inbox))
            return {g.group_id: g for g in await s.list_groups()}
        except NETWORK_ERRORS as exc:
            s.say(f"Could not set up your inbox: {exc}")
            return None

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
        Reconnects after a random wait, 1-30 s at first and growing to at most five
        minutes while the node stays away, so that clients do not all come back
        at once after a restart (UN-RFC 0043 section 4.4; ``watch_retry`` makes it
        fixed, for tests). Returns when the node cannot
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

        backoff = Backoff()
        while node in s.nodes and (keep_going is None or keep_going()):
            backoff.up()                     # a watch that stays up a minute starts over
            try:
                if await s.watch(pushed, node=node) is False:
                    return
            except NETWORK_ERRORS:
                pass
            backoff.down()
            wait = self.watch_retry if self.watch_retry is not None else backoff.next()
            await asyncio.sleep(max(wait, s.retry_in(node)))

    async def read_profiles(self) -> int:
        """Read the profiles of the authors in your groups, all at once, so a client can
        mark bots (UN-RFC 0030 section 6) without the node learning whose profile is
        looked at (UN-RFC 0022 section 13, UN-RFC 0041 section 3.2). Cached for a day;
        groups are redrawn when something was read. Quiet on failure."""
        s = self.session
        try:
            n = await s.prefetch_profiles(s.authors())
        except NETWORK_ERRORS:
            return 0
        if n:
            for gid in list(s.data["subscribed"]):
                s.emit(ev.GroupUpdated(gid))
        return n

    async def _fetch_quietly(self, gid: str) -> None:
        try:
            await self.session.fetch_group(gid)
        except NETWORK_ERRORS:
            pass

    async def ripen(self) -> None:
        """Ripen the identity's key on, segment by segment, up to ``ripen_to``,
        publishing ripe@ at each new level (UN-RFC 0025 sections 3.2, 7). A restart
        loses at most the segment being computed. ``stop()`` ends it at once."""
        from ..core import ripening as rp
        s = self.session
        if self.ripen_to is None or not rp.available() or not s.has_identity():
            return
        self._ripen_stop = asyncio.Event()
        if not await self._wait_for_a_node_that_asks():
            return                              # stopped while waiting
        await s.adopt_published_ripening()      # further elsewhere: go on from there
        import tempfile
        from pathlib import Path
        fd, path = tempfile.mkstemp(prefix="unseenet-ripening-")
        os.close(fd)
        self._run_file = Path(path)
        try:
            while True:
                lv = s.ripening().level
                if lv is not None and lv >= self.ripen_to:
                    break
                if not await s.ripen_segment(run_file=self._run_file):
                    break                                  # stopped, or at the top
                if s.ripening().level != s.published_level():
                    try:
                        await s.publish_ripening()         # a new level: tell the nodes
                    except NETWORK_ERRORS as exc:
                        log.info("ripe@ not published now (%s); again at the next level", exc)
        finally:
            self._stop_ripening()

    async def _wait_for_a_node_that_asks(self) -> bool:
        """Wait until our node asks for ripening (UNSEENET-MINRIPE other than "-").

        A node that cannot be reached now (Tor not up yet, the node restarting) is
        asked again after a growing random wait (#297); one that says "-" is asked
        again every RIPEN_RECHECK seconds, since its operator may turn ripening on
        or we may move to another node. Giving up at the first answer left a
        client that started offline without background ripening until it was
        restarted, so its first post waited minutes for it (#314). False when
        ``stop_ripening()`` ended the wait."""
        backoff = Backoff()
        while True:
            value = await self.session.node_min_ripe()
            if value is not None and value != "-":
                return True
            wait = backoff.next() if value is None else RIPEN_RECHECK
            try:
                await asyncio.wait_for(self._ripen_stop.wait(), wait)
                return False                               # stop_ripening()
            except asyncio.TimeoutError:
                pass

    def stop_ripening(self) -> None:
        """Stop the segment being computed within a second (its run file goes)."""
        if self._ripen_stop is not None:
            self._ripen_stop.set()
        self._stop_ripening()

    def _stop_ripening(self) -> None:
        if self._run_file is not None:
            self._run_file.unlink(missing_ok=True)
            self._run_file = None

    # --- or let it run on its own ---
    async def start(self) -> int:
        """Run every step by itself until ``stop()``. Returns the saved posts loaded."""
        loaded = self.open()
        self._spawn(self._run())
        return loaded

    async def stop(self) -> None:
        self.stop_ripening()                           # before cancelling: frees its thread
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._watching.clear()

    async def _run(self) -> None:
        while True:
            await self.refresh()
            self._spawn(self.read_profiles())
            if self.inbox_ready:
                for node in self.session.nodes:          # nodes added later get one too
                    if node not in self._watching:
                        self._watching[node] = self._spawn(self.watch_node(node))
                if not self._background_started:
                    self._background_started = True
                    self._spawn(self.maintain())
                    self._spawn(self.ripen())
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
