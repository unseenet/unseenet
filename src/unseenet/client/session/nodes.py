"""Nodes and the connection to them: where the network is reached.

Belongs here: the nodes the user has (``add_node``, ``node_for`` - the node a group is
read on), the known-node list and releases from the project's channels (UN-RFC 0010,
0020), the one connection per node over Tor with retries and backoff (``_connect``,
``_call``), push (``watch``, UN-RFC 0008), Tor and bridges (``set_tor``,
``set_bridges``), a node's information (UN-RFC 0011), and ``close``.

Not here: what is read from a node (reading.py, groups.py) or posted to it (posting.py).
"""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import session as _s   # names tests patch on the module, read at call time

# A node that has failed this long (no connection opened in between) is taken to be gone
# (#603, #605): longer than a node's restart, short enough that nobody waits long.
NODE_GIVE_UP = 120.0


class NodesMixin:
    # ------------------------------------------------------------------
    # nodes: your identity is in the vault, so it is the same on every node.
    # Each group is read from one node (article numbers are per node); new
    # groups and your inbox go to the default node, the first in the list.
    # ------------------------------------------------------------------
    def add_node(self, address: str, default: bool = False) -> None:
        """Add a node address (``xyz.onion`` or ``host:port``) to the vault. ``default``
        puts it first, so new groups and your inbox go there; an address already known
        only moves. A node added on purpose is tried at once, whatever its backoff."""
        address = address.strip()
        if not address:
            raise SessionError("no address given")
        self.reset_backoff(address)        # chosen on purpose: try it at once
        nodes = self.data["nodes"]
        if address in nodes:
            if not default:
                return
            nodes.remove(address)
        if default or not nodes:
            nodes.insert(0, address)
        else:
            nodes.append(address)
        self.save()

    def remove_node(self, address: str) -> list[str]:
        """Stop using a node. Returns the followed groups that were read from it.

        They are no longer bound to any node: the next read looks for them on your
        other nodes, default first, and keeps the one that carries each (``fetch_group``)
        - never moved blindly to a node that does not carry them (#603). A group nobody
        else carries shows as not reachable. ``rehome_groups`` does the looking at once,
        and says which groups no node of yours carries."""
        nodes = self.data["nodes"]
        if address not in nodes:
            return []
        if len(nodes) == 1:
            raise SessionError("you need at least one node")
        nodes.remove(address)
        (self.data.get("node_names") or {}).pop(address, None)
        moved = [gid for gid, e in self.data["groups"].items() if e.get("node") == address]
        for gid in moved:
            self._forget_numbers(gid)
            self.data["groups"][gid]["node"] = None
        client = self._clients.pop(address, None)
        if client is not None:
            client.writer.close()
        self.save()
        self.save_offline()
        return [g for g in moved if g in self.data["subscribed"]]

    @property
    def nodes(self) -> list[str]:
        """The vault's node addresses, the default first."""
        return list(self.data["nodes"])

    @property
    def node(self) -> str | None:
        """The default node: new groups and your inbox live here."""
        return self.data["nodes"][0] if self.data["nodes"] else None

    def node_for(self, group_id: str | None) -> str | None:
        """The node a group is read from and posted to."""
        if group_id:
            address = self.data["groups"].get(group_id, {}).get("node")
            if address in self.data["nodes"]:
                return address
        return self.node

    def pin_group(self, group_id: str, address: str) -> None:
        """Read a group from ``address`` from now on."""
        if address not in self.data["nodes"]:
            raise SessionError(f"{address} is not one of your nodes")
        entry = self.group_entry(group_id)
        if entry.get("node") != address:
            if entry.get("node") is not None:
                self._forget_numbers(group_id)
            entry["node"] = address
            self.save()

    # --- when nodes are gone (#603, #604, #605) ------------------------------------
    # Every followed group keeps its own node, whatever the default is, and is only ever
    # moved to a node that carries it - a group only an unlisted node carries (a local
    # node, an association's own) stays with it and is read again when it comes back.
    async def carried_by(self, address: str) -> set[str] | None:
        """The Group IDs ``address`` carries, or None when it does not answer."""
        async def run(c: Client) -> set[str]:
            lines = await c.multiline("LIST NEWSGROUPS *", 215)
            return {line.partition("\t")[0] for line in lines}
        try:
            return await self._call(run, address)
        except (OSError, ConnectionError, SessionError, NNTPError, asyncio.IncompleteReadError,
                asyncio.TimeoutError):
            return None

    def down_for(self, address: str | None) -> float:
        """Seconds ``address`` has failed without a connection opening in between (0: up)."""
        since = self._down_since.get(address or "")
        return 0.0 if since is None else time.monotonic() - since

    def _move_groups(self, to: str, carried: set[str], away_from) -> list[str]:
        """Read the groups of the nodes ``away_from`` from ``to``, where it carries them;
        your own inbox goes along in any case (``ensure_inbox`` makes it there). Returns
        the Group IDs moved."""
        away_from, moved = set(away_from), []
        inbox = self.my_inbox if self.has_identity() else None
        for gid, entry in list(self.data["groups"].items()):
            if entry.get("node") not in away_from and entry.get("node") is not None:
                continue
            if gid in carried:
                self.pin_group(gid, to)
                moved.append(gid)
            elif gid == inbox:
                self.pin_group(gid, to)
                entry["check_exists"] = True        # not there yet: ensure_inbox makes it
                moved.append(gid)
        return moved

    async def rehome_groups(self, group_ids=None) -> dict:
        """Find a node of yours for groups without one (after ``remove_node``), asking
        your nodes what they carry: the default first. ``{"moved": {gid: node},
        "unavailable": [gid]}`` - unavailable: no node of yours carries it."""
        todo = [g for g in (group_ids if group_ids is not None else self.data["subscribed"])
                if self.data["groups"].get(g, {}).get("node") not in self.data["nodes"]]
        out: dict = {"moved": {}, "unavailable": []}
        if not todo:
            return out
        carried = {}
        for n in self.nodes:
            got = await self.carried_by(n)
            if got is not None:
                carried[n] = got
        for gid in todo:
            home = next((n for n in self.nodes if gid in carried.get(n, ())), None)
            if home is None:
                out["unavailable"].append(gid)
            else:
                self.pin_group(gid, home)
                out["moved"][gid] = home
        return out

    async def fall_back_to_known_node(self) -> str | None:
        """None of your nodes answers (#603): take a random node from the newest signed
        known-node list (UN-RFC 0010 section 5) that does - or else an announced node whose
        key checks out (UN-RFC 0055 section 7) - make it your default, and read the groups
        there that it carries; your inbox goes along. Never a node learned from an article
        or a page. Returns its address, or None when none answers."""
        previous = self.node
        dead = list(self.nodes)
        candidates = [n.address for n in self.known_nodes() if n.address not in dead]
        random.shuffle(candidates)
        listed = set(candidates)
        announced = [e for e in self.announced_nodes()          # then announced ones, each
                     if e["address"] not in dead and e["address"] not in listed]  # checked
        random.shuffle(announced)
        candidates += [e["address"] for e in announced]
        keys = {e["address"]: e["key"] for e in announced}
        for address in candidates:
            if address in keys and not await self.check_announced(keys[address]):
                continue                                  # not the node it says (0055 5.3)
            carried = await self.carried_by(address)
            if carried is None:
                continue
            self.add_node(address, default=True)
            self._move_groups(address, carried, dead)
            self.save()
            self.say(f"{self.node_label(previous)} does not answer - "
                     f"you now use {self.node_label(address)}")
            self.emit(ev.DefaultNodeChanged(address, previous, "fallback"))
            return address
        return None

    async def promote_default(self, give_up: float | None = None) -> str | None:
        """The default node has failed for ``give_up`` seconds while another of your
        nodes answers (#605): make that one the default, so new groups and your inbox go
        there. The groups keep their own nodes. Returns the new default, or None."""
        give_up = NODE_GIVE_UP if give_up is None else give_up
        previous = self.node
        if previous is None or self.down_for(previous) < give_up:
            return None
        for address in self.nodes[1:]:
            if self.down_for(address) > 0 or address in self.slow:
                continue
            if await self.carried_by(address) is None:
                continue
            self.add_node(address, default=True)
            self.say(f"{self.node_label(previous)} does not answer - new groups and your "
                     f"inbox now go to {self.node_label(address)}")
            self.emit(ev.DefaultNodeChanged(address, previous, "default-down"))
            return address
        return None

    def _answering_first(self, preferred: str | None) -> list[str]:
        """Your nodes to try for something, ``preferred`` first, then those not failing."""
        rest = [n for n in self.nodes if n != preferred]
        rest.sort(key=lambda n: self.down_for(n) > 0)
        return ([preferred] if preferred else []) + rest

    # --- announced nodes (UN-RFC 0055 sections 5 and 7) -----------------------------
    # Nodes announce themselves in a group every node carries. An announcement is only
    # the node's own word: before a node is offered or used, the client connects to its
    # address and checks that the node there has the announcing key (section 5.3).
    async def refresh_announced_nodes(self) -> list[dict]:
        """Read the nodes' announcements from your default node and keep the newest per
        node that is not stale. Returns them as ``announced_nodes`` does."""
        from ...core import announcements as an
        from ...known_nodes import NODES_ANNOUNCE_GROUP
        messages = await self.fetch_group(NODES_ANNOUNCE_GROUP)
        found = []
        for m in messages:
            if not (m.readable and m.author_key and m.date):
                continue
            try:
                found.append(an.parse(m.body, key=m.author_key, date=m.date,
                                      message_id=m.message_id))
            except an.AnnouncementProblem:
                continue
        now = datetime.now(timezone.utc)
        kept = self.data.setdefault("announced", {})
        newest = an.newest(found, now)
        from ...core import transport
        for key, a in newest.items():
            usable = transport.usable([a.address, *a.addresses])   # UN-RFC 0064: onion: first
            if not usable:
                continue                                  # no address this client can use
            old = kept.get(key, {})
            entry = {"address": usable[0].plain(), "addresses": [u.plain() for u in usable[1:]],
                     "name": a.name,
                     "carries": a.carries, "date": a.date.isoformat(),
                     "operator": a.operator, "contact": a.contact}
            if old.get("address") == entry["address"]:   # the check holds for this address
                entry.update({k: old[k] for k in ("checked", "checked_at") if k in old})
            kept[key] = entry
        for key in [k for k, e in kept.items()
                    if k not in newest and now - datetime.fromisoformat(e["date"]) > an.STALE]:
            del kept[key]                                  # stale and not renewed
        self.save()
        return self.announced_nodes()

    def announced_nodes(self) -> list[dict]:
        """The announced nodes this client knows, newest first: ``key``, ``address``,
        ``name``, ``carries`` (the node's own word), ``checked`` (True: the node at that
        address has that key; False: it has not; None: not checked yet)."""
        out = [{"key": k, "checked": e.get("checked"), **{x: e[x] for x in
               ("address", "addresses", "name", "carries", "date", "operator", "contact")}}
               for k, e in self.data.get("announced", {}).items()]
        return sorted(out, key=lambda e: e["date"], reverse=True)

    async def check_announced(self, key: str) -> bool:
        """Section 5.3: connect to the announced address and compare the node key it
        gives with the announcing key. Kept for the address; False when it differs or
        the node does not answer (then not kept: it may answer later)."""
        entry = self.data.get("announced", {}).get(key)
        if entry is None:
            return False
        try:
            info = await self.node_info(entry["address"])
        except (OSError, ConnectionError, SessionError, NNTPError, asyncio.IncompleteReadError,
                asyncio.TimeoutError, ValueError):
            return False
        entry["checked"] = info.get("node_key") == key
        entry["checked_at"] = datetime.now(timezone.utc).isoformat()
        self.save()
        return entry["checked"]

    def carrying_nodes(self, group_id: str) -> dict:
        """Section 7, coverage: of the announced nodes this client knows, those whose
        ``carries`` covers ``group_id`` - ``{"nodes": n, "checked": n, "addresses": [...]}``.
        It is information, not a warning; one node is worth saying plainly."""
        from ...core import carrying as ca
        network = ca.network_groups()
        hits = [e for e in self.announced_nodes()
                if ca.carries(group_id, ca.read_carries({"carries": e["carries"]}), network)]
        return {"nodes": len(hits), "checked": sum(1 for e in hits if e["checked"]),
                "addresses": [e["address"] for e in hits]}

    # --- names of nodes (#518) -------------------------------------------------
    # The signed known-node list (UN-RFC 0010) is trusted; a node's own name (UN-RFC
    # 0011) is not - anyone can call a node "unseenet-node1" - so it is marked as the
    # node's own claim. Without either, the start of the onion address.
    def _known_node(self, address: str):
        host = address.strip().split(":")[0].lower()
        for n in self.known_nodes():
            if n.address.strip().split(":")[0].lower() == host:
                return n
        return None

    def node_name(self, address: str) -> tuple[str | None, str]:
        """``(name, source)`` of a node: source ``known`` (the signed node list),
        ``self`` (the node's own name, not checked) or ``none``."""
        known = self._known_node(address)
        if known is not None and known.name:
            return known.name, "known"
        own = (self.data.get("node_names") or {}).get(address)
        if own:
            return own, "self"
        return None, "none"

    def node_label(self, address: str | None) -> str:
        """How a node is shown in one line: its listed name; its own name marked
        ``(unlisted)``; else the start of its onion address."""
        if not address:
            return ""
        name, source = self.node_name(address)
        if source == "known":
            return name
        if source == "self":
            return f"{name} (unlisted)"
        return short_node(address)

    def node_entry(self, address: str) -> dict:
        """One node for a front end: name, where it is from, label, the full address."""
        name, source = self.node_name(address)
        known = self._known_node(address)
        return {"address": address, "name": name, "source": source,
                "label": self.node_label(address),
                "description": known.description if known is not None else "",
                "operator": known.operator if known is not None else "",
                "default": address == self.node}

    def node_entries(self) -> list[dict]:
        """Your nodes, the default first, each with how many followed groups it serves."""
        out = []
        for address in self.nodes:
            e = self.node_entry(address)
            e["groups"] = sum(1 for g in self.data["subscribed"] if self.node_for(g) == address)
            out.append(e)
        return out

    def _keep_node_name(self, address: str, info: dict) -> None:
        """Keep a node's own name from its node information, cleaned, in the vault."""
        name = clean_node_name(info.get("name") if isinstance(info, dict) else None)
        names = self.data.setdefault("node_names", {})
        if name and names.get(address) != name:
            names[address] = name
            self.save()

    async def _learn_node_name(self, client: Client, address: str) -> None:
        """While connecting: a node not on the known list tells its name, once a run.

        A full node's 400 and a broken connection go to ``_connect`` as any other
        failure; an answer that is not a name is only no name."""
        tried = self.__dict__.setdefault("_names_asked", set())
        if (address in tried or self._known_node(address) is not None
                or address in (self.data.get("node_names") or {})
                or client.capability("UNSEENET-NODEINFO") is None):
            return
        tried.add(address)
        try:
            lines = await client.multiline("LIST UNSEENET.NODEINFO", 215)
        except NNTPError as exc:
            if exc.code == 400:             # full: refused like any other command
                raise
            return
        try:
            self._keep_node_name(address, json.loads(lines[0]) if lines else {})
        except ValueError:
            pass

    # --- the known nodes (UN-RFC 0010) ---
    def known_nodes(self) -> list:
        """The newest node list this client has: read from the network, else built in."""
        from ...known_nodes import KNOWN_NODES, KnownNode
        cached = self.data.get("known_nodes")
        if cached and cached.get("nodes"):
            return [KnownNode(**n) for n in cached["nodes"]]
        return list(KNOWN_NODES)

    async def refresh_known_nodes(self) -> bool:
        """Read the newest signed node list from the project's channel. True if it changed.

        The group ID carries the project key's fingerprint, its manifest is
        signed by that key, and only the owner and the manifest's posters may
        post: the node enforces that, and we check it again here.
        """
        from dataclasses import asdict
        from ...known_nodes import NODES_GROUP, PROJECT_KEY, parse_node_list
        subscribed = NODES_GROUP in self.data["subscribed"]
        try:
            messages = await self.fetch_group(NODES_GROUP)
        finally:
            if not subscribed:          # read it, but do not keep it around
                self.cache.pop(NODES_GROUP, None)
                self._raw.pop(NODES_GROUP, None)
                self._high.pop(NODES_GROUP, None)
        manifest = self.manifest_data(NODES_GROUP)
        if manifest.get("owner") != PROJECT_KEY:
            return False
        allowed = {PROJECT_KEY, *manifest.get("posters", [])}
        best = None
        for m in messages:
            if not m.readable or m.author_key not in allowed:
                continue
            try:
                updated, nodes = parse_node_list(m.body)
            except ValueError:
                continue
            if best is None or (m.date and (best[0] is None or m.date > best[0])):
                best = (m.date, updated, nodes)
        if best is None:
            return False
        new = {"updated": best[1], "nodes": [asdict(n) for n in best[2]]}
        if self.data.get("known_nodes") == new:
            return False
        self.data["known_nodes"] = new
        self.save()
        return True

    async def refresh_releases(self) -> dict | None:
        """Read the newest signed releases from unseenet.releases (#264) and return
        update_offer(). The posts only carry a release's checksums and their
        signature; the signature is checked against the keys the channel trusts
        (unseenet.update), whoever posted it."""
        from ... import update
        from ...known_nodes import RELEASES_GROUP
        subscribed = RELEASES_GROUP in self.data["subscribed"]
        try:
            messages = await self.fetch_group(RELEASES_GROUP)
        finally:
            if not subscribed:          # read it, but do not keep it around
                self.cache.pop(RELEASES_GROUP, None)
                self._raw.pop(RELEASES_GROUP, None)
                self._high.pop(RELEASES_GROUP, None)
        best = dict(self.data.get("releases") or {})
        for m in messages:
            post = update.parse_release_post(m.body) if m.readable else None
            if not post:
                continue
            channel, sums, sig = post
            try:
                update.check_signature(sums, sig, channel)
            except update.UpdateError:
                continue
            versions = [a.group("version") for a in map(update.ASSET.match, update.parse_sums(sums)) if a]
            if not versions:
                continue
            version = versions[0]
            if channel not in best or update.version_key(version) > update.version_key(best[channel]["version"]):
                best[channel] = {"version": version}
        if best != self.data.get("releases"):
            self.data["releases"] = best
            self.save()
        return self.update_offer()

    def update_offer(self) -> dict | None:
        """A signed release newer than this program, on its channel (a development
        build follows development builds): {"version", "channel"}, or None."""
        from ... import __version__, update
        channel = "dev" if ".dev" in __version__ else "stable"
        found = (self.data.get("releases") or {}).get(channel)
        if found and update.version_key(found["version"]) > update.version_key(__version__):
            return {"version": found["version"], "channel": channel}
        return None

    def _forget_numbers(self, group_id: str) -> None:
        """Article numbers belong to one node: drop them when a group moves."""
        for store in (self.cache, self._raw, self._high):
            store.pop(group_id, None)
        self.data["groups"].get(group_id, {}).pop("closed", None)   # numbers of the old node
        (self.data.get("read_high") or {}).pop(group_id, None)       # ... and how far (#735)

    # ------------------------------------------------------------------
    # connection (one persistent connection; Tor circuits are slow to build)
    # ------------------------------------------------------------------
    def retry_in(self, address: str) -> float:
        """Seconds until ``address`` is tried again after it failed or refused (0: now)."""
        return max(0.0, self._retry_at.get(address, 0.0) - time.monotonic())

    def reset_backoff(self, address: str | None = None) -> None:
        """Try again at once: after the user chose a node or entrance on purpose."""
        for a in ([address] if address else list(self._retry_at)):
            self._retry_at.pop(a, None)
            self._backoff.pop(a, None)

    def _failed(self, address: str) -> float:
        self._down_since.setdefault(address, time.monotonic())
        wait = self._backoff.setdefault(address, Backoff()).next()
        self._retry_at[address] = time.monotonic() + wait
        return wait

    async def _connect(self, address: str | None = None, quiet: bool = False) -> Client:
        address = address or self.node
        if not address:
            raise SessionError("no node configured")
        wait = self.retry_in(address)
        if wait > 0:                       # it just failed: not again before its time (#297)
            raise ConnectionError(f"{address} could not be reached; trying again in "
                                  f"{wait:.0f} s")
        status = (lambda *_, **__: None) if quiet else self.say
        socks = None
        if address.split(":")[0].endswith(".onion"):
            socks = await self._ensure_tor(status)
        status(f"Connecting to {self.node_label(address)} ...")
        try:
            client = await Client.connect(address, socks)
            await client.fetch_capabilities()
            await self._learn_node_name(client, address)
        except (OSError, ConnectionError, NNTPError, asyncio.TimeoutError) as exc:
            wait = self._failed(address)
            self.emit(ev.NodeState(address, False, str(exc) or type(exc).__name__))
            if isinstance(exc, NNTPError) and exc.code == 400:    # full, at the greeting too
                raise SessionError(f"{address} is full; trying again in {wait:.0f} s, "
                                   "or another node") from exc
            raise
        self._backoff.setdefault(address, Backoff()).up()
        self._retry_at.pop(address, None)
        self._down_since.pop(address, None)
        self.emit(ev.NodeState(address, True))
        status(f"Connected to {self.node_label(address)}", idle=True)
        return client

    async def _ensure_tor(self, status) -> int | Socks:
        """Our Tor's SOCKS port, starting Tor first if it is not running.

        Or a Tor that is already running (Tails, ``UNSEENET_TOR_SOCKS``, the
        ``tor.socks`` setting): then we start nothing and only check it answers.

        Several connections (each node, the watch connections) start at once. Without
        the lock each started its own Tor on the same data directory: the extra ones
        died ("another Tor process is running"), but first overwrote the control-port
        file, so a client could end up talking to a Tor that was gone.
        """
        async with self._tor_lock:
            try:
                existing = existing_tor(self.data.get("tor"))
            except TorError as exc:
                raise SessionError(str(exc)) from exc
            if existing is not None:
                if existing != self._checked_socks:
                    status(f"Using the Tor at {existing} ({existing.source}) ...")
                    try:
                        await check_socks(existing)
                    except TorError as exc:
                        raise SessionError(f"{exc}. Start that Tor, or let Unseenet start "
                                           "its own (Ctrl+P: Tor).") from exc
                    self._checked_socks = existing
                return existing
            if self.tor is not None and not self.tor.alive():
                await self.tor.stop()
                self.tor = None
            if self.tor is None:
                tor_dir = self.vault.path.resolve().parent / "unseenet-tor"
                try:
                    binary = _s.TorProcess.find_binary()
                except TorError as exc:
                    raise SessionError(str(exc)) from exc
                try:
                    bridges = bridges_for(self.data.get("tor"), binary)
                except TorError as exc:
                    raise SessionError(f"Tor bridges: {exc}") from exc
                tor = _s.TorProcess(tor_dir, binary, bridges=bridges)
                status("Starting Tor" + (" with bridges" if bridges else "") + " ...")
                try:
                    await tor.start(progress=lambda p, s: self.emit(ev.TorState(p, s)))
                except TorError as exc:
                    await tor.stop()
                    hint = ("" if bridges else
                            " If this network blocks Tor, try bridges (Ctrl+P: Tor bridges).")
                    raise SessionError(f"{exc}.{hint}") from exc
                self.tor = tor
            return self.tor.socks_port

    async def watch(self, on_new, pattern: str = "*", node: str | None = None) -> bool:
        """Listen for new articles (UN-RFC 0008) on a second connection.

        Calls ``on_new(group_id, message_id)`` for each one. Returns False at once if the
        node cannot push; otherwise runs until the connection fails (raises).
        Watching "*" tells the node nothing about which groups you follow.
        """
        client = await self._connect(node, quiet=True)
        try:
            if client.capability("UNSEENET-WATCH") is None:
                return False
            await client.command(f"XUN-WATCH {pattern}", (290,))
            while True:
                line = await client.reader.readline()
                if not line:
                    raise ConnectionError("node closed the watch connection")
                parts = line.decode("utf-8", "replace").split()
                if parts and parts[0] == "291" and len(parts) >= 4:
                    await on_new(parts[1], parts[3])
        finally:
            client.writer.close()

    async def _call(self, fn, node: str | None = None):
        """Run ``fn(client)`` on a node (default: the default node), with one
        reconnect attempt on a broken connection."""
        address = node or self.node
        if not address:
            raise SessionError("no node configured")
        late = self.slow.get(address)
        if late is not None and not late.done():     # asked, not answered yet (#704): no
            raise SessionError(                      # one else waits behind it
                f"{self.node_label(address)} is not answering yet")
        async with self._locks.setdefault(address, asyncio.Lock()):
            for attempt in (1, 2):
                if address not in self._clients:
                    self._clients[address] = await self._connect(address)
                client = self._clients[address]
                try:
                    return await fn(client)
                except (ConnectionError, OSError, asyncio.IncompleteReadError):
                    self._drop(address, client)
                    self._backoff.setdefault(address, Backoff()).down()
                    if attempt == 2:
                        raise
                except NNTPError as exc:
                    if exc.code == 400:     # full (UN-RFC 0005 section 6): it closes; back off
                        self._drop(address, client)
                        wait = self._failed(address)
                        self.emit(ev.NodeState(address, False, str(exc)))
                        raise SessionError(f"{address} is full; trying again in {wait:.0f} s, "
                                           "or another node") from exc
                    raise                   # a complete answer: the connection is fine
                except SessionError:
                    raise
                except BaseException:
                    # Interrupted half-way (cancelled, timed out, a bug): the rest of
                    # an answer may still be on its way, and the next command would
                    # read it as its own. Never reuse such a connection.
                    self._drop(address, client)
                    raise

    def _drop(self, address: str, client: Client) -> None:
        if self._clients.get(address) is client:
            del self._clients[address]
        try:
            client.writer.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Tor bridges, for networks that block Tor
    # ------------------------------------------------------------------
    def bridge_setting(self) -> dict:
        """The Tor bridge setting as stored: ``{"mode": "off"}``, or the mode and the
        bridges the user gave (see ``set_bridges``)."""
        return dict(self.data.get("tor") or {"mode": "off"})

    def tor_in_use(self) -> Socks | None:
        """The running Tor this session uses, or None when it starts its own."""
        try:
            return existing_tor(self.data.get("tor"))
        except TorError:
            return None

    def tor_setting(self) -> str:
        """``"auto"``, ``"own"`` or ``host:port`` - which Tor to use (the vault setting)."""
        return (self.data.get("tor") or {}).get("socks") or "auto"

    async def set_tor(self, value: str) -> None:
        """Use a running Tor (``host:port``), our own (``own``), or decide (``auto``).

        ``auto`` uses Tails' Tor on Tails and starts our own everywhere else.
        """
        value = value.strip().lower() if value.strip().lower() in ("auto", "own", "") else value.strip()
        if value not in ("auto", "own", ""):
            try:
                host, port = parse_socks(value)
            except TorError as exc:
                raise SessionError(str(exc)) from exc
            value = str(Socks(host, port))
        tor = dict(self.data.get("tor") or {"mode": "off"})
        if value in ("auto", ""):
            tor.pop("socks", None)
        else:
            tor["socks"] = value
        self.data["tor"] = tor
        self.save()
        self._checked_socks = None
        await self.close()

    async def set_bridges(self, mode: str, custom: list[str] | None = None) -> None:
        """Change how Tor connects; Tor is restarted at the next connection."""
        if mode not in BRIDGE_MODES:
            raise SessionError(f"unknown bridge mode {mode!r}")
        lines = [ln.strip() for ln in (custom or []) if ln.strip()]
        if mode == "custom" and not lines:
            raise SessionError("paste at least one bridge line")
        tor = dict(self.data.get("tor") or {})        # keeps the choice of Tor (socks)
        tor.update(mode=mode, custom=lines)
        self.data["tor"] = tor
        self.save()
        await self.close()

    async def close(self) -> None:
        """Close every node connection and stop the Tor this session started. Call it
        when the client ends; the vault itself needs no closing."""
        for client in list(self._clients.values()):
            try:
                await client.quit()
            except Exception:  # noqa: BLE001
                pass
        self._clients.clear()
        async with self._tor_lock:
            if self.tor:
                await self.tor.stop()
                self.tor = None

    async def node_info(self, node: str | None = None) -> dict:
        """UN-RFC 0011 node information, or {} if the node does not offer it - with
        ``carries``, how many groups the node itself carries (one LIST ACTIVE), so a client
        can show both that and how many of yours you read there (unseenet-gui#153), and
        ``carried``, what the node says it carries (UN-RFC 0055 section 3.1: its pattern
        list, files, sites)."""
        async def run(c: Client) -> dict:
            info = {}
            if c.capability("UNSEENET-NODEINFO") is not None:
                lines = await c.multiline("LIST UNSEENET.NODEINFO", 215)
                info = json.loads(lines[0]) if lines else {}
                self._keep_node_name(node or self.node, info)     # its own name, newest (#518)
            if isinstance(info.get("carries"), dict):  # UN-RFC 0055 3.1: what it says it carries
                info["carried"] = info.pop("carries")
            try:
                info["carries"] = len(await c.list_active())
            except (NNTPError, OSError, ValueError):
                pass                                  # a node that will not list: unknown
            return info
        return await self._call(run, node)
