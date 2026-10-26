"""Blobs (UN-RFC 0027): the files articles carry, when the operator carries them.

Belongs here: a client's article needing its blobs stored or staged, the daily quotas,
storing and sweeping blobs (what nothing references, refused ones, retention), refusal
lists from configured keys, and holding an article from a peer until its blobs are
fetched (``blob_wait``; the fetching is ``node/blobfetch.py``).

Not here: BLOBPOST and BLOB (blob_commands.py), the rules every node checks
(``core/blobs.py``).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Blobs:
    # --- blobs (UN-RFC 0027) ---
    def _blobs_for(self, art: Article, blobs, from_peer: bool, staged: dict | None) -> list[str]:
        """Section 6.2: a blob node takes a client's article only with every blob
        stored or staged on that connection. Returns the staged ones to keep. From
        peers, blobs follow their article later (section 6.3)."""
        if not blobs or from_peer or not self.config.carries_blobs(art.group, bl.encrypted(art)):
            return []
        staged = staged or {}
        wanted = [(b, n) for b, n in blobs if not self.store.blob_refused(b)]   # 7.3: not ours
        missing = [b for b, _ in wanted if not self.blobs.has(b) and b not in staged]
        if missing:
            raise ArticleError("blobs", f"{len(missing)} blob(s) neither stored nor staged")
        new = [(b, n) for b, n in wanted if b in staged and not self.blobs.has(b)]
        if new and not self._within_quota(art, sum(n for _, n in new)):
            raise ArticleError("quota", "too many blob octets today for this key or group")
        return [b for b, _ in new]

    def _within_quota(self, art: Article, octets: int) -> bool:
        """Section 8.1: a day's blob octets per author key and per group."""
        b = self.config.blobs or {}
        per_key = b.get("daily_per_key", bl.DAILY_PER_KEY)
        per_group = b.get("daily_per_group", bl.DAILY_PER_GROUP)
        return (self.store.blob_usage("key", art["Author-Key"]) + octets <= per_key
                and self.store.blob_usage("group", art.group) + octets <= per_group)

    def store_blob(self, bid: str, octets: bytes) -> None:
        """Keep a blob's octets on disk and note it in the store (UN-RFC 0027 section 7)."""
        self.blobs.put(bid, octets)
        self.store.note_blob(bid, len(octets))

    def sweep_blobs(self, retention: bool = True) -> int:
        """Delete the blobs no stored article references, refused ones, and those
        past the node's blob retention unless a kept article references them
        (UN-RFC 0027 sections 7.1-7.3, UN-RFC 0017 section 2.1)."""
        days = (self.config.blobs or {}).get("retention_days") if retention else None
        gone = self.store.blobs_to_delete(days)
        for bid in gone:
            self.blobs.delete(bid)
            self.store.forget_blob(bid)
        return len(gone)

    def _refusal_list(self, art: Article) -> None:
        """Section 7.3: a refusal list, followed only from keys the operator configured."""
        b = self.config.blobs or {}
        keys = b.get("refusal_keys") or []
        if (not keys or art["Author-Key"] not in keys or "Encrypted" in art
                or not wildmat(b.get("refusal_groups", "*"), art.group)
                or not (art.get("Content-Type") or "").startswith("application/x-unseenet-blob-refusals")):
            return
        try:
            data = parse_canonical_json(art.body)
            listed = [x for x in data.get("blobs", []) if isinstance(x, str) and bl.valid_id(x)]
            reason = str(data.get("reason", ""))[:200]
        except (ValueError, AttributeError):
            return
        for bid in listed:
            self.store.refuse_blob(bid, reason, art["Author-Key"])
        if listed:
            self.sweep_blobs(retention=False)

    def _wait_for_blobs(self, art: Article, blobs, source: str | None, from_peer: bool) -> bool:
        """Section 6.3: an article from a peer whose blobs we carry but lack is not
        passed on until we have fetched them, or at most BLOB_WAIT_SECONDS."""
        if not blobs or not from_peer or not self.config.carries_blobs(art.group, bl.encrypted(art)):
            return False
        missing = {b: n for b, n in blobs if n <= self.config.max_blob and not self.blobs.has(b)
                   and not self.store.blob_refused(b)}
        if not missing or not self._within_quota(art, sum(missing.values())):
            return False                 # over the quota: the article goes on, its files not (8.1)
        self.store.charge_blobs(art["Author-Key"], art.group, sum(missing.values()))
        self.blob_wait[art.message_id] = {"group": art.group, "source": source, "missing": missing,
                                          "until": time.time() + BLOB_WAIT_SECONDS}
        return True

    def backfill_blobs(self, limit: int = BACKFILL_MAX) -> int:
        """Fetch the files of stored articles the node now carries but lacks (#543):
        after blobs were turned on, or ``encrypted`` or ``groups`` widened. They join
        the articles waiting for blobs (section 6.3), with no peer of origin, so the
        follower asks every peer carrying the group; they are already stored and
        forwarded, so nothing is held back. Not charged to the daily quotas (8.1):
        they were posted before. Returns how many articles were added, at most
        ``limit``; the rest come with the next start or as peers send them again."""
        if self.config.blobs is None:
            return 0
        added = 0
        for mid, gid, refs in self.store.articles_missing_blobs():
            if added >= limit:
                break
            if mid in self.blob_wait:
                continue
            raw = self.store.get(mid)
            if raw is None:
                continue
            try:
                art = Article.from_bytes(raw)
            except ArticleError:
                continue
            if not self.config.carries_blobs(gid, bl.encrypted(art)):
                continue
            missing = {b: n for b, n in refs if n <= self.config.max_blob}
            if not missing:
                continue
            self.blob_wait[mid] = {"group": gid, "source": None, "missing": missing,
                                   "until": time.time() + BLOB_WAIT_SECONDS}
            added += 1
        return added

    def fetching(self, bid: str) -> bool:
        """True while the node is fetching this blob for an article it holds back
        (UN-RFC 0027 section 6.3): BLOB then answers ``436`` (try later)."""
        return any(bid in w["missing"] for w in self.blob_wait.values())

    def blobs_done(self, message_id: str) -> None:
        """The blobs came, or we gave up: pass the article on with the usual delay."""
        w = self.blob_wait.pop(message_id, None)
        if w is None:
            return
        manifest = self.store.manifest(w["group"])
        lo, hi = (0.0, 0.0) if manifest is not None and manifest.low_latency else self.config.forward_delay
        self.store.reschedule(message_id, lambda _peer: time.time() + random.uniform(lo, hi))
        for event in self._listeners:
            event.set()
