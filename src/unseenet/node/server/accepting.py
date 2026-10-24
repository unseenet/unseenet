"""Taking an article: the pipeline every article goes through, from a client or a peer.

Belongs here: ``accept`` and ``_accept`` - the order of the checks (structure,
duplicates, which groups a peer may send, the group and its window, postage, then
manifests, control articles or ordinary posts) and storing and forwarding what passed;
holding comments that came before their thread (UN-RFC 0030 section 4.1) and waiting
for a key-bound group's manifest (UN-RFC 0040 section 6).

Not here: the rules of each kind - postage (postage.py), manifests (manifests.py),
control articles (controls.py), kept articles (kept.py), edits (edits.py), blobs
(blobs.py), blocks (blocks.py).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Accepting:
    # ------------------------------------------------------------------
    # Acceptance pipeline
    # ------------------------------------------------------------------
    def accept(self, raw: bytes, source: str | None = None,
               now: datetime | None = None, from_peer: bool = False,
               how: str | None = None, staged: dict | None = None) -> Article:
        """Validate and store an article. Raises ArticleError with an RFC 0005 reason.

        ``from_peer`` is true for articles pushed by another node (IHAVE/TAKETHIS),
        authenticated or not; ``source`` names the peer when it authenticated.
        ``how`` is only for the counters: "client", "peer" or "pull".
        """
        try:
            art = self._accept(raw, source, now, from_peer, staged)
        except ArticleError as err:
            self.stats.rejected_one(err.reason)
            if err.reason == "later":
                self._hold(raw, source, from_peer)
            raise
        self.stats.accepted_one(how or ("peer" if from_peer else "client"))
        self._release_held(art.message_id)
        if art.control == ["manifest"]:
            self._kb_waiting.pop(art.group, None)
        return art

    # --- comments before their thread (UN-RFC 0030 section 4.1) ---
    HOLD_SECONDS = 3600.0

    HOLD_MAX = 1000

    def _hold(self, raw: bytes, source: str | None, from_peer: bool) -> None:
        """Keep a comment aside until its thread arrives, at most an hour. The
        sender is told to try again anyway, so dropping one here loses nothing."""
        try:
            root = Article.from_bytes(raw).get("References", "").split()[0]
        except (ArticleError, ValueError, IndexError):
            return
        now = time.monotonic()
        for key in [k for k, v in self._held.items()
                    if all(now - t > self.HOLD_SECONDS for t, *_ in v)]:
            del self._held[key]
        if sum(len(v) for v in self._held.values()) >= self.HOLD_MAX:
            return
        waiting = self._held.setdefault(root, [])
        if all(r != raw for _, r, _, _ in waiting):
            waiting.append((now, raw, source, from_peer))

    def _release_held(self, message_id: str) -> None:
        now = time.monotonic()
        for held_at, raw, source, from_peer in self._held.pop(message_id, []):
            if now - held_at <= self.HOLD_SECONDS:
                try:
                    self.accept(raw, source=source, from_peer=from_peer)
                except ArticleError as err:
                    log.debug("held comment not accepted: %s", err)

    # --- key-bound groups whose manifest has not arrived (UN-RFC 0040 section 6) ---
    KB_WAIT_SECONDS = 6 * 3600.0
    GROUP_WAIT_SECONDS = 15 * 60.0   # an ordinary group's manifest, sent first, comes soon (#384)

    KB_WAIT_MAX = 10000

    def _wait_for_manifest(self, group_id: str, source: str | None,
                           wait: float | None = None) -> None:
        """A peer offers an article in a key-bound group we hold no manifest for.
        Rather than refuse it, ask the peer to try again later (431/436), and have
        the next pull from it reconcile, which fetches the manifest. After
        KB_WAIT_SECONDS without it the article is refused as before: the group
        may simply not exist. An ordinary group waits ``wait`` (GROUP_WAIT_SECONDS):
        its manifest is sent ahead of its posts, so it is only a little behind."""
        wait = self.KB_WAIT_SECONDS if wait is None else wait
        now = time.monotonic()
        if len(self._kb_waiting) >= self.KB_WAIT_MAX:
            for gid in [g for g, t in self._kb_waiting.items() if now - t > self.KB_WAIT_SECONDS]:
                del self._kb_waiting[gid]
        since = self._kb_waiting.get(group_id)
        if since is None:
            if len(self._kb_waiting) >= self.KB_WAIT_MAX:
                return
            since = self._kb_waiting[group_id] = now
        if now - since > wait:
            return
        if source:
            self.reconcile_wanted.add(source)
        raise ArticleError("later", "the group's manifest is not on this node yet")

    def _thread_root(self, message_id: str) -> Article | None:
        """An article this node holds, for comments in channels (UN-RFC 0030, 4).
        A root replaced by an edit is found through the edit, dated as its earliest
        version, so that editing does not reopen comments (UN-RFC 0042, 3.2)."""
        raw = self.store.get(message_id)
        if raw is None:
            edit = self.store.supersede_for(message_id)
            raw = self.store.get(edit[0]) if edit else None
        if raw is not None:
            root = Article.from_bytes(raw)
            first = self.store.first_date(message_id)
            if first is not None and first < int(parse_date(root["Date"]).timestamp()):
                root.set("Date", format_datetime(datetime.fromtimestamp(first, timezone.utc)))
            return root
        if self.store.seen(message_id):      # was here, but expired or was cancelled
            raise ArticleError("permission", "that thread is no longer on this node")
        return None

    def _accept(self, raw: bytes, source: str | None, now: datetime | None,
                from_peer: bool, staged: dict | None = None) -> Article:
        art = Article.from_bytes(raw)
        validate_structure(art, raw_size=len(raw), max_size=self.config.max_size, now=now)
        if self.store.seen(art.message_id):
            raise ArticleError("duplicate")
        if from_peer and source is not None:
            peer = self.peer_config(source)
            if peer is not None and not wildmat(peer.accept, art.group):
                raise ArticleError("group", f"not accepted from peer {source}")
        now = now or datetime.now(timezone.utc)
        ctl = art.control
        is_manifest = ctl == ["manifest"]
        if is_manifest and is_key_bound(art.group):
            limit = KEY_BOUND_MANIFEST_MAX.get(art.group.split("@")[0])
            if limit is not None and len(raw) > limit:     # UN-RFC 0040 section 9
                raise ArticleError("size", f"key-bound manifest larger than {limit} octets")
        if self.config.excludes and wildmat(self.config.excludes, art.group):
            raise ArticleError("group", "excluded by this node")
        removed = self.store.tombstone(art.group)
        if removed:
            raise ArticleError("group", "group was removed by its owner" if removed == "owner"
                               else "group was dropped by this node")

        self._check_profile_group(art.group)
        manifest = self.store.manifest(art.group)
        if ctl == ["rmgroup"]:
            return self._accept_rmgroup(art, manifest, raw, source, from_peer)
        if not is_manifest:
            if manifest is None:
                if from_peer and is_key_bound(art.group) and not self.store.known_group(art.group):
                    self._wait_for_manifest(art.group, source)
                elif from_peer and not is_key_bound(art.group):
                    self._wait_for_manifest(art.group, source, self.GROUP_WAIT_SECONDS)   # #384
                raise ArticleError("group", "group not carried")
            if manifest.local and from_peer:
                raise ArticleError("group", "local group: never accepted from peers")
            if manifest.type == "state":                     # UN-RFC 0044 section 3
                raise ArticleError("permission", "a state group has no articles, only its manifest")
            retention = min(self.config.retention_days, manifest.retention_days)
            if (parse_date(art["Date"]) < now - timedelta(days=retention)
                    and not self._keep_old(art, manifest)):
                raise ArticleError("date", "older than retention")

        # UN-RFC 0027 section 5.2: what every node checks, carrying blobs or not
        blobs = bl.check_article(art, None if is_manifest or manifest is None else manifest.raw)
        group_pow = manifest.min_pow if manifest is not None and not is_manifest else 0
        required = (self._required_pow(art, manifest, group_pow, source, from_peer)
                    + bl.extra_bits(art))                       # section 4.5
        if art.proven_pow() < required:
            raise ArticleError("postage", f"need {required} bits")

        if is_manifest:
            self._accept_manifest(art, manifest, raw, from_peer)
        elif ctl:
            self._accept_control(art, manifest, raw)
        else:
            page = self._check_page(art, manifest, blobs) if art.get("Page") is not None else None
            versions = [] if page else parse_supersedes(art)   # an edit (UN-RFC 0042)
            held = self._check_edit(art, manifest, versions) if versions else {}
            self._check_cancelled(art, manifest)
            self._check_superseded(art)
            check_permitted(art, manifest, self.store.epochs(art.group),
                            self.store.closed_before(art.group), thread_root=self._thread_root)
            self._check_blocked(art)
            carried = self._blobs_for(art, blobs, from_peer, staged)
            self.store.add(art, raw)
            if page:
                self.store.add_page(art, *page)
            for bid in carried:                         # staged on this connection: now kept
                self.store_blob(bid, staged.pop(bid)[0])
            if carried:                                 # UN-RFC 0027 8.1: the day's quota
                self.store.charge_blobs(art["Author-Key"], art.group,
                                        sum(n for b, n in blobs if b in carried))
            self._refusal_list(art)
            if versions:
                self._apply_edit(art, versions, held)
            if self._wait_for_blobs(art, blobs, source, from_peer):
                self._enqueue(art, source, not_before=time.time() + BLOB_WAIT_SECONDS)
                self._notify_watchers(art)
                log.info("accepted %s in %s; fetching its blobs", art.message_id, art.group)
                return art
        self._enqueue(art, source)
        self._notify_watchers(art)
        log.info("accepted %s in %s", art.message_id, art.group)
        return art
