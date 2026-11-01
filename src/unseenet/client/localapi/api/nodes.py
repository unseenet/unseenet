"""Your nodes (UN-RFC 0046 section 4.17, #518): see them by name, add, remove, choose the
default - what the terminal client's "Your nodes" does, for every front end.

Belongs here: ``nodes`` and ``change_nodes``. The known-node list for setting up stays
with the groups (``known_nodes``, section 4.3).

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file

NODE_INFO_SECONDS = 60


class Nodes:
    async def nodes(self, info: bool = False) -> dict:
        """``GET /api/nodes``: your nodes, the default first, each with its name, where the
        name is from (``known``, ``self``, ``none``), a label, the full address, its
        description and operator if listed, and the followed groups read there. With
        ``info``, each node is also asked for its node information (UN-RFC 0011):
        ``reachable`` and ``info`` (the node's answer, or ``{}`` if it offers none)."""
        s = self._ready()
        entries = s.node_entries()
        if info:
            async def ask(e: dict) -> None:
                try:
                    e["info"] = await asyncio.wait_for(s.node_info(e["address"]), NODE_INFO_SECONDS)
                    e["reachable"] = True
                except (SessionError, asyncio.TimeoutError, ValueError, *NETWORK_ERRORS):
                    e["info"], e["reachable"] = None, False
            await asyncio.gather(*(ask(e) for e in entries))
            names = {a: s.node_entry(a) for a in s.nodes}      # a name just learned
            for e in entries:
                e.update({k: names[e["address"]][k] for k in ("name", "source", "label")})
        known = {n["address"] for n in s.node_entries()}
        return {"nodes": entries,
                "known": [{**s.node_entry(n.address), "default": False}
                          for n in s.known_nodes() if n.address not in known]}

    async def change_nodes(self, data: dict) -> dict:
        """``POST /api/nodes`` ``{"action": "add" | "remove" | "default", "address": ...}``:
        answers ``GET /api/nodes`` (without asking the nodes), and for ``remove`` also
        ``moved``, the followed groups now read from the default node."""
        s = self._ready()
        action = data.get("action")
        address = data.get("address")
        if not isinstance(address, str) or not address.strip():
            raise SessionError("give a node address")
        address = address.strip()
        moved: list[str] = []
        if action == "add":
            if address not in s.nodes:
                check_node_address(address)
            s.add_node(address)
        elif action == "default":
            if address not in s.nodes:
                check_node_address(address)
            s.add_node(address, default=True)
        elif action == "remove":
            if address not in s.nodes:
                raise SessionError(f"{address} is not one of your nodes")
            moved = s.remove_node(address)
            try:                                       # where each group is read now (#603)
                rehomed = await s.rehome_groups(moved)
            except SessionError:
                rehomed = {"moved": {}, "unavailable": []}
        else:
            raise SessionError('action is "add", "remove" or "default"')
        if self.runtime is not None:
            self.runtime.nodes_changed()              # watches, and its groups at once
        self.session.emit(ev.GroupsChanged())
        out = await self.nodes()
        if action == "remove":
            out["moved"] = [g for g in moved if g not in rehomed["unavailable"]]
            out["unavailable"] = rehomed["unavailable"]   # no node of yours carries them
        return out


class AnnouncedNodes:
    async def announced(self, refresh: bool = False, check: str | None = None) -> dict:
        """``GET /api/nodes/announced``: the nodes that announced themselves (UN-RFC 0055
        section 5), newest first, each with ``key``, ``address``, ``name``, ``carries`` (its
        own word) and ``checked`` (True: the node at that address has that key; False: it
        has not; None: not yet). ``refresh`` reads the announcements again; ``check`` (a
        node key) checks that one node first, as a client must before it offers or uses it
        (section 5.3)."""
        s = self._ready()
        if refresh:
            await s.refresh_announced_nodes()
        if check:
            await s.check_announced(check)
        return {"nodes": s.announced_nodes()}


def check_node_address(address: str) -> None:
    """An address a client can reach: ``<56 base32>.onion`` (with an optional port), or
    ``host:port`` for a node on this machine or network."""
    import re
    host, _, port = address.partition(":")
    if port and not (port.isdigit() and 0 < int(port) < 65536):
        raise SessionError(f"{address}: the port is not a number from 1 to 65535")
    if host.endswith(".onion"):
        if not re.fullmatch(r"[a-z2-7]{56}\.onion", host.lower()):
            raise SessionError(f"{address} is not an onion address (56 letters and digits, then .onion)")
    elif not port:
        raise SessionError(f"{address}: give an onion address, or host:port")
