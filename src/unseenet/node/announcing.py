"""A node announces itself (UN-RFC 0055 section 5): it ripens its own node key, then
posts where it is and what it carries in ``unseenet.nodes.announce``, signed with that
key, and again when that changes and every few weeks.

Belongs here: the node key's ripening (UN-RFC 0025: a node key is ripened like any
other, so that announcing costs the same as posting) and the node's own announcement,
both taken by this node first and passed on to its peers like any article.

Not here: the rules (``core/announcements.py``), what a node checks when it takes an
announcement (``node/server/announcements.py``)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..core import announcements as an
from ..core import ripening as rp
from ..core.article import ArticleError, format_date, new_article, parse_date
from ..core.groups import make_group_id, manifest_article
from ..known_nodes import NODES_ANNOUNCE_GROUP
from .server import Node

log = logging.getLogger("unseenet.announce")

RIPEN_TO = 1                 # the level a node key ripens to by default: a few hours of one core
CHECK_EVERY = 3600.0


def _rfc3339(when: datetime) -> str:
    return when.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _announceable(text: str) -> bool:
    """An address this node may say it has: onion, or test only on a test network."""
    from ..core import transport
    try:
        a = transport.parse(text)
    except transport.AddressProblem:
        return False
    return a is not None and transport.announceable(a)


class Announcer:
    """Ripens ``node``'s key and announces it at ``address``. State in
    ``<data>/announce.json``: the key's ripening chain, what was announced and when."""

    def __init__(self, node: Node, data: Path, address: str, *, addresses=(),
                 ripen_to: int = RIPEN_TO, now: Callable[[], datetime] | None = None,
                 prove: Callable | None = None):
        self.node, self.address = node, address
        self.addresses = tuple(t for t in addresses if _announceable(t))   # 0064 section 2.3
        self.path = Path(data) / "announce.json"
        self.ripen_to = ripen_to
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._prove = prove or (lambda pk, start, t: rp.prove_segment(pk, start, t))
        self.state = self._load()

    # --- state ------------------------------------------------------------------------------

    def _load(self) -> dict:
        try:
            st = json.loads(self.path.read_text())
        except (OSError, ValueError):
            st = {}
        st.setdefault("segments", [])
        return st

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        tmp.replace(self.path)

    @property
    def chain(self) -> rp.Chain:
        return rp.Chain([rp.Segment.from_dict(s) for s in self.state["segments"]])

    @property
    def level(self) -> int | None:
        return self.chain.level if self.state["segments"] else None

    # --- ripening (UN-RFC 0025) -----------------------------------------------------------------

    async def ripen_once(self) -> bool:
        """One segment of the node key's chain, in a thread at low priority. False when
        the key is ripe enough, ripening is not available, or the machine cannot."""
        from ..client import machine
        from ..client.session import Session
        chain = self.chain
        level = self.level
        if (level is not None and level >= self.ripen_to) or not rp.available():
            return False
        length = rp.fitting_segment_length(chain.t, len(chain.segments), machine.ripening_budget())
        if not length:
            return False
        pk = self.node.key.public_key
        seg = await Session._in_ripening_thread(lambda: self._prove(pk, chain.end, length))
        if seg is None:
            return False
        self.state["segments"].append(seg.to_dict())
        self._save()
        log.info("node key ripened to t=%d (level %s)", self.chain.t, self.level)
        return True

    async def publish_ripening(self) -> bool:
        """The node key's ripe@ manifest (UN-RFC 0025 section 3.3), taken here and passed
        on, when the chain grew since it was last published."""
        chain = self.chain
        if chain.level is None or self.state.get("published_t") == chain.t:
            return False                      # nothing to show before level 0 (section 3.3)
        key = self.node.key
        gid = make_group_id(rp.GROUP_NAME, key.public_key)
        held = self.node.store.manifest(gid)
        data = {"v": 1, "name": rp.GROUP_NAME, "type": "channel", "owner": key.key_text,
                "serial": (held.serial if held is not None else 0) + 1, "min_pow": 0,
                "retention_days": 7, "view": "data", "ripening": chain.to_manifest()}
        bits = rp.required_pow(self.node.config.min_pow, 0, chain.level, allow_unripe=True)
        art = await asyncio.to_thread(manifest_article, key, gid, data, bits)
        art.set("Key-Ripening", chain.header())
        try:
            self.node.accept(art.to_bytes())
        except ArticleError as exc:
            if exc.reason != "duplicate":
                log.warning("the node key's ripening was not taken: %s", exc)
                return False
        self.state["published_t"] = chain.t
        self._save()
        return True

    # --- announcing (UN-RFC 0055 section 5) ------------------------------------------------------

    def _says(self) -> tuple[str, dict]:
        cfg = self.node.config
        op = cfg.operator or {}
        what = {"address": self.address, "name": cfg.name, "carries": self.node.carries_info(),
                "addresses": list(self.addresses), "operator": op.get("key"),
                "contact": op.get("contact")}
        return an.fingerprint(**what), what

    async def announce(self) -> str | None:
        """Post this node's announcement when it is due. Returns its Message-ID, or None
        when nothing was due or it could not be posted yet (said in the log)."""
        if not _announceable(self.address):
            log.warning("not announcing %s: only onion addresses are announced outside a "
                        "test network (UN-RFC 0064 section 2.3)", self.address)
            return None
        now = self.now()
        said, what = self._says()
        last = self.state.get("last")
        if not an.due(datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                      if last else None, self.state.get("said"), said, now):
            return None
        group = self.node.store.manifest(NODES_ANNOUNCE_GROUP)
        if group is None:
            log.info("not announcing yet: this node does not hold %s", NODES_ANNOUNCE_GROUP)
            return None
        cfg = self.node.config
        level = self.level
        if level is None or not rp.meets(level, cfg.min_ripe):
            log.info("not announcing yet: the node key is still ripening")
            return None
        bits = rp.required_pow(cfg.min_pow, group.min_pow, level)
        when = parse_date(format_date(now))           # the Date as written: coarse (0002)
        body = an.make_body(what["address"], what["name"], what["carries"], when,
                            addresses=what["addresses"], operator=what["operator"],
                            contact=what["contact"])
        art = new_article(NODES_ANNOUNCE_GROUP, an.subject(cfg.name), body, from_name=cfg.name,
                          now=when, extra=[("Content-Type", "application/json")])
        await asyncio.to_thread(art.finalize, self.node.key, bits)
        art.set("Key-Ripening", self.chain.header())
        try:
            self.node.accept(art.to_bytes())
        except ArticleError as exc:
            log.warning("the announcement was not taken: %s", exc)
            return None
        self.state.update({"last": _rfc3339(now), "said": said})
        self._save()
        log.info("announced this node at %s", self.address)
        return art.message_id

    async def run_once(self) -> str | None:
        while await self.ripen_once():
            await self.publish_ripening()
        await self.publish_ripening()
        return await self.announce()

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - announcing never stops the node
                log.exception("announcing failed; trying again later")
            await asyncio.sleep(CHECK_EVERY)
