"""State (UN-RFC 0046 section 4.1): one answer with all a front end needs to draw itself.

Belongs here: ``state`` (identities, groups with counts, ripening, settings), pausing
ripening, the about text and the emoji list.

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import api as _a   # LocalAPI itself, joined after the parts


class State:
    # --- state (section 4.1) ---------------------------------------------------
    def state(self) -> dict:
        """``GET /api/state`` (section 4.1): everything a front end needs to draw itself -
        locked or not, setup, connection, identity, nodes, inbox, ripening."""
        s = self.session
        out = {"api": API_VERSION, "version": __version__, "service": self.service,
               "unlocked": s is not None, "setup": self.needs_setup(),
               "connected": self.connected, "status": self.status,
               "status_idle": self.status_idle, "identity": None,
               "node": None, "node_label": None, "nodes": [], "node_names": {},
               "inbox_ready": bool(self.runtime and self.runtime.inbox_ready),
               "ripening": None}
        if self.vault_path is not None:
            out["vault_exists"] = self.vault_path.exists()
        if s is not None and s.has_identity():
            ident = s.identity()
            out["identity"] = {"key": ident.key_text, "display": s.display_name(),
                               "label": s.identity_label(ident.key_text, s.display_name()),
                               # UN-RFC 0050 section 4.2: written down, and whether to remind
                               "words_written": s.words_written(),
                               "words_reminder": not self.service and s.words_reminder_due()}
            out["node"], out["nodes"] = s.node, list(s.nodes)
            out["node_label"] = s.node_label(s.node) or None               # #518
            out["node_names"] = {a: {k: e[k] for k in ("name", "source", "label")}
                                 for a, e in ((a, s.node_entry(a)) for a in s.nodes)}
            t = s.ripening().t
            out["ripening"] = {"level": rp.level(t), "t": t, "next_at": rp.next_threshold(t),
                               "published": s.published_level(), "available": rp.available(),
                               "paused": bool(self.runtime and self.runtime.ripening_paused)}
        return out

    async def set_ripening_paused(self, paused: bool) -> dict:
        """Pause or resume ripening in the background (#337), for this run only.
        Answers the state's ``ripening``; every listener gets ``ripening-paused``."""
        self._ready()
        if self.runtime is None:
            raise Locked("not running")
        if paused:
            await self.runtime.pause_ripening()
        else:
            await self.runtime.resume_ripening()
        self._broadcast({"event": "ripening-paused", "paused": self.runtime.ripening_paused})
        return self.state()["ripening"]

    def about(self) -> dict:
        """``GET /api/about`` (section 4.1): the "About Unseenet" text every client shows,
        with this version."""
        return about_text.as_dict(__version__)

    @staticmethod
    def emoji() -> dict:
        """For a picker (section 4.4, #362): static, so a front end loads it once."""
        return {"table": markup.emoji_table(), "categories": markup.emoji_categories(),
                "names": markup.emoji_names()}
