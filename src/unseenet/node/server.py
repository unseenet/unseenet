"""ONNTP server and article acceptance (UN-RFC 0002 section 5, 0004, 0005)."""

from __future__ import annotations

import asyncio
from email.utils import format_datetime
import fnmatch
import hmac
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .. import __version__
from ..core.groups import canonical_json, parse_canonical_json
from ..core import crypto, profiles, reconcile
from ..core.groups import split_group_id
from ..core.article import MAX_SIZE, Article, ArticleError, parse_date, validate_structure
from ..core.groups import message_kind, parse_supersedes
from ..core.groups import (INBOX_SCHEME, KEY_BOUND_MANIFEST_MAX, Manifest, check_permitted,
                           is_key_bound, make_group_id, parse_key_update, split_group_id)
from ..core import ripening as rp
from ..core.store import Store
from ..nntp import (MANIFESTS_ANSWER_BYTES, MANIFESTS_MAX, MAX_LINE, RECONCILE_MAX_BYTES,
                    dot_stuff, read_block)
from .stats import Stats

log = logging.getLogger("unseenet.node")


@dataclass
class PeerConfig:
    name: str
    address: str                # "xyz.onion" or "host:port" (testing)
    groups: str = "*"           # RFC 3977 wildmat over Group IDs
    key: str | None = None      # the peer's node key, "ed25519:..." (UN-RFC 0016)
    pull: str = "*"             # wildmat of groups to catch up on from this peer (UN-RFC 0017)
    accept: str = "*"           # wildmat of groups to take from this peer, pushed or pulled
    password: str | None = None  # legacy shared secret for AUTHINFO

    def public_key(self) -> bytes | None:
        return crypto.key_from_text(self.key) if self.key else None


@dataclass
class NodeConfig:
    name: str = "unseenet"              # how this node introduces itself to peers
    max_size: int = MAX_SIZE
    min_pow: int = 18
    # UN-RFC 0025 section 5: the lowest level accepted; None is "-" (no ripening needed)
    min_ripe: int | None = field(default_factory=lambda: rp.DEFAULT_MIN_RIPE)
    retention_days: int = 90
    new_groups: str = "accept"            # "accept" | "trusted" | "manual"
    trusted_owners: list[str] = field(default_factory=list)
    peers: list[PeerConfig] = field(default_factory=list)
    forward_delay: tuple[float, float] = (0.0, 60.0)  # UN-RFC 0005, section 5.5
    require_peer_auth: bool = False
    excludes: str = ""                   # wildmat of groups not carried by choice (UN-RFC 0021)
    pull_interval: float = 3600.0        # seconds between catch-up pulls (UN-RFC 0017)
    honour_blocks: bool = False          # UN-RFC 0018 section 8.2: maintainers' blocks
    profiles: str = "accept"             # UN-RFC 0022 section 10: carry profile@ groups
    avatars: str = "refuse"              # ... and avatar@ groups: images, so off by default
    # UN-RFC 0011: who runs this node and how to reach them
    operator: dict = field(default_factory=dict)   # key, contact, description, logging


def wildmat(pattern: str, text: str) -> bool:
    """RFC 3977 wildmat: comma-separated patterns, '!' negates, last match wins."""
    result = False
    for pat in pattern.split(","):
        neg = pat.startswith("!")
        if fnmatch.fnmatchcase(text, pat[1:] if neg else pat):
            result = not neg
    return result


class Node:
    def __init__(self, store: Store, config: NodeConfig | None = None,
                 key: crypto.Identity | None = None):
        self.store = store
        self.config = config or NodeConfig()
        # The node key identifies this node to its peers (UN-RFC 0016). A real node
        # keeps it sealed in its data directory; without one (tests) it is temporary.
        self.key = key or crypto.Identity.generate()
        self._listeners: list[asyncio.Event] = []
        self._watchers: list[tuple[str, asyncio.Queue]] = []   # UN-RFC 0008 section 2
        self.stats = Stats()                  # for the operator's monitor (node/stats.py)
        self._blocks: dict[str, tuple[float, dict]] = {}   # group name -> (time, blocks)
        # comments that came before their thread (UN-RFC 0030, 4.1):
        # thread root Message-ID -> [(time held, raw, source, from_peer)]
        self._held: dict[str, list[tuple[float, bytes, str | None, bool]]] = {}
        # UN-RFC 0040 section 6: key-bound groups whose manifest a peer's article
        # showed we lack, since when; and the peers to reconcile with soon.
        self._kb_waiting: dict[str, float] = {}
        self.reconcile_wanted: set[str] = set()
        # UN-RFC 0025 section 3.4: each key's chain and how many segments are verified
        self._ripe_cache: dict[bytes, tuple[rp.Chain, int]] = {}

    def watch(self, pattern: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._watchers.append((pattern, queue))
        return queue

    def unwatch(self, queue: asyncio.Queue) -> None:
        self._watchers = [(p, q) for p, q in self._watchers if q is not queue]

    def _notify_watchers(self, art: Article) -> None:
        number = self.store.number_of(art.message_id)
        if number is None:
            return
        for pattern, queue in self._watchers:
            if wildmat(pattern, art.group):
                try:
                    queue.put_nowait((art.group, number, art.message_id))
                except asyncio.QueueFull:
                    pass                      # a slow watcher catches up by polling

    def peer_config(self, name: str) -> PeerConfig | None:
        for peer in self.config.peers:
            if peer.name == name:
                return peer
        return None

    def subscribe(self) -> asyncio.Event:
        """An event that is set whenever a new article is queued for peers."""
        event = asyncio.Event()
        self._listeners.append(event)
        return event

    # ------------------------------------------------------------------
    # Acceptance pipeline
    # ------------------------------------------------------------------
    def accept(self, raw: bytes, source: str | None = None,
               now: datetime | None = None, from_peer: bool = False,
               how: str | None = None) -> Article:
        """Validate and store an article. Raises ArticleError with an RFC 0005 reason.

        ``from_peer`` is true for articles pushed by another node (IHAVE/TAKETHIS),
        authenticated or not; ``source`` names the peer when it authenticated.
        ``how`` is only for the counters: "client", "peer" or "pull".
        """
        try:
            art = self._accept(raw, source, now, from_peer)
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
    KB_WAIT_MAX = 10000

    def _wait_for_manifest(self, group_id: str, source: str | None) -> None:
        """A peer offers an article in a key-bound group we hold no manifest for.
        Rather than refuse it, ask the peer to try again later (431/436), and have
        the next pull from it reconcile, which fetches the manifest. After
        KB_WAIT_SECONDS without it the article is refused as before: the group
        may simply not exist."""
        now = time.monotonic()
        if len(self._kb_waiting) >= self.KB_WAIT_MAX:
            for gid in [g for g, t in self._kb_waiting.items() if now - t > self.KB_WAIT_SECONDS]:
                del self._kb_waiting[gid]
        since = self._kb_waiting.get(group_id)
        if since is None:
            if len(self._kb_waiting) >= self.KB_WAIT_MAX:
                return
            since = self._kb_waiting[group_id] = now
        if now - since > self.KB_WAIT_SECONDS:
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
                from_peer: bool) -> Article:
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
                raise ArticleError("group", "group not carried")
            if manifest.local and from_peer:
                raise ArticleError("group", "local group: never accepted from peers")
            retention = min(self.config.retention_days, manifest.retention_days)
            if parse_date(art["Date"]) < now - timedelta(days=retention):
                raise ArticleError("date", "older than retention")

        group_pow = manifest.min_pow if manifest is not None and not is_manifest else 0
        required = self._required_pow(art, manifest, group_pow, source, from_peer)
        if art.proven_pow() < required:
            raise ArticleError("postage", f"need {required} bits")

        if is_manifest:
            self._accept_manifest(art, manifest, raw, from_peer)
        elif ctl:
            self._accept_control(art, manifest, raw)
        else:
            versions = parse_supersedes(art)          # an edit (UN-RFC 0042)
            held = self._check_edit(art, manifest, versions) if versions else {}
            self._check_cancelled(art, manifest)
            self._check_superseded(art)
            check_permitted(art, manifest, self.store.epochs(art.group),
                            self.store.closed_before(art.group), thread_root=self._thread_root)
            self._check_blocked(art)
            self.store.add(art, raw)
            if versions:
                self._apply_edit(art, versions, held)
        self._enqueue(art, source)
        self._notify_watchers(art)
        log.info("accepted %s in %s", art.message_id, art.group)
        return art

    # --- key ripening (UN-RFC 0025) ---
    def _required_pow(self, art: Article, manifest: Manifest | None, group_pow: int,
                      source: str | None, from_peer: bool) -> int:
        """The postage this article needs, with its author's ripening (section 5).

        Postage is checked first against the least any level could need, so a
        flood of bogus proofs costs the sender postage before it costs us work
        (section 3.4). Sealed inbox articles are signed by one-time keys that
        cannot ripen (UN-RFC 0009): they pay as an unripe key where "-" is
        allowed (section 3.5)."""
        base = max(self.config.min_pow, group_pow)
        least = max(rp.FLOOR_POW, base + min(s for _, _, s in rp.LEVELS))
        if art.proven_pow() < least:
            raise ArticleError("postage", f"need {least} bits")
        group_min = rp.parse_min(manifest.raw.get("min_ripe")) if manifest is not None else 0
        minimums = [self.config.min_ripe, group_min]
        if self._sealed_inbox(art) or None in minimums:      # "-" somewhere: no proof needed
            lv = self._ripening_level(art, source, from_peer, required=False)
            return rp.required_pow(self.config.min_pow, group_pow, lv, allow_unripe=True)
        lv = self._ripening_level(art, source, from_peer, required=True)
        for minimum in minimums:
            if not rp.meets(lv, minimum):
                raise ArticleError("ripening", f"level {minimum} needed, the key is at level "
                                   + ("-" if lv is None else str(lv)))
        return rp.required_pow(self.config.min_pow, group_pow, lv)

    @staticmethod
    def _sealed_inbox(art: Article) -> bool:
        return (art.get("Encrypted", "").strip() == INBOX_SCHEME
                and art.group.split("@", 1)[0] == "inbox")

    def _ripening_level(self, art: Article, source: str | None, from_peer: bool,
                        required: bool) -> int | None:
        """The level the article's Key-Ripening header shows (section 3.4)."""
        value = art.get("Key-Ripening")
        if not value:
            if required:
                raise ArticleError("ripening", "unknown: no Key-Ripening header")
            return None
        try:
            t, y = rp.parse_header(value)
        except rp.RipeningError as exc:
            raise ArticleError("syntax", str(exc)) from exc
        pk = art.author_key
        chain = self._own_chain(art) if self._is_ripe_group(art) else self._chain(pk)
        if chain is None or chain.points().get(t) != y:
            if not required:
                return None                    # it may name a point we don't hold yet
            ripe = make_group_id(rp.GROUP_NAME, pk)
            if from_peer and self.store.manifest(ripe) is None:
                self._wait_for_manifest(ripe, source)     # the peer sends ripe@ first
            raise ArticleError("ripening", "unknown: post your ripe@ manifest first")
        return rp.level(t)

    def _is_ripe_group(self, art: Article) -> bool:
        return art.control == ["manifest"] and self._group_name(art.group) == rp.GROUP_NAME

    def _chain(self, pk: bytes) -> rp.Chain | None:
        """The verified chain of a key, from its ripe@ manifest; cached with how far
        it has been verified, so a new version costs only its new segments."""
        m = self.store.manifest(make_group_id(rp.GROUP_NAME, pk))
        if m is None or "ripening" not in m.raw:
            return None
        return self._verified(pk, m.raw["ripening"])

    def _own_chain(self, art: Article) -> rp.Chain | None:
        """A ripe@ manifest names a point on the chain it carries itself."""
        try:
            data = Manifest.from_article(art).raw
        except ArticleError:
            return None
        return self._verified(art.author_key, data.get("ripening")) if data.get("ripening") else None

    def _verified(self, pk: bytes, obj) -> rp.Chain:
        try:
            chain = rp.Chain.from_manifest(obj)
        except rp.RipeningError as exc:
            raise ArticleError("syntax", str(exc)) from exc
        known, done = self._ripe_cache.get(pk, (None, 0))
        already = done if known is not None and chain.extends(known) and done <= len(known.segments) else 0
        try:
            if not rp.available():
                raise ArticleError("ripening", "this node cannot verify ripening")
            n = rp.verify(pk, chain, already=min(already, len(chain.segments)))
        except rp.RipeningError as exc:
            raise ArticleError("ripening", str(exc)) from exc
        if len(self._ripe_cache) > 100_000:
            self._ripe_cache.clear()
        self._ripe_cache[pk] = (chain, n)
        return chain

    def _check_ripe_manifest(self, m: Manifest, current: Manifest | None) -> None:
        """A new version of ripe@ must hold a valid chain that extends the old (3.3)."""
        if m.name != rp.GROUP_NAME:
            if "ripening" in m.raw:
                raise ArticleError("syntax", "ripening belongs in a ripe@ group")
            return
        if "ripening" not in m.raw:
            raise ArticleError("syntax", "a ripe@ manifest needs a ripening chain")
        chain = self._verified(m.owner, m.raw["ripening"])
        if current is not None and "ripening" in current.raw:
            old = rp.Chain.from_manifest(current.raw["ripening"])
            if not chain.extends(old):
                raise ArticleError("ripening", "does not extend the chain this node holds")

    def _accept_rmgroup(self, art: Article, manifest: Manifest | None, raw: bytes,
                        source: str | None, from_peer: bool) -> Article:
        """UN-RFC 0013: the owner removes the group from the network."""
        author = art.author_key
        if manifest is not None:
            if author != manifest.owner:
                raise ArticleError("permission", "only the group's owner can remove it")
            if manifest.local and from_peer:
                raise ArticleError("group", "local group: never accepted from peers")
        elif crypto.fingerprint(author) != split_group_id(art.group)[1]:
            raise ArticleError("permission", "only the group's owner can remove it")
        if art.proven_pow() < self.config.min_pow:          # exempt from the group's own minimum
            raise ArticleError("postage", f"need {self.config.min_pow} bits")
        local = manifest is not None and manifest.local
        self.store.remember(art.message_id)
        self.store.add_tombstone(art.group, "owner", art.message_id, raw)
        deleted = self.store.remove_group(art.group)
        if not local:
            self._enqueue(art, source, force=True)
        log.info("group %s removed by its owner (%d articles deleted)", art.group, deleted)
        return art

    def drop_group(self, group_id: str) -> int:
        """UN-RFC 0013 section 3: the operator stops carrying a group on this node."""
        self.store.add_tombstone(group_id, "operator")
        return self.store.remove_group(group_id)

    def _accept_manifest(self, art: Article, current: Manifest | None, raw: bytes,
                         from_peer: bool = False) -> None:
        m = Manifest.from_article(art)
        if m.local and from_peer:
            raise ArticleError("group", "local group: never accepted from peers")
        if current is not None:
            if m.type != current.type or m.owner != current.owner or m.local != current.local:
                raise ArticleError("permission", "manifest may not change type, owner or locality")
        elif (not self.store.known_group(art.group) and not self._is_profile_group(art.group)
              and not self._allow_new_group(m)):
            # profile and avatar groups are accepted whatever new_groups says (UN-RFC 0022, 10)
            # an expired key-bound group is not new: its renewal is accepted (UN-RFC 0029)
            raise ArticleError("group", "node does not accept this new group")
        if m.expired():
            raise ArticleError("group", "key-bound group has expired")
        self._check_profile_content(m)
        self._check_ripe_manifest(m, current)
        self.store.add(art, raw)
        if m.supersedes(current):
            self.store.set_manifest(m)

    @staticmethod
    def _group_name(group_id: str) -> str:
        try:
            return split_group_id(group_id)[0]
        except ValueError:
            return ""

    def _is_profile_group(self, group_id: str) -> bool:
        """Groups every key may have, accepted whatever new_groups says: profiles,
        pictures (UN-RFC 0022 section 10) and ripening (UN-RFC 0025 section 3.3)."""
        return self._group_name(group_id) in (profiles.PROFILE_NAME, profiles.AVATAR_NAME,
                                              rp.GROUP_NAME)

    def _check_profile_group(self, group_id: str) -> None:
        """UN-RFC 0022 section 10: the operator decides whether profiles and pictures
        are carried; pictures only when turned on."""
        name = self._group_name(group_id)
        if name == profiles.PROFILE_NAME and self.config.profiles != "accept":
            raise ArticleError("group", "this node does not carry profiles")
        if name == profiles.AVATAR_NAME and self.config.avatars != "accept":
            raise ArticleError("group", "this node does not carry pictures")

    def _check_profile_content(self, m: Manifest) -> None:
        """A profile or picture manifest must hold a valid one (sections 4, 8.1)."""
        own = {profiles.PROFILE_NAME: "profile", profiles.AVATAR_NAME: "avatar"}.get(m.name)
        try:
            for field_ in ("profile", "avatar"):
                if field_ in m.raw and field_ != own:
                    raise profiles.ProfileError(f"{field_} belongs in a {field_}@ group")
            if own == "profile" and "profile" in m.raw:
                profiles.check_profile(m.raw["profile"])
            if own == "avatar" and "avatar" in m.raw:
                profiles.check_picture(m.raw["avatar"])
        except profiles.ProfileError as exc:
            raise ArticleError("syntax", str(exc)) from exc

    def _allow_new_group(self, m: Manifest) -> bool:
        if self.config.new_groups == "accept":
            return True
        if self.config.new_groups == "trusted":
            return crypto.key_to_text(m.owner) in self.config.trusted_owners
        return False  # "manual": operator adds groups out of band

    def _accept_control(self, art: Article, manifest: Manifest, raw: bytes) -> None:
        ctl = art.control or []
        author = art.author_key
        if ctl[0] in ("key-update", "key-grant"):
            if manifest.type != "closed" or author != manifest.owner:
                raise ArticleError("permission", "only the owner of a closed group may issue keys")
            epoch, member_key, _ = parse_key_update(art)
            self.store.add(art, raw)
            if member_key is not None:
                self.store.set_epoch(art.group, epoch, member_key, art.message_id)
                if parse_canonical_json(art.body).get("closes_previous") is True:
                    self.store.close_previous(art.group, epoch)
        elif ctl[0] == "cancel" and len(ctl) == 2:
            target = ctl[1]
            meta = self.store.get_meta(target)
            privileged = author == manifest.owner or author in manifest.moderators
            if meta is not None:
                group_id, target_author = meta
                if group_id != art.group:
                    raise ArticleError("permission", "cancel for another group")
                if not privileged and crypto.key_from_text(target_author) != author:
                    raise ArticleError("permission", "not allowed to cancel")
                stored = self.store.get(target)
                if stored is not None and Article.from_bytes(stored).control:
                    # manifests, key updates, cancels: never cancelled (UN-RFC 0004, 7.1)
                    raise ArticleError("permission", "control articles cannot be cancelled")
                self.store.delete(target)
            else:
                self.store.add_cancel(target, art["Author-Key"], art.group)
            self.store.add(art, raw)
        else:
            raise ArticleError("syntax", f"unknown control {ctl[0]!r}")

    # --- maintainers' blocks (UN-RFC 0018 sections 5.4 and 8.2) ---
    BLOCKS_TTL = 300.0

    def _check_blocked(self, art: Article) -> None:
        if not self.config.honour_blocks or art.group.startswith("inbox@"):
            return
        blocked = self.blocks_for(art.group)
        hit = blocked.get(art["Author-Key"])
        if hit:
            raise ArticleError("permission", f"blocked in {hit[0]}.* by its maintainer: {hit[1]}")

    def blocks_for(self, group_id: str) -> dict[str, tuple[str, str]]:
        """{key: (hierarchy, reason)} blocked for a group, from the lists this node
        carries (the project's root list and the maintainers' lists)."""
        from .. import hierarchies as hz
        name = group_id.rpartition("@")[0] or group_id
        cached = self._blocks.get(name)
        if cached and time.monotonic() - cached[0] < self.BLOCKS_TTL:
            return cached[1]
        from ..known_nodes import PROJECT_KEY
        root = self._newest_list(hz.HIERARCHIES_GROUP, PROJECT_KEY,
                                 lambda body: hz.parse_root_list(body)[1])
        if root is None:
            root = hz.builtin_root_list()[1]
        lists: dict = {"unseenet": hz.builtin_checkgroups()}
        h = hz.policy_of(name.split(".")[0], root)
        for _ in range(hz.MAX_DEPTH + 1):
            if h.policy != "governed":
                break
            lst = self._newest_list(h.list, h.maintainer,
                                    lambda body, n=h.name: hz.parse_hierarchy_list(body, n))
            if lst is None:
                lst = lists.get(h.name)
            if lst is None:
                break
            lists[h.name] = lst
            deeper = [x for x in lst.sub.values() if hz._within(name, x.name)]
            if not deeper:
                break
            h = max(deeper, key=lambda x: len(x.name))
        result = hz.blocks_for(name, root, lists)
        self._blocks[name] = (time.monotonic(), result)
        return result

    def _newest_list(self, group_id: str | None, owner: str | None, parse):
        """The newest valid list posted in a channel group by its owner or posters."""
        if not group_id or not owner:
            return None
        manifest = self.store.manifest(group_id)
        if manifest is None or crypto.key_to_text(manifest.owner) != owner:
            return None
        allowed = {manifest.owner, *manifest.posters}
        best = None
        for n in self.store.numbers(group_id):
            found = self.store.by_number(group_id, n)
            if not found:
                continue
            try:
                art = Article.from_bytes(found[1])
                if art.control or art.author_key not in allowed:
                    continue
                value = parse(art.body)
                date = parse_date(art["Date"])
            except (ArticleError, ValueError, KeyError, TypeError, crypto.CryptoError):
                continue
            if best is None or date > best[0]:
                best = (date, value)
        return best[1] if best else None

    # --- edits (UN-RFC 0042) ---
    @staticmethod
    def _kind(art: Article) -> str:
        # in a closed group the kind is in the encrypted inner article: unknown here
        return "" if "Encrypted" in art else message_kind(art)

    def _check_edit(self, art: Article, manifest: Manifest, versions: list[str]) -> dict:
        """Section 3.1: every version we hold must be the same author's, in this group,
        of the same kind and place in its thread, and no control article. Returns
        {Message-ID: Date} of the versions held."""
        if manifest.type == "inbox":
            raise ArticleError("permission", "private posts cannot be edited")
        author, kind = art["Author-Key"], self._kind(art)
        refs = art.get("References", "").split()
        held: dict[str, int] = {}
        for v in versions:
            meta = self.store.get_meta(v)
            if meta is None:
                continue
            group_id, v_author = meta
            old = Article.from_bytes(self.store.get(v))
            if group_id != art.group or v_author != author:
                raise ArticleError("permission", "only its author can edit a post")
            if old.control:
                raise ArticleError("permission", "control articles cannot be edited")
            if kind and self._kind(old) and self._kind(old) != kind:
                raise ArticleError("permission", "an edit keeps the kind of the post")
            if old.get("References", "").split() != refs:
                raise ArticleError("permission", "an edit keeps the post's place in its thread")
            held[v] = int(parse_date(old["Date"]).timestamp())
        return held

    def _apply_edit(self, art: Article, versions: list[str], held: dict) -> None:
        """Withdraw the versions held, remember the rest as pending (section 3.1)."""
        store = self.store
        dates = list(held.values()) + [d for d in (store.first_date(v) for v in versions)
                                       if d is not None]
        first = min(dates) if dates else None
        for v in versions:
            if v in held:
                store.delete(v)                    # as a valid cancel (UN-RFC 0004, 7.2)
            store.add_supersede(v, art.message_id, art["Author-Key"], art.group,
                                self._kind(art), first)
        store.db.execute("UPDATE supersedes SET new=? WHERE new IN (%s)" % ",".join("?" * len(versions)),
                         (art.message_id, *versions))
        store.db.commit()

    def _check_superseded(self, art: Article) -> None:
        """A version that arrives after its edit is refused (section 3.1)."""
        pending = self.store.supersede_for(art.message_id)
        if not pending or art.control:
            return
        _, author, group_id, kind = pending
        if group_id == art.group and author == art["Author-Key"] and (
                not kind or not self._kind(art) or kind == self._kind(art)):
            self.store.remember(art.message_id)
            raise ArticleError("permission", "article was replaced by an edit")

    def _check_cancelled(self, art: Article, manifest: Manifest) -> None:
        pending = self.store.cancel_for(art.message_id)
        if not pending:
            return
        author_key, group_id = pending
        canceller = crypto.key_from_text(author_key)
        if group_id == art.group and (canceller == art.author_key or canceller == manifest.owner
                                      or canceller in manifest.moderators):
            self.store.remember(art.message_id)
            raise ArticleError("permission", "article was cancelled")

    def _enqueue(self, art: Article, source: str | None, force: bool = False) -> None:
        manifest = self.store.manifest(art.group)
        if not force and manifest is not None and manifest.local:
            return                       # local groups never leave this node (UN-RFC 0009, 4)
        lo, hi = self.config.forward_delay
        if manifest is not None and manifest.low_latency:
            lo = hi = 0.0                # chat groups: no random delay (UN-RFC 0008, 3.2)
        ripe = None
        if art.get("Key-Ripening") and not self._is_ripe_group(art):
            m = self.store.manifest(make_group_id(rp.GROUP_NAME, art.author_key))
            ripe = m.message_id if m is not None else None
        for peer in self.config.peers:
            if peer.name != source and wildmat(peer.groups, art.group):
                at = time.time() + random.uniform(lo, hi)
                if ripe:                       # first, so the peer can check the article
                    self.store.enqueue(peer.name, ripe, at - 0.001)
                self.store.enqueue(peer.name, art.message_id, at)
        for event in self._listeners:
            event.set()

    def offer(self, peer_name: str, message_ids: list[str]) -> int:
        """Queue articles a reconciliation showed ``peer_name`` lacks, for its feeder
        (UN-RFC 0040 section 4.3: offered with CHECK/TAKETHIS). Returns how many."""
        peer = self.peer_config(peer_name)
        if peer is None:
            return 0
        n = 0
        for msgid in message_ids:
            meta = self.store.get_meta(msgid)
            if meta and wildmat(peer.groups, meta[0]):
                self.store.enqueue(peer.name, msgid, time.time())
                n += 1
        for event in self._listeners:
            event.set()
        return n

    def excludes(self) -> str:
        """UN-RFC 0021 section 3: `excludes` from node.toml, plus every dropped group."""
        parts = [p for p in self.config.excludes.split(",") if p]
        parts += [g for g in self.store.dropped_groups() if g not in parts]
        return ",".join(parts)

    def node_info(self) -> dict:
        cfg = self.config
        op = cfg.operator or {}
        info = {"v": 1, "name": cfg.name, "software": f"unseenet {__version__}",
                "node_key": self.key.key_text,
                "policy": {"new_groups": cfg.new_groups, "min_pow": cfg.min_pow,
                           "min_ripe": "-" if cfg.min_ripe is None else cfg.min_ripe,
                           "retention_days": cfg.retention_days, "max_size": cfg.max_size,
                           "archive": False, "honours_blocks": cfg.honour_blocks,
                           "profiles": cfg.profiles, "avatars": cfg.avatars,
                           "logging": op.get("logging", "accepted articles only, no reading activity")}}
        excludes = self.excludes()
        if excludes:
            info["policy"]["excludes"] = excludes
        for key in ("operator", "contact", "description"):
            value = op.get("key" if key == "operator" else key)
            if value:
                info[key] = value
        return info

    # ------------------------------------------------------------------
    # ONNTP server
    # ------------------------------------------------------------------
    async def serve(self, host: str = "127.0.0.1", port: int = 1119) -> asyncio.base_events.Server:
        return await asyncio.start_server(self._session, host, port, limit=MAX_LINE * 200)

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        session = Session(self, reader, writer)
        self.stats.session_opened()
        try:
            await session.run()
        except (ConnectionError, asyncio.IncompleteReadError, TimeoutError):
            pass        # gone, cut off, or idle for longer than the session allows
        finally:
            self.stats.session_closed(was_peer=session.peer is not None)
            writer.close()


class Session:
    IDLE_SECONDS = 600.0       # a connection silent this long is closed

    def __init__(self, node: Node, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.node, self.reader, self.writer = node, reader, writer
        self.group: str | None = None
        self.current: int | None = None
        self.peer: str | None = None
        self._user: str | None = None
        self._challenge: tuple[bytes, bytes] | None = None   # (claimed key, nonce)
        self._auth_failures = 0
        self._reconcile_rounds = 0
        self._manifest_requests: list[float] = []   # times of recent XUN-MANIFESTS

    def send(self, line: str) -> None:
        self.writer.write(line.encode("utf-8") + b"\r\n")

    async def run(self) -> None:
        self.send(f"200 Unseenet node {__version__} ready (posting ok)")
        while True:
            await self.writer.drain()
            raw = await asyncio.wait_for(self.reader.readline(), timeout=self.IDLE_SECONDS)
            if not raw:
                return
            if len(raw) > MAX_LINE:
                self.send("501 line too long")
                continue
            parts = raw.decode("utf-8", "replace").strip().split()
            if not parts:
                continue
            cmd, args = parts[0].upper(), parts[1:]
            if cmd == "QUIT":
                self.send("205 bye")
                await self.writer.drain()
                return
            if cmd == "MODE" and args and args[0].upper() in ("READER", "STREAM"):
                if args[0].upper() == "STREAM":
                    self.send("203 streaming permitted")
                else:
                    self.send("200 posting allowed")
                continue
            if cmd == "LIST":
                cmd = "LIST_" + (args[0].upper() if args else "ACTIVE")
                args = args[1:]
            handler = getattr(self, "cmd_" + cmd.lower().replace(".", "_").replace("-", "_"), None)
            if handler is None:
                self.send("500 unknown command")
                continue
            await handler(args)

    # --- capabilities & misc ---
    async def cmd_capabilities(self, args):
        cfg = self.node.config
        self.send("101 capability list follows")
        for cap in ("VERSION 2", "READER", "POST", "IHAVE", "STREAMING", "AUTHINFO USER",
                    "LIST ACTIVE NEWSGROUPS OVERVIEW.FMT HEADERS", "NEWNEWS", "OVER MSGID", "HDR",
                    "UNSEENET 1",
                    f"UNSEENET-MAXSIZE {cfg.max_size}", f"UNSEENET-MINPOW {cfg.min_pow}",
                    "UNSEENET-MINRIPE " + ("-" if cfg.min_ripe is None else str(cfg.min_ripe)),
                    "UNSEENET-NODEINFO", "UNSEENET-WATCH", "UNSEENET-PEERKEY",
                    "UNSEENET-RECONCILE 1", f"UNSEENET-MANIFESTS {MANIFESTS_MAX}"):
            self.send(cap)
        self.send(".")

    async def cmd_date(self, args):
        self.send("111 " + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))

    async def cmd_help(self, args):
        self.send("100 help text follows")
        self.send("See UN-RFC 0005 for the supported command profile.")
        self.send(".")

    async def cmd_authinfo(self, args):
        if len(args) < 2:
            self.send("501 syntax")
        elif args[0].upper() == "USER":
            self._user = args[1]
            self.send("381 password required")
        elif args[0].upper() == "PASS" and self._user:
            for peer in self.node.config.peers:
                if (peer.name == self._user and peer.password
                        and hmac.compare_digest(peer.password.encode(), args[1].encode())):
                    self.peer = peer.name
                    self.node.stats.peer_authenticated()
                    self.send("281 authentication accepted")
                    return
            await self._auth_failed()
        else:
            self.send("482 authentication commands issued out of sequence")

    # --- peer authentication with node keys (UN-RFC 0016) ---
    async def cmd_xun_peer(self, args):
        """XUN-PEER <key>: a node claims a key; we answer with ours and a challenge."""
        if len(args) != 1:
            self.send("501 syntax: XUN-PEER <node key>")
            return
        try:
            claimed = crypto.key_from_text(args[0])
        except crypto.CryptoError:
            self.send("501 malformed key")
            return
        nonce = os.urandom(32)
        self._challenge = (claimed, nonce)
        # The same answer whether or not the key is a configured peer: no probing.
        self.send(f"383 {self.node.key.key_text} {crypto.b64(nonce)}")

    async def cmd_xun_peer_proof(self, args):
        """XUN-PEER-PROOF <signature> over nonce || our key || its key."""
        if self._challenge is None:
            self.send("482 XUN-PEER first")
            return
        claimed, nonce = self._challenge
        self._challenge = None                      # one attempt per challenge
        if len(args) != 1:
            self.send("501 syntax: XUN-PEER-PROOF <signature>")
            return
        peer = next((p for p in self.node.config.peers
                     if p.key and p.public_key() == claimed), None)
        try:
            sig = crypto.sig_from_text(args[0])
        except crypto.CryptoError:
            sig = b""
        message = nonce + self.node.key.public_key + claimed
        if peer is not None and sig and crypto.verify(claimed, crypto.PURPOSE_PEER_AUTH,
                                                       message, sig):
            self.peer = peer.name
            self.node.stats.peer_authenticated()
            self.send("281 peer authenticated")
            log.info("peer %s authenticated by key", peer.name)
            return
        await self._auth_failed()

    async def _auth_failed(self) -> None:
        self._auth_failures += 1
        await asyncio.sleep(min(self._auth_failures, 5))     # slow down guessing
        self.send("481 authentication failed")
        if self._auth_failures >= 3:
            await self.writer.drain()
            raise ConnectionError("too many failed authentications")

    # --- lists ---
    async def cmd_list_active(self, args):
        pattern = args[0] if args else "*"
        self.send("215 list follows")
        for gid, high, low, _ in self.node.store.groups(ordinary=True):   # UN-RFC 0040, 3
            if wildmat(pattern, gid):
                self.send(f"{gid} {high} {low} y")
        self.send(".")

    async def cmd_list_newsgroups(self, args):
        pattern = args[0] if args else "*"
        self.send("215 descriptions follow")
        for gid, _, _, desc in self.node.store.groups(ordinary=True):
            if wildmat(pattern, gid):
                self.send(f"{gid}\t{desc}")
        self.send(".")

    async def cmd_xun_watch(self, args):
        """UN-RFC 0008: tell the client about new articles until it sends DONE."""
        pattern = args[0] if args else "*"
        queue = self.node.watch(pattern)
        self.send("290 watching")
        await self.writer.drain()
        line_task = asyncio.ensure_future(self.reader.readline())
        get_task = asyncio.ensure_future(queue.get())
        try:
            while True:
                done, _ = await asyncio.wait({line_task, get_task}, timeout=300,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    self.send("293 keepalive")
                if get_task in done:
                    group, number, msgid = get_task.result()
                    self.send(f"291 {group} {number} {msgid}")
                    get_task = asyncio.ensure_future(queue.get())
                await self.writer.drain()
                if line_task in done:
                    line = line_task.result()
                    if not line:
                        raise ConnectionError("client went away while watching")
                    if line.strip().upper() == b"DONE":
                        self.send("292 done")
                        return
                    line_task = asyncio.ensure_future(self.reader.readline())
        finally:
            self.node.unwatch(queue)
            for task in (line_task, get_task):
                task.cancel()

    async def cmd_list_unseenet_nodeinfo(self, args):
        """UN-RFC 0011: who runs this node and its policy."""
        self.send("215 node information follows")
        self.send(canonical_json(self.node.node_info()))
        self.send(".")

    # --- group navigation ---
    async def cmd_group(self, args):
        removed = self.node.store.tombstone(args[0]) if args else None
        if removed:
            self.send("411 no such group (removed by its owner)" if removed == "owner"
                      else "411 no such group (dropped by this node)")
            return
        if not args or self.node.store.manifest(args[0]) is None:
            self.send("411 no such group")
            return
        self.group = args[0]
        nums = self.node.store.numbers(self.group)
        self.current = nums[0] if nums else None
        low, high = (nums[0], nums[-1]) if nums else (1, 0)
        self.send(f"211 {len(nums)} {low} {high} {self.group}")

    async def cmd_listgroup(self, args):
        if args:
            await self.cmd_group(args[:1])
            if self.group != args[0]:
                return
        if not self.group:
            self.send("412 no group selected")
            return
        nums = self.node.store.numbers(self.group)
        low, high = (nums[0], nums[-1]) if nums else (1, 0)
        self.send(f"211 {len(nums)} {low} {high} {self.group} list follows")
        for n in nums:
            self.send(str(n))
        self.send(".")

    def _lookup(self, args) -> tuple[int, str, bytes] | None:
        store = self.node.store
        if args and args[0].startswith("<"):
            raw = store.get(args[0])
            if raw is None:
                self.send("430 no such article")
                return None
            return 0, args[0], raw
        if not self.group:
            self.send("412 no group selected")
            return None
        number = int(args[0]) if args and args[0].isdigit() else self.current
        found = store.by_number(self.group, number) if number else None
        if not found:
            self.send("423 no such article number")
            return None
        self.current = number
        return number, found[0], found[1]

    def _reader_headers(self, number: int) -> bytes:
        # Synthesized for newsreaders only, never part of the article (UN-RFC 0005, 3).
        xref = f"\r\nXref: unseenet {self.group}:{number}" if number and self.group else ""
        return ("Path: not-for-mail" + xref).encode()

    async def _send_part(self, args, code: int, part: str):
        found = self._lookup(args)
        if not found:
            return
        number, msgid, raw = found
        head, _, body = raw.partition(b"\r\n\r\n")
        if not self.peer:
            head = head + b"\r\n" + self._reader_headers(number)
        payload = {"article": head + b"\r\n\r\n" + body, "head": head + b"\r\n", "body": body,
                   "stat": None}[part]
        self.send(f"{code} {number} {msgid}")
        if payload is not None:
            self.writer.write(dot_stuff(payload))
        if part in ("article", "body") and not self.peer:
            self.node.stats.served_one()          # how many, never which (UN-RFC 0011)

    async def cmd_article(self, args):
        await self._send_part(args, 220, "article")

    async def cmd_head(self, args):
        await self._send_part(args, 221, "head")

    async def cmd_body(self, args):
        await self._send_part(args, 222, "body")

    async def cmd_stat(self, args):
        await self._send_part(args, 223, "stat")

    # --- overview (RFC 3977 sections 8.3-8.5; UN-RFC 0005 section 2.4) ---
    OVERVIEW_FMT = ("Subject:", "From:", "Date:", "Message-ID:", "References:",
                    ":bytes", ":lines", "Xref:full")

    def _range(self, args) -> list[tuple[int, str, bytes]] | None:
        """Articles named by a message-id, a number, n-, n-m or (none) the current one."""
        store = self.node.store
        if args and args[0].startswith("<"):
            raw = store.get(args[0])
            if raw is None:
                self.send("430 no such article")
                return None
            return [(0, args[0], raw)]
        if not self.group:
            self.send("412 no group selected")
            return None
        nums = store.numbers(self.group)
        if not args:
            if self.current is None:
                self.send("420 no current article")
                return None
            lo = hi = self.current
        else:
            first, dash, last = args[0].partition("-")
            try:
                lo = int(first)
                hi = (int(last) if last else (nums[-1] if nums else lo)) if dash else lo
            except ValueError:
                self.send("501 syntax: range n, n- or n-m")
                return None
        out = []
        for n in nums:
            if lo <= n <= hi:
                found = store.by_number(self.group, n)
                if found:
                    out.append((n, found[0], found[1]))
        if not out:
            self.send("423 no articles in that range")
            return None
        return out

    @staticmethod
    def _clean(value: str) -> str:
        return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")

    def _overview_fields(self, number: int, raw: bytes) -> dict[str, str]:
        """The overview of one article. Articles a newsreader cannot show get a
        fixed subject, so readers do not show empty lines (#21)."""
        try:
            art = Article.from_bytes(raw)
        except ArticleError:
            return {"Subject:": "(invalid article)"}
        ctl = art.control
        encrypted = art.get("Encrypted", "")
        if ctl and ctl[0] == "manifest":
            subject = "(group settings)"
        elif ctl:
            subject = f"(control: {ctl[0]})"
        elif encrypted.strip() == INBOX_SCHEME or art.group.startswith("inbox@"):
            subject = "(private message)"
        elif encrypted:
            subject = "(encrypted)"
        else:
            subject = art.get("Subject") or "(no subject)"
        head, _, body = raw.partition(b"\r\n\r\n")
        group = self.group or art.group
        return {
            "Subject:": subject, "From:": art.get("From") or "(unknown)",
            "Date:": art.get("Date", ""), "Message-ID:": art.message_id,
            "References:": art.get("References", ""), ":bytes": str(len(raw)),
            ":lines": str(body.count(b"\n") + (1 if body and not body.endswith(b"\n") else 0)),
            "Xref:full": f"Xref: unseenet {group}:{number}" if number else "",
        }

    async def cmd_over(self, args):
        found = self._range(args)
        if found is None:
            return
        self.send("224 overview information follows")
        for number, _, raw in found:
            f = self._overview_fields(number, raw)
            self.send("\t".join([str(number)] + [self._clean(f.get(k, "")) for k in self.OVERVIEW_FMT]))
        self.send(".")

    cmd_xover = cmd_over

    async def cmd_list_overview_fmt(self, args):
        self.send("215 order of fields in overview database")
        for field_ in self.OVERVIEW_FMT:
            self.send(field_)
        self.send(".")

    async def cmd_hdr(self, args, code: int = 225):
        if not args:
            self.send("501 syntax: HDR field [range|message-id]")
            return
        name = args[0]
        found = self._range(args[1:])
        if found is None:
            return
        key = name if name.startswith(":") else name.rstrip(":").lower()
        self.send(f"{code} headers follow")
        for number, _, raw in found:
            f = self._overview_fields(number, raw)
            if key.startswith(":"):
                value = f.get(key, "")
            else:
                over = {k.rstrip(":").lower(): v for k, v in f.items() if not k.startswith(":")}
                if key in over and key != "xref:full":
                    value = over[key]
                else:
                    try:
                        value = Article.from_bytes(raw).get(name.rstrip(":"), "") or ""
                    except ArticleError:
                        value = ""
            self.send(f"{number} {self._clean(value)}")
        self.send(".")

    async def cmd_xhdr(self, args):
        await self.cmd_hdr(args, code=221)

    async def cmd_list_headers(self, args):
        self.send("215 headers and metadata items supported")
        self.send(":")
        self.send(".")

    async def cmd_newnews(self, args):
        if len(args) < 3:
            self.send("501 syntax: NEWNEWS wildmat yyyymmdd hhmmss [GMT]")
            return
        try:
            stamp = datetime.strptime(args[1] + args[2], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            self.send("501 bad date")
            return
        store, pattern, since = self.node.store, args[0], int(stamp.timestamp())
        self.send("230 list of new articles follows")
        listed: set[str] = set()
        # UN-RFC 0017: first the state of every matching group, whatever its age, so
        # that a node catching up can accept what follows; then what arrived since.
        # Key-bound groups are not in part 1 (UN-RFC 0040 section 5): their state is
        # reconciled, and what changes still comes in part 2.
        for gid, *_ in store.groups(ordinary=True):
            if wildmat(pattern, gid):
                for msgid in store.state_ids(gid):
                    if msgid not in listed:
                        listed.add(msgid)
                        self.send(msgid)
            await self.writer.drain()
        for msgid, gid in store.received_since(since):
            if msgid not in listed and wildmat(pattern, gid):
                listed.add(msgid)
                self.send(msgid)
        for msgid, gid in store.removals_since(since):
            if wildmat(pattern, gid):
                self.send(msgid)
        self.send(".")

    async def cmd_xun_reconcile(self, args):
        """UN-RFC 0040 section 4.3: compare key-bound state by range fingerprints.

        Open to readers too, so anyone can check a node; a reader gets one exchange
        (MAX_ROUNDS rounds) per connection, an authenticated peer is not limited."""
        try:
            block = await read_block(self.reader, RECONCILE_MAX_BYTES)
        except ValueError:
            self.send("501 reconciliation message too large")
            return
        if not self.peer:
            self._reconcile_rounds += 1
            if self._reconcile_rounds > reconcile.MAX_ROUNDS:
                self.send("400 too many reconciliation rounds; connect again")
                await self.writer.drain()
                raise ConnectionError("reconciliation round limit")
        try:
            ranges = reconcile.parse_message(block.decode("utf-8", "replace").splitlines())
        except (reconcile.ReconcileError, ValueError) as err:
            self.send(f"501 {err}")
            return
        store = self.node.store
        store.kb_sweep()
        lines = reconcile.format_message(reconcile.answer(store, ranges))
        self.send("295 reconcile")
        self.writer.write(dot_stuff("\r\n".join(lines).encode()) if lines else b".\r\n")

    MANIFESTS_PER_MINUTE = 60          # requests from an unauthenticated reader

    async def cmd_xun_manifests(self, args):
        """UN-RFC 0041: the current manifests of up to MANIFESTS_MAX groups at once.

        One answer per line, in order, as ARTICLE/STAT answer: 220 with the article
        as stored (no Path/Xref), 223 if the client holds the current one, 411 if we
        have none, 431 for lines past MANIFESTS_ANSWER_BYTES (section 2.3)."""
        try:
            block = await read_block(self.reader, MANIFESTS_MAX * (MAX_LINE + 2))
        except ValueError:
            self.send(f"501 more than {MANIFESTS_MAX} lines")
            return
        entries: list[tuple[str, str | None]] = []
        for line in block.decode("utf-8", "replace").splitlines():
            parts = line.split()
            if not parts or len(parts) > 2 or (len(parts) == 2 and not (
                    parts[1].startswith("<") and parts[1].endswith(">"))):
                self.send("501 malformed line: <group-id> [<message-id>]")
                return
            entries.append((parts[0], parts[1] if len(parts) == 2 else None))
        if not entries or len(entries) > MANIFESTS_MAX:
            self.send(f"501 between 1 and {MANIFESTS_MAX} lines")
            return
        if len({gid for gid, _ in entries}) != len(entries):
            self.send("501 a Group ID appears twice")
            return
        if not self.peer:
            now = time.monotonic()
            self._manifest_requests = [t for t in self._manifest_requests if now - t < 60]
            if len(self._manifest_requests) >= self.MANIFESTS_PER_MINUTE:
                self.send("400 too many manifest requests; wait a minute")
                return
            self._manifest_requests.append(now)
        store, sent, full = self.node.store, 0, False
        self.send(f"296 {len(entries)} manifests follow")
        for gid, held in entries:
            if full:
                self.send(f"431 {gid}")
                continue
            m = None if store.tombstone(gid) else store.manifest(gid)
            raw = store.get(m.message_id) if m else None
            if raw is None:
                self.send(f"411 {gid}")
            elif held == m.message_id:
                self.send(f"223 0 {m.message_id} {gid}")
            elif sent and sent + len(raw) > MANIFESTS_ANSWER_BYTES:
                full = True
                self.send(f"431 {gid}")
            else:
                sent += len(raw)
                self.send(f"220 0 {m.message_id} {gid}")
                self.writer.write(dot_stuff(raw))
                await self.writer.drain()

    # --- posting ---
    def _try_accept(self, raw: bytes, from_peer: bool = False) -> ArticleError | None:
        try:
            self.node.accept(raw, source=self.peer, from_peer=from_peer)
            return None
        except ArticleError as err:
            log.debug("rejected: %s", err)
            return err

    async def cmd_post(self, args):
        self.send("340 send article")
        await self.writer.drain()
        try:
            raw = await read_block(self.reader, self.node.config.max_size)
        except ValueError:
            self.send("441 size")
            return
        err = self._try_accept(raw)
        self.send("240 article received" if err is None
                  else f"441 {err.reason}{': ' + err.detail if err.detail else ''}")

    def _peer_allowed(self) -> bool:
        if self.node.config.require_peer_auth and not self.peer:
            self.send("480 peer authentication required")
            return False
        return True

    async def cmd_ihave(self, args):
        if not args or not self._peer_allowed():
            return
        if self.node.store.seen(args[0]):
            self.send("435 not wanted")
            return
        self.send("335 send it")
        await self.writer.drain()
        raw = await read_block(self.reader, self.node.config.max_size + 1024)
        err = self._try_accept(raw, from_peer=True)
        self.send("235 transferred" if err is None
                  else "436 try again later" if err.reason == "later" else "437 rejected")

    async def cmd_check(self, args):
        if not args or not self._peer_allowed():
            return
        self.send(f"{438 if self.node.store.seen(args[0]) else 238} {args[0]}")

    async def cmd_takethis(self, args):
        if not args:
            self.send("501 syntax")
            return
        raw = await read_block(self.reader, self.node.config.max_size + 1024)
        if self.node.config.require_peer_auth and not self.peer:
            self.send(f"439 {args[0]}")
            return
        err = self._try_accept(raw, from_peer=True)
        # 431 after TAKETHIS: our peers retry it later (UN-RFC 0005 5.2, UN-RFC 0030 4.1)
        self.send(f"{239 if err is None else 431 if err.reason == 'later' else 439} {args[0]}")
