"""Maintainers' blocks (UN-RFC 0018 sections 5.4 and 8.2): keys a hierarchy blocks.

Belongs here: reading a hierarchy's block list and refusing posts by blocked keys when
the operator honours blocks.

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Blocks:
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
        from ... import hierarchies as hz
        name = group_id.rpartition("@")[0] or group_id
        cached = self._blocks.get(name)
        if cached and time.monotonic() - cached[0] < self.BLOCKS_TTL:
            return cached[1]
        from ...known_nodes import PROJECT_KEY
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
