"""Session: a posting queue (#569) - many posts paced by postage, ripening and quotas.

An importer (UN-RFC 0049 section 6.4), a bot or a gateway may have many articles to
post. The queue posts them in the order given (an importer puts the newest first), one
at a time through ``Session.post`` - so postage, key ripening (UN-RFC 0025) and the
article are the same as any client's - and builds each article only when it posts it,
so its ``Date`` is the time of posting (UN-RFC 0049 section 3.1).

What is left is kept where the caller says: a JSON file (written 0600, replaced whole)
or the caller's own ``load``/``save`` - for unseenet-import that is its local draft, not
the vault, which travels to phones. A post the node refuses for good is kept aside with
the reason; one that hits a day's file quota (UN-RFC 0027 section 8.1) waits for the next
day; a network failure is tried again later. ``run`` carries on until nothing is left,
over days if it must; ``estimate`` says how long the rest will take.

Belongs here: the queue and its pacing. Posting itself is ``posting.py``.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import *  # noqa: F403  - the shared names: SessionError, NNTPError, ...

RETRY_SECONDS = (30, 120, 600, 1800, 3600)   # network failures, then hourly
NETWORK_ERRORS = (OSError, ConnectionError, NNTPError, asyncio.IncompleteReadError, asyncio.TimeoutError)
ITEM_KEYS = ("group", "subject", "body", "kind", "references", "content_type", "origin", "files", "key")


def _quota(text: str) -> bool:
    return "quota" in text or "today's limit" in text


def _try_later(text: str) -> bool:
    """A refusal that passes: a node full or not reached yet, or asking to try later."""
    low = text.lower()
    return any(w in low for w in ("is full", "trying again", "try later", "could not be reached",
                                  "the state could not be fetched", "tor:"))


def _next_day(now: float) -> float:
    d = datetime.fromtimestamp(now, timezone.utc)
    return (d.replace(hour=0, minute=5, second=0, microsecond=0) + timedelta(days=1)).timestamp()


class PostingQueue:
    """Posts to make, kept until they are made. ``add`` items (dicts: ``group``,
    ``subject``, ``body``, and optionally ``kind``, ``references``, ``content_type``,
    ``origin`` (UN-RFC 0049), ``files`` (paths, prepared when posted) and ``key`` - the
    caller's own ID for the item, e.g. to know it was imported); ``run`` posts them.
    ``progress(done, left, failed, waiting_until)`` is called after each step."""

    def __init__(self, session, path: str | Path | None = None, *, load=None, save=None,
                 progress=None):
        self.session = session
        self.path = Path(path) if path is not None else None
        self._load, self._save = load, save
        self.progress = progress
        self.items: list[dict] = []           # what is left, in order
        self.done: list[dict] = []            # {"key", "message_id", "at"}
        self.failed: list[dict] = []          # {"item", "error"}
        self.waiting_until: float = 0.0       # a quota or the network: not before this
        self._seconds: list[float] = []       # how long recent posts took (postage, ripening)
        self._stop = asyncio.Event()
        self._read()

    # --- keeping it ---
    def _state(self) -> dict:
        return {"v": 1, "items": self.items, "done": self.done[-1000:], "failed": self.failed,
                "waiting_until": self.waiting_until, "seconds": self._seconds[-50:]}

    def _read(self) -> None:
        data = None
        if self._load is not None:
            data = self._load()
        elif self.path is not None and self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        if data:
            self.items = list(data.get("items", []))
            self.done = list(data.get("done", []))
            self.failed = list(data.get("failed", []))
            self.waiting_until = float(data.get("waiting_until", 0))
            self._seconds = [float(x) for x in data.get("seconds", [])]

    def _write(self) -> None:
        state = self._state()
        if self._save is not None:
            self._save(state)
            return
        if self.path is None:
            return
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    # --- filling it ---
    def add(self, *items: dict) -> int:
        """Add posts at the end, checked now (not when posted): a group and a body, and a
        subject unless it is a chat line. Returns how many are waiting."""
        for item in items:
            item = {k: item[k] for k in ITEM_KEYS if k in item and item[k] is not None}
            if not item.get("group") or not (item.get("body") or item.get("files")):
                raise SessionError("a queued post needs a group and a body or files")
            if item.get("kind", KIND_POST) == KIND_POST and not str(item.get("subject", "")).strip():
                raise SessionError("a queued post needs a subject (or kind chat)")
            if item.get("origin"):
                from ...core import origins
                o = item["origin"]
                try:
                    origins.origin_headers(o.get("network", ""), o.get("date"), o.get("id", ""), o.get("from", ""))
                except origins.OriginError as exc:
                    raise SessionError(str(exc)) from exc
            self.items.append(item)
        self._write()
        return len(self.items)

    # --- how long ---
    def estimate(self) -> dict:
        """``{"left", "seconds", "until"}``: the posts left, and a rough guess of how long
        they take from the time recent posts took; ``until`` is a wait for a quota or
        the network, if any. Files' daily quotas can make it longer than this."""
        per = sorted(self._seconds)[len(self._seconds) // 2] if self._seconds else 30.0
        wait = max(0.0, self.waiting_until - time.time())
        return {"left": len(self.items), "seconds": round(wait + per * len(self.items)),
                "until": self.waiting_until or None, "failed": len(self.failed)}

    def stop(self) -> None:
        self._stop.set()

    # --- posting ---
    async def post_one(self) -> str | None:
        """Post the first item now. Returns its Message-ID, or None when it waits (a
        quota, the network) or failed for good (kept in ``failed``)."""
        if not self.items:
            return None
        item = self.items[0]
        s = self.session
        started = time.monotonic()
        try:
            files = s.prepare_files(item["files"]) if item.get("files") else None
            msgid = await s.post(item["group"], item.get("subject", ""), item.get("body", ""),
                                 references=item.get("references") or None,
                                 kind=item.get("kind", KIND_POST),
                                 content_type=item.get("content_type"), files=files,
                                 origin=item.get("origin"))
        except SessionError as exc:
            text = str(exc)
            if _quota(text):                                     # tomorrow (UN-RFC 0027 8.1)
                self.waiting_until = _next_day(time.time())
            elif _try_later(text):                               # a full node, Tor starting
                self._retry()
            else:                                                # refused for good
                self.failed.append({"item": self.items.pop(0), "error": text})
            self._write()
            return None
        except NETWORK_ERRORS:
            self._retry()
            self._write()
            return None
        self._tries = 0
        self.items.pop(0)
        self._seconds.append(time.monotonic() - started)
        self.done.append({"key": item.get("key"), "message_id": msgid,
                          "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        self.waiting_until = 0.0
        self._write()
        return msgid

    def _retry(self) -> None:
        tries = getattr(self, "_tries", 0)
        self._tries = tries + 1
        self.waiting_until = time.time() + RETRY_SECONDS[min(tries, len(RETRY_SECONDS) - 1)]

    async def run(self, sleep=asyncio.sleep) -> dict:
        """Post everything, waiting where a quota or the network says so, until nothing is
        left or ``stop`` is called. Returns ``estimate()`` at the end."""
        self._stop.clear()
        while self.items and not self._stop.is_set():
            wait = self.waiting_until - time.time()
            if wait > 0:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=wait) if sleep is asyncio.sleep \
                        else await sleep(wait)
                except asyncio.TimeoutError:
                    pass
                continue
            await self.post_one()
            if self.progress is not None:
                self.progress(len(self.done), len(self.items), len(self.failed),
                              self.waiting_until or None)
        return self.estimate()


class QueueMixin:
    def posting_queue(self, path: str | Path | None = None, *, load=None, save=None,
                      progress=None) -> PostingQueue:
        """A posting queue for many posts (#569), kept in ``path`` (a JSON file) or by the
        caller's ``load``/``save``; see ``PostingQueue``."""
        return PostingQueue(self, path, load=load, save=save, progress=progress)
