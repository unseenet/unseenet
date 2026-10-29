"""Key ripening (UN-RFC 0025): a key works for a while, once, before it posts.

Belongs here: the chain in the vault and its published point (``ripe@<fp>``), computing
segments (``ripen_segment``, in a thread or a browser worker through ``_prove_segment``),
taking over a chain published elsewhere, ``ensure_ripe`` before posting, the
``Key-Ripening`` header, what a node asks for (``UNSEENET-MINRIPE``), and the level
private senders must have (section 3.5).

Not here: running ripening in the background (``client.runtime.ClientRuntime``), or
postage itself (posting.py).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class RipeningMixin:
    def _ripening_entry(self, name: str | None = None) -> dict:
        name = name or self.default_identity_name()
        return self.data.setdefault("ripening", {}).setdefault(
            self.identity(name).key_text, {"segments": [], "published": 0})

    def ripening(self, name: str | None = None) -> rp.Chain:
        """The chain this identity has computed so far, in the vault (section 3.2)."""
        return rp.Chain([rp.Segment.from_dict(s) for s in self._ripening_entry(name)["segments"]])

    def ripening_kept_paused(self, name: str | None = None) -> bool:
        """True when the user paused ripening this key on this device, until they resume
        it (#337): kept with the key's chain in this vault, not with your state, so a
        warm phone pausing does not pause the desktop."""
        if not self.has_identity():
            return False
        return bool(self._ripening_entry(name).get("paused"))

    def set_ripening_kept_paused(self, paused: bool, name: str | None = None) -> None:
        """Remember (or forget) that ripening this key is paused on this device, and save;
        the client runtime calls it from ``pause_ripening`` and ``resume_ripening``."""
        if not self.has_identity():
            return
        entry = self._ripening_entry(name)
        if bool(entry.get("paused")) == paused:
            return
        if paused:
            entry["paused"] = True
        else:
            entry.pop("paused", None)
        self.save()

    # --- the level to ripen to on this device (#740) ---
    def ripening_target(self, name: str | None = None) -> int | None:
        """The level this key is ripened to on this device when the user chose one (3 or
        4, #740), else None - the program's own default then (3 for clients). Kept with
        the key's chain like the pause (#337): the work is this machine's, and two
        devices should not both ripen one key."""
        if not self.has_identity():
            return None
        value = self._ripening_entry(name).get("target")
        return value if value in (3, 4) else None

    def set_ripening_target(self, level: int, name: str | None = None) -> None:
        """Ripen this key to ``level`` (3 or 4) on this device (UN-RFC 0025 section 7):
        4 costs weeks of one core while the program runs, and then pays 2 bits less
        postage than 3 (section 4). The client runtime follows it at once."""
        if level not in (3, 4):
            raise SessionError("the level to ripen to is 3 or 4")
        entry = self._ripening_entry(name)
        if entry.get("target") == level:
            return
        entry["target"] = level
        self.save()

    def ripening_speed(self, name: str | None = None) -> float | None:
        """Iterations a second this device proved the key's last segments at, or None."""
        speed = self._ripening_entry(name).get("speed") if self.has_identity() else None
        return float(speed) if isinstance(speed, (int, float)) and speed > 0 else None

    def ripening_seconds_left(self, level: int, name: str | None = None) -> float | None:
        """About how long ripening to ``level`` takes from where the key is, at this
        device's speed (its last segments): None when unknown, 0 when there."""
        target = next((th for lv, th, _ in rp.LEVELS if lv == level), None)
        if target is None or not self.has_identity():
            return None
        left = target - self.ripening(name).t
        if left <= 0:
            return 0.0
        speed = self.ripening_speed(name)
        return left / speed if speed else None

    def _note_speed(self, name: str | None, iterations: int, seconds: float) -> None:
        """Keep how fast this device proves, weighted to the newest segments."""
        if seconds <= 0 or iterations <= 0:
            return
        entry = self._ripening_entry(name)
        now = iterations / seconds
        old = entry.get("speed")
        entry["speed"] = round(now if not isinstance(old, (int, float)) or old <= 0
                               else 0.5 * old + 0.5 * now, 1)

    def ripe_group(self, name: str | None = None) -> str:
        """The Group ID where an identity publishes its ripening chain:
        ``ripe@<fingerprint>`` (UN-RFC 0025)."""
        return make_group_id(rp.GROUP_NAME, self.identity(name).public_key)

    def published_level(self, name: str | None = None) -> int | None:
        """The level nodes know for this identity: the newest point it published."""
        return rp.level(self._ripening_entry(name)["published"])

    def ripening_header(self, name: str | None = None) -> str | None:
        """Key-Ripening for our articles: the newest published point (section 3.4)."""
        entry = self._ripening_entry(name)
        t = entry["published"]
        y = self.ripening(name).points().get(t) if t else None
        return rp.format_header(t, y) if y else None

    async def node_min_ripe(self, node: str | None = None) -> str | None:
        """The node's UNSEENET-MINRIPE: a level, "-", or None for a node that knows
        nothing of ripening (before UN-RFC 0025). Such a node puts Key-Ripening in
        the canonical form, so it must never get the header: the signature would
        not match. Unreachable now: None, so nothing is computed for it."""
        async def minimum(c: Client):
            return c.capability("UNSEENET-MINRIPE")
        try:
            value = await self._call(minimum, node or self.node)
        except (OSError, ConnectionError, SessionError, asyncio.IncompleteReadError):
            return None
        return value.strip() if value else None

    async def node_wants_ripening(self, node: str | None = None) -> bool:
        """Does this node ask for ripening (UNSEENET-MINRIPE other than "-")?"""
        value = await self.node_min_ripe(node)
        return value is not None and value != "-"

    def _with_inner_ripening(self, extra):
        """A private post carries the sender's Key-Ripening inside the sealed box,
        for the recipient only (UN-RFC 0025 section 3.5)."""
        header = self.ripening_header() if self.has_identity() else None
        return list(extra or []) + ([("Key-Ripening", header)] if header else [])

    def private_min_ripe(self) -> int | None:
        """Hide private posts from senders below this level; None shows them all."""
        return self.data.get("private_min_ripe")

    def set_private_min_ripe(self, level: int | None) -> None:
        """The lowest ripening level a sender of private posts must have for you to see
        them (UN-RFC 0025 section 3.5); ``None`` takes everybody."""
        if level is not None:
            rp.parse_min(level)                       # 0-4, or raises
        self.data["private_min_ripe"] = level
        self.save()

    async def sender_level(self, msg: "Message") -> int | None:
        """The level a private post's sender has, checked against the sender's own
        ripe@ chain (UN-RFC 0025 section 3.5); None if unripe or not shown."""
        if not msg.sender_key or not msg.sender_ripening or not rp.available():
            return None
        try:
            t, y = rp.parse_header(msg.sender_ripening)
            pk = crypto.key_from_text(msg.sender_key)
        except (rp.RipeningError, crypto.CryptoError, ValueError):
            return None
        known, done = self._sender_chains.get(msg.sender_key, (None, 0))
        if known is None or known.points().get(t) != y:
            m = await self.fetch_manifest(make_group_id(rp.GROUP_NAME, pk))
            if m is None or "ripening" not in m.raw:
                return None
            try:
                chain = rp.Chain.from_manifest(m.raw["ripening"])
                already = done if known is not None and chain.extends(known) else 0
                done = rp.verify(pk, chain, already=already)
            except rp.RipeningError:
                return None
            self._sender_chains[msg.sender_key] = (chain, done)
            known = chain
        return rp.level(t) if known.points().get(t) == y else None

    async def check_private_senders(self) -> None:
        """Learn the senders' levels for the private posts the setting may hide."""
        if self.private_min_ripe() is None:
            return
        for m in self.cache.get(self.my_inbox, {}).values():
            if m.sender_key and m.message_id not in self._sender_levels:
                try:
                    self._sender_levels[m.message_id] = await self.sender_level(m)
                except (SessionError, OSError, ConnectionError, asyncio.IncompleteReadError):
                    pass                                   # again at the next fetch

    def sender_shown(self, msg: "Message") -> bool:
        """With the setting on, a private post from someone who is not a contact is
        shown only when its sender is known to be ripe enough. A local choice: the
        node knows nothing of it (UN-RFC 0025 sections 3.5, 6)."""
        minimum = self.private_min_ripe()
        if minimum is None or not msg.private or msg.to_key or not msg.sender_key:
            return True
        if self.contact_name(msg.sender_key) or self._identity_named_by(msg.sender_key):
            return True
        return rp.meets(self._sender_levels.get(msg.message_id), minimum)

    async def ripen_segment(self, name: str | None = None, run_file=None) -> bool:
        """Compute this identity's next segment (section 3.2) in a worker thread and
        keep it in the vault. False at the top, or when ``run_file`` was removed.
        True also when the chain grew meanwhile from another caller (posting and
        the background may ask at once): that one's segment is kept, not ours."""
        from .. import machine
        name = name or self.default_identity_name()
        chain = self.ripening(name)

        def fitting() -> int:
            length = rp.fitting_segment_length(chain.t, len(chain.segments),
                                               machine.ripening_budget())
            if not length and rp.next_segment_length(chain.t):   # not the top: this machine's limit
                self.ripening_limit = rp.level(chain.t)
                self.say(f"This machine can ripen this key to level {rp.level(chain.t)}: "
                         f"more needs more memory than it has free (#440).")
            return length

        length = fitting()
        if not length:
            return False
        lock = None
        if rp.memory_for(length) > machine.LOCK_ABOVE:   # a large segment: one at a time
            lock = machine.RipeningLock()
            waited = False
            while not lock.acquire():
                if run_file is not None and not Path(run_file).exists():
                    return False                          # stopped while waiting
                if not waited:
                    self.say("Another program on this machine is ripening a key; waiting.")
                    waited = True
                await asyncio.sleep(15)
            length = fitting()                    # free memory as it is now we hold it (#677)
            if not length:
                lock.release()
                return False
        _s.log.info("ripening %s: a segment of %d iterations from t=%d (about %d MiB)",
                    name, length, chain.t, rp.memory_for(length) >> 20)
        pk = self.identity(name).public_key
        began = time.monotonic()
        try:
            seg = await self._prove_segment(pk, chain.end, length, run_file)
        finally:
            if lock is not None:
                lock.release()
        if seg is None:
            return False
        entry = self._ripening_entry(name)
        if len(entry["segments"]) != len(chain.segments):   # someone else ripened meanwhile
            return self.ripening(name).t > chain.t           # grown all the same (#326)
        entry["segments"].append(seg.to_dict())
        self._note_speed(name, seg.t, time.monotonic() - began)    # for the time left (#740)
        self.save()
        t = chain.t + seg.t
        self.emit(ev.Ripening(self.identity(name).key_text, t, rp.level(t),
                              rp.next_threshold(t)))
        return True

    async def _prove_segment(self, public_key: bytes, start: bytes, t: int,
                             run_file=None) -> "rp.Segment | None":
        """Prove one segment of ``t`` iterations from ``start``: None when stopped
        (``run_file`` removed), and the segment starts again later (section 3.2).

        Here in the ripening thread. A platform without threads overrides this, e.g.
        the browser client, which proves in a Web Worker of its own (unseenet#323)."""
        return await self._in_ripening_thread(
            lambda: rp.prove_segment(public_key, start, t, run_file))

    @staticmethod
    async def _in_ripening_thread(fn):
        """Run one segment in a thread of its own, at low priority where the system
        allows it, so it never holds up postage (UN-RFC 0025, 7). A daemon thread:
        a program that closes is never kept waiting for a segment of hours."""
        import threading
        loop = asyncio.get_running_loop()
        done = loop.create_future()

        def deliver(setter, value) -> None:
            if not done.done():
                setter(value)

        def run() -> None:
            try:
                os.nice(10)             # this thread only, on Linux
            except (AttributeError, OSError):
                pass                    # Windows: no nice
            try:
                result = fn()
                call = (deliver, done.set_result, result)
            except BaseException as exc:  # noqa: BLE001 - handed to the waiting task
                call = (deliver, done.set_exception, exc)
            try:
                loop.call_soon_threadsafe(*call)
            except RuntimeError:        # the loop is gone: the program has closed
                pass
        threading.Thread(target=run, name="ripening", daemon=True).start()
        return await done

    async def adopt_published_ripening(self, name: str | None = None,
                                       node: str | None = None) -> bool:
        """Take over this identity's chain from its own ``ripe@`` group when that is
        further than the one kept here: the same key on another machine, a vault copy,
        a service reinstalled, a CI key ripened once elsewhere (UN-RFC 0025 section 3.3).
        The chain is checked first. True when it was taken over."""
        name = name or self.default_identity_name()
        pk = self.identity(name).public_key
        if not rp.available():
            return False
        try:
            m = await self.fetch_manifest(make_group_id(rp.GROUP_NAME, pk), node)
        except (SessionError, OSError, ConnectionError, asyncio.IncompleteReadError):
            return False
        if m is None or "ripening" not in m.raw:
            return False
        try:
            chain = rp.Chain.from_manifest(m.raw["ripening"])
            if chain.t <= self.ripening(name).t:
                return False
            rp.verify(pk, chain)
        except rp.RipeningError:
            return False
        entry = self._ripening_entry(name)
        entry["segments"] = [s.to_dict() for s in chain.segments]
        entry["published"] = chain.t
        self.save()
        self.emit(ev.Ripening(self.identity(name).key_text, chain.t, rp.level(chain.t),
                              rp.next_threshold(chain.t)))
        return True

    async def ensure_ripe(self, name: str | None = None, node: str | None = None) -> None:
        """Before posting: ripen to level 0 if needed, and publish ripe@ when its chain
        has reached a level nodes don't know yet (sections 3.3, 7). ``node``: publish
        there (the node about to be posted to); otherwise to all our nodes."""
        name = name or self.default_identity_name()
        lock = self._ripe_locks.setdefault(name, asyncio.Lock())
        async with lock:
            if not rp.available():
                return                     # a node that requires ripening will say so
            if self.ripening(name).level is None:      # ripened elsewhere already?
                await self.adopt_published_ripening(name, node)
            while self.ripening(name).level is None:
                self.say("Ripening your key: a new key takes a few minutes before it can post")
                if not await self.ripen_segment(name):
                    raise SessionError("ripening stopped before the key could post")
            if rp.level(self.ripening(name).t) != self.published_level(name):
                await self.publish_ripening(name, node)

    async def publish_ripening(self, name: str | None = None, node: str | None = None) -> None:
        """Post this identity's ripe@ manifest with its whole chain (section 3.3)."""
        name = name or self.default_identity_name()
        chain = self.ripening(name)
        if not chain.segments:
            return
        owner = self.identity(name)
        gid = self.ripe_group(name)
        entry = self.group_entry(gid)
        data = {"v": 1, "name": rp.GROUP_NAME, "type": "channel", "owner": owner.key_text,
                "serial": int(self.manifest_data(gid).get("serial", 0)) + 1, "min_pow": 0,
                "retention_days": 7, "view": "data", "ripening": chain.to_manifest()}
        targets = [node] if node else self.nodes or [self.node]
        bits = await self._ripe_pow(chain, next((t for t in targets if t), None))
        art = await self._compute(lambda: manifest_article(owner, gid, data, bits))
        art.set("Key-Ripening", chain.header())
        sent, problems = 0, []
        for target in targets:                                           # every node of ours
            if await self.node_min_ripe(target) is None:
                continue                   # knows nothing of ripening (or down): not for it
            try:
                await self._send_article(art, target)
                sent += 1
            except SessionError as exc:
                if "duplicate" in str(exc):
                    sent += 1
                else:
                    problems.append(exc)
            except (OSError, ConnectionError, asyncio.IncompleteReadError) as exc:
                problems.append(exc)       # down now: it gets the chain when it asks (3.4)
        if not sent and not problems:
            return                         # no node of ours knows ripening yet
        if not sent:
            raise problems[0] if isinstance(problems[0], SessionError) \
                else SessionError(f"could not publish your ripening: {problems[0]}")
        entry.update({"type": "channel", "owner": True, "manifest": data,
                      "node": entry.get("node") or self.node})
        self._ripening_entry(name)["published"] = chain.t
        self.save()

    async def _ripe_pow(self, chain: rp.Chain, node: str | None) -> int:
        """Postage for a ripe@ manifest: that node's minimum with the chain's own level."""
        async def minimum(c: Client) -> int:
            value = c.capability("UNSEENET-MINPOW")
            return int(value) if value and value.strip().isdigit() else _s.DEFAULT_POW
        try:
            node_pow = await self._call(minimum, node)
        except (OSError, ConnectionError, SessionError, asyncio.IncompleteReadError):
            node_pow = _s.DEFAULT_POW
        return rp.required_pow(node_pow, 0, chain.level, allow_unripe=True)
