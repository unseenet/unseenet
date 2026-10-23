"""Postage and key ripening (UN-RFC 0006, 0025): what an article must pay.

Belongs here: the postage an article needs for its author's ripening level (section 5),
checking a key's chain (``ripe@<fp>``, its ``Key-Ripening`` header), and the ripe
group's manifest.

Not here: the extra bits for blobs (blobs.py adds them in accepting.py).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Postage:
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
