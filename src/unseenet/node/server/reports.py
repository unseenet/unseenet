"""Spam reports a node follows (UN-RFC 0045 section 6).

A node follows nobody unless its operator says so, in ``[[follow_reports]]``: each
issuer with what to do with the posts it reports (``hide``: not served and not
forwarded; ``delete``) and with the keys (``refuse`` their new articles,
``surcharge``: 6 bits more postage, or ``ignore``). The reports are read from the
issuers' ``reports@`` groups, which the node carries like other key-bound groups, and
apply as they arrive - also to articles that arrive later.

Belongs here: the reports of the issuers followed (``report_book``), checking a new
article against them, the postage surcharge, which held posts are hidden, and deleting
those the operator wants deleted.

Not here: the form of reports (``core/reports.py``), what readers do (the client).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from ...core import reports as rpt


class Reports:
    REPORTS_TTL = 300.0           # read the reports groups again at least this often

    def followed_issuers(self) -> dict[str, dict]:
        """{issuer key: {"posts": ..., "keys": ...}} from the configuration."""
        return {f["issuer"]: f for f in self.config.follow_reports}

    def report_book(self) -> rpt.Book:
        """The reports of the issuers this node follows, read from their ``reports@``
        groups; kept until one of those groups changes, or REPORTS_TTL."""
        cached = getattr(self, "_report_book", None)
        if cached is not None and time.monotonic() - cached[0] < self.REPORTS_TTL:
            return cached[1]
        book = rpt.Book()
        for issuer in self.followed_issuers():
            try:
                gid = rpt.reports_group(crypto.key_from_text(issuer))
            except crypto.CryptoError:
                continue
            manifest = self.store.manifest(gid)
            if manifest is None or manifest.expired():
                continue
            automatic = manifest.raw.get("automatic") is True
            for n in self.store.numbers(gid):
                found = self.store.by_number(gid, n)
                if not found:
                    continue
                try:
                    book.add(rpt.parse_report(Article.from_bytes(found[1])), automatic)
                except (ArticleError, rpt.ReportError, ValueError, KeyError):
                    continue
        self._report_book = (time.monotonic(), book)
        return book

    def _post_action(self, message_id: str) -> tuple[str, rpt.Hit] | None:
        """("hide" or "delete", the report) for a post reported by an issuer followed."""
        if not self.config.follow_reports:
            return None
        hit = self.report_book().post(message_id)
        if hit is None:
            return None
        return self.followed_issuers()[hit.issuer].get("posts", "hide"), hit

    def _key_action(self, key: str) -> tuple[str, rpt.Hit] | None:
        """("refuse", "surcharge" or "ignore", the report) for a reported key."""
        if not self.config.follow_reports or not key:
            return None
        hit = self.report_book().key(key)
        if hit is None:
            return None
        return self.followed_issuers()[hit.issuer].get("keys", "ignore"), hit

    def report_hidden(self, message_id: str) -> bool:
        """A post this node does not serve or forward: reported by an issuer it follows."""
        return self._post_action(message_id) is not None

    def _check_reported(self, art: Article) -> None:
        """Refuse a new article whose key an issuer followed reports, when the operator
        chose ``refuse``, and a reported post the operator deletes. Reports never touch
        the issuers' own groups or a manifest (a key's groups must stay renewable)."""
        if not self.config.follow_reports or art.control or rpt.is_reports_group(art.group):
            return
        found = self._key_action(art["Author-Key"])
        if found and found[0] == "refuse":
            raise ArticleError("permission", f"the key is reported ({found[1].reason}) by an "
                               "issuer this node follows")
        post = self._post_action(art.message_id)
        if post and post[0] == "delete":
            raise ArticleError("permission", f"reported ({post[1].reason}) by an issuer "
                               "this node follows")

    def _report_surcharge(self, art: Article) -> int:
        """Extra postage for a key reported by an issuer followed with ``surcharge``."""
        if not self.config.follow_reports or art.control or rpt.is_reports_group(art.group):
            return 0
        found = self._key_action(art["Author-Key"])
        return rpt.SURCHARGE_BITS if found and found[0] == "surcharge" else 0

    def _reports_arrived(self, art: Article) -> None:
        """An article in the reports group of an issuer followed (a report, or the
        withdrawal of one): read the reports again and apply them."""
        if not self.config.follow_reports or not rpt.is_reports_group(art.group):
            return
        fp = rpt.issuer_of(art.group)
        if not any(self._fingerprint(k) == fp for k in self.followed_issuers()):
            return
        self._report_book = None
        self.apply_reports()

    @staticmethod
    def _fingerprint(key: str) -> str:
        try:
            return crypto.fingerprint(crypto.key_from_text(key))
        except crypto.CryptoError:
            return ""

    def apply_reports(self) -> int:
        """Delete the held posts reported by issuers this node follows with
        ``posts = "delete"`` (their history stays, so they are not taken again).
        Hidden posts stay, unserved. Returns how many were deleted."""
        if not self.config.follow_reports:
            return 0
        followed = self.followed_issuers()
        deleted = 0
        for mid, hit in self.report_book().reported_posts().items():
            if followed[hit.issuer].get("posts") != "delete" or self.store.get_meta(mid) is None:
                continue
            if rpt.is_reports_group(self.store.get_meta(mid)[0]):
                continue
            self.store.delete(mid)
            deleted += 1
        if deleted:
            log.info("deleted %d post(s) reported by issuers this node follows", deleted)
            self.sweep_blobs(retention=False)
        return deleted
