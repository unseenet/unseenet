"""Key ripening (UN-RFC 0025). Part of Session (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time


class RipeningMixin:
    # --- key ripening (UN-RFC 0025) ---
    def _identity_named_by(self, key) -> str | None:
        """The name of our identity with this public key (bytes or text), if it is ours."""
        try:
            text = key if isinstance(key, str) else crypto.key_to_text(key)
        except (crypto.CryptoError, TypeError, ValueError):
            return None
        for name in self.data["identities"]:
            if self.identity(name).key_text == text:
                return name
        return None

    def _ripening_entry(self, name: str | None = None) -> dict:
        name = name or self.default_identity_name()
        return self.data.setdefault("ripening", {}).setdefault(
            self.identity(name).key_text, {"segments": [], "published": 0})

    def ripening(self, name: str | None = None) -> rp.Chain:
        """The chain this identity has computed so far, in the vault (section 3.2)."""
        return rp.Chain([rp.Segment.from_dict(s) for s in self._ripening_entry(name)["segments"]])

    def ripe_group(self, name: str | None = None) -> str:
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
        name = name or self.default_identity_name()
        chain = self.ripening(name)
        length = rp.next_segment_length(chain.t)
        if not length:
            return False
        pk = self.identity(name).public_key
        seg = await self._prove_segment(pk, chain.end, length, run_file)
        if seg is None:
            return False
        entry = self._ripening_entry(name)
        if len(entry["segments"]) != len(chain.segments):   # someone else ripened meanwhile
            return self.ripening(name).t > chain.t           # grown all the same (#326)
        entry["segments"].append(seg.to_dict())
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

    def default_identity_name(self) -> str:
        ids = self.data["identities"]
        if not ids:
            raise SessionError("no identity yet")
        name = self._acting_as or self.data.get("default_identity")
        return name if name in ids else next(iter(ids))

    def act_as(self, name: str | None) -> None:
        """Use the identity ``name`` for this run, without changing the vault's
        default (a command-line client's -i)."""
        if name is not None and name not in self.data["identities"]:
            raise SessionError(f"no identity {name!r} in this vault")
        self._acting_as = name

    def identity(self, name: str | None = None) -> crypto.Identity:
        entry = self.data["identities"][name or self.default_identity_name()]
        return crypto.Identity.from_seed(bytes.fromhex(entry["seed"]))

    def my_fingerprints(self) -> tuple[str, ...]:
        """The fingerprints of all your identities (owner:me in a group search, #13)."""
        return tuple(crypto.fingerprint(crypto.Identity.from_seed(bytes.fromhex(e["seed"])).public_key)
                     for e in self.data["identities"].values())

    def filter_groups(self, groups: list["GroupInfo"], query: str,
                      known: dict | None = None) -> list["GroupInfo"]:
        """The groups that match a search (#13, ``client.groupfilter``), locally.
        ``known``: manifest data fetched for groups you do not follow."""
        from .. import groupfilter
        f = groupfilter.parse(query)
        if not f:
            return list(groups)
        mine, known = self.my_fingerprints(), known or {}
        return [g for g in groups if groupfilter.matches(
            f, g.group_id, description=g.description, gtype=g.type,
            data=known.get(g.group_id) or self.manifest_data(g.group_id),
            subscribed=g.subscribed, my_fingerprints=mine)]

    async def group_manifests(self, groups: list["GroupInfo"], known: dict) -> int:
        """Fetch the manifests of listed groups whose type is not known yet, from the
        node that carries each, in a few requests (UN-RFC 0041), into ``known``
        (Group ID -> manifest data) and each GroupInfo's type. Asking for all of them
        tells a node nothing about what you search for. Returns how many were asked."""
        todo: dict[str | None, list[GroupInfo]] = {}
        for g in groups:
            if g.type or g.group_id in known or self.manifest_data(g.group_id):
                continue
            todo.setdefault(g.nodes[0] if g.nodes else None, []).append(g)
        asked = 0
        for node, items in todo.items():
            found = await self.fetch_manifests([g.group_id for g in items], node,
                                               fallback=False)
            for g in items:
                m = found.get(g.group_id)
                known[g.group_id] = dict(m.raw) if m else {}
                if m:
                    g.type = m.type
            asked += len(items)
        return asked

    def display_name(self, name: str | None = None) -> str:
        return self.data["identities"][name or self.default_identity_name()]["display"]

    def signature_template(self, name: str | None = None) -> str:
        # no "signature" yet: the default; one set to "" by the user: none
        return self.data["identities"][name or self.default_identity_name()].get(
            "signature", DEFAULT_SIGNATURE)

    def set_signature(self, template: str, name: str | None = None) -> None:
        lines = template.strip("\n").split("\n") if template.strip() else []
        if len(lines) > MAX_SIG_LINES:
            raise SessionError(f"a signature has at most {MAX_SIG_LINES} lines")
        self.data["identities"][name or self.default_identity_name()]["signature"] = "\n".join(lines)
        self.save()

    def signature(self, name: str | None = None) -> str:
        """The signature with {name}, {key} and {fp} filled in ('' if none)."""
        template = self.signature_template(name)
        if not template:
            return ""
        ident = self.identity(name)
        for placeholder, value in (("{name}", self.display_name(name)), ("{key}", ident.key_text),
                                   ("{fp}", ident.fingerprint[:4])):
            template = template.replace(placeholder, value)
        return template

    def new_identity(self, name: str, display: str | None = None) -> crypto.Identity:
        ident = crypto.Identity.generate()
        self.data["identities"][name] = {"seed": ident.seed.hex(), "display": display or name,
                                         "signature": DEFAULT_SIGNATURE}
        self.data.setdefault("default_identity", name)
        self.save()
        return ident
