"""What this node carries (UN-RFC 0055): its pattern list, the network's own groups it
carries whatever the list says, and what its peers carry.

Belongs here: whether the node carries a group, which groups are the network's own
(read from the hierarchy list for ``unseenet`` this node holds), whether a group is
excluded on purpose (never one of the network's own), and the peers' pattern lists
learned from their node information.

Not here: the pure rules (``core/carrying.py``).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Carrying:
    NETWORK_TTL = 300.0
    PEER_INFO_EVERY = 86400.0           # section 6: learn a peer's list at least daily

    def network_groups(self) -> frozenset[str]:
        """The infrastructure groups and the endorsed groups of ``unseenet.*`` (section
        4), from the newest hierarchy list for ``unseenet`` this node holds, or the one
        shipped with this version."""
        from ... import hierarchies as hz
        from ...core import carrying as ca
        from ...known_nodes import PROJECT_KEY
        cached = getattr(self, "_network", None)
        if cached and time.monotonic() - cached[0] < self.NETWORK_TTL:
            return cached[1]
        root = self._newest_list(hz.HIERARCHIES_GROUP, PROJECT_KEY,
                                 lambda body: hz.parse_root_list(body)[1])
        h = hz.policy_of("unseenet", root if root is not None else hz.builtin_root_list()[1])
        lst = None
        if h.policy == "governed":
            lst = self._newest_list(h.list, h.maintainer,
                                    lambda body: hz.parse_hierarchy_list(body, "unseenet"))
        lst = lst or hz.builtin_checkgroups()
        result = ca.network_groups(lst.groups.values())
        self._network = (time.monotonic(), result)
        return result

    def carries_group(self, group_id: str, local: bool = False) -> bool:
        """Section 2: key-bound groups as UN-RFC 0040 section 8 says (all of them here),
        local groups always (3.3), the network's own always (4), the rest by the list."""
        from ...core import carrying as ca
        if local or is_key_bound(group_id):
            return True
        m = self.store.manifest(group_id)
        if m is not None and m.local:
            return True
        return ca.carries(group_id, self.config.carries, self.network_groups())

    def excluded(self, group_id: str) -> bool:
        """``excludes`` (UN-RFC 0021 section 3), which never covers the network's own
        groups (UN-RFC 0055 section 3.2)."""
        return bool(self.config.excludes and wildmat(self.config.excludes, group_id)
                    and group_id not in self.network_groups())

    def carries_info(self) -> dict:
        """The ``carries`` field of this node's information (section 3.1)."""
        from ...core import carrying as ca
        cfg = self.config
        return ca.carries_object(cfg.carries, files=cfg.blobs is not None,
                                 sites=cfg.sites == "accept",
                                 new=cfg.new_groups != "manual")

    # --- peers (section 6) ---------------------------------------------------------------

    def peer_knows(self, peer_name: str, info: dict) -> None:
        """Note the pattern list a peer gives in its node information."""
        from ...core import carrying as ca
        peers = self.__dict__.setdefault("_peer_carries", {})
        peers[peer_name] = (time.monotonic(), ca.read_carries(info))

    def peer_info_due(self, peer_name: str) -> bool:
        """Whether the feeder should ask the peer for its node information again: when
        its pattern list is not known, or was learned more than a day ago."""
        seen = self.__dict__.get("_peer_carries", {}).get(peer_name)
        return seen is None or time.monotonic() - seen[0] >= self.PEER_INFO_EVERY

    def peer_carries(self, peer_name: str, group_id: str) -> bool:
        """Whether a peer carries a group, as far as this node knows: the network's own
        groups always; anything while its list is not known yet."""
        from ...core import carrying as ca
        seen = self.__dict__.get("_peer_carries", {}).get(peer_name)
        if seen is None or is_key_bound(group_id):
            return True
        return ca.carries(group_id, seen[1], self.network_groups())
