"""Events (UN-RFC 0046 section 5): what the front end is told without asking.

Belongs here: the WebSocket listeners, turning ``Session`` events into section 5's
JSON events, jobs' progress (``job``), status lines (``say``), and ``spawn`` for work
that runs on while a request has returned.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class Events:
    # --- events (section 5) --------------------------------------------------
    def listen(self) -> asyncio.Queue:
        """A queue of the events of section 5 for one WebSocket client; the server reads
        it and sends each event. Give it back with ``unlisten``."""
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._listeners.add(q)
        return q

    def unlisten(self, q: asyncio.Queue) -> None:
        """Stop sending events to a WebSocket client's queue (see ``listen``)."""
        self._listeners.discard(q)

    def _broadcast(self, data: dict) -> None:
        for q in list(self._listeners):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(data)

    def _on_event(self, e: ev.Event) -> None:
        if isinstance(e, ev.Status):
            self.status = e.text
        elif isinstance(e, ev.Refreshed):
            self.connected = e.error is None
        self._broadcast(e.to_dict())
        if isinstance(e, ev.Refreshed) and self.session is not None:
            # the status line every front end shows after a round (as the TUI's)
            self._say(f"Offline ({e.error}) - showing saved posts" if e.error
                      else f"Connected to {self.session.node}")
        if self._job is not None:            # progress of the job being sent
            job, group = self._job
            if isinstance(e, ev.PowProgress) and not e.done:
                self._job_event(job, group, "pow", fraction=round(e.fraction, 3))
            elif isinstance(e, ev.Ripening) and e.next_at:
                self._job_event(job, group, "ripening",
                                fraction=round(min(1.0, e.t / e.next_at), 3))

    def emit(self, event: str, **data) -> None:
        """Send an event of a front end's own (UN-RFC 0046 section 6), such as an
        extension's progress, to everyone listening on ``/api/events``. Name it
        ``x-<extension>-...``."""
        self._broadcast({"event": event, **data})

    def _job_event(self, job: str, group: str, state: str, **more) -> None:
        self._broadcast({"event": "job", "job": job, "group": group, "state": state, **more})

    def _say(self, text: str) -> None:
        self.status = text
        self._broadcast(ev.Status(text).to_dict())

    def spawn(self, coro) -> asyncio.Task:
        """Run a coroutine in the background, kept until done and cancelled by ``close``."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
