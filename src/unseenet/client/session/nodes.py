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
        """Stop using a node. Its groups move to the default node; returns them."""
        nodes = self.data["nodes"]
        if address not in nodes:
            return []
        if len(nodes) == 1:
            raise SessionError("you need at least one node")
        nodes.remove(address)
        moved = [gid for gid, e in self.data["groups"].items() if e.get("node") == address]
        for gid in moved:
            self.data["groups"][gid]["node"] = nodes[0]
            self._forget_numbers(gid)
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
        status = (lambda *_: None) if quiet else self.say
        socks = None
        if address.split(":")[0].endswith(".onion"):
            socks = await self._ensure_tor(status)
        status(f"Connecting to {address} ...")
        try:
            client = await Client.connect(address, socks)
            await client.fetch_capabilities()
        except (OSError, ConnectionError, NNTPError, asyncio.TimeoutError) as exc:
            wait = self._failed(address)
            self.emit(ev.NodeState(address, False, str(exc) or type(exc).__name__))
            if isinstance(exc, NNTPError) and exc.code == 400:    # full, at the greeting too
                raise SessionError(f"{address} is full; trying again in {wait:.0f} s, "
                                   "or another node") from exc
            raise
        self._backoff.setdefault(address, Backoff()).up()
        self._retry_at.pop(address, None)
        self.emit(ev.NodeState(address, True))
        status(f"Connected to {address}")
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
        """UN-RFC 0011 node information, or {} if the node does not offer it."""
        async def run(c: Client) -> dict:
            if c.capability("UNSEENET-NODEINFO") is None:
                return {}
            lines = await c.multiline("LIST UNSEENET.NODEINFO", 215)
            return json.loads(lines[0]) if lines else {}
        return await self._call(run, node)
