"""Councils (UN-RFC 0054, 0061) for front ends: a council in plain fields, its hearings,
and what a person posts in one - their copy of a manifest, and the founder's, a member's
or anybody's acts. The same as ``unseenet council show|hearings|sign|admit|renounce|
resign|sponsor|unsponsor|object`` (#841, #578).

Belongs here: ``GET /api/council``, ``GET /api/council/hearings``, ``POST /api/council``.
The rules are the session's (``Session.council_*``) and the core's (``core/council.py``).

Part of ``LocalAPI`` (see __init__.py)."""

from __future__ import annotations

from datetime import datetime, timezone

from . import *  # noqa: F403  - the module's names, as when this was one file

ACTIONS = ("sign", "admit", "renounce", "resign", "sponsor", "unsponsor", "object")
_DONE = {"admit": "Asked the council's replicas to admit {key}. They do it once it has run "
                  "as a shadow for 7 days, agreeing.",
         "renounce": "The founding period is given up.",
         "resign": "You stepped down. The other members' replicas remove your key.",
         "sponsor": "You sponsor {key}.",
         "unsponsor": "Your sponsorship of {key} is taken back.",
         "object": "Your objection is posted. Everybody can see it."}


def _iso(t) -> str | None:
    return t.isoformat() if t is not None else None


def council_fields(m, me: bytes, disputed: bool = False) -> dict:
    """A council manifest as plain fields, for a person: who is in it, how newcomers
    come in, the founding period (UN-RFC 0054 sections 3, 11, 19, 21)."""
    from ....core import council as cn
    f = m.founding
    members = [{"key": crypto.key_to_text(x.key), "full": x.full, "joined": _iso(x.joined),
                "by_founder": x.by == "founder", "you": x.key == me} for x in m.members]
    you = m.member(me)
    return {"group": m.group_id, "counts": True, "name": m.name, "type": m.type,
            "title": m.data.get("title", ""), "seq": m.seq, "date": _iso(m.date),
            "members": members, "full": len(m.full), "min_level": m.min_level,
            "sponsors": m.sponsors, "max_probation": m.max_probation,
            "founding": None if f is None else {
                "founder": crypto.key_to_text(f.founder), "you": f.founder == me,
                "until": _iso(f.until), "size": f.size, "renounced": f.renounced,
                "lasts": m.founding_lasts(datetime.now(timezone.utc))},
            "room": m.room, "claims": m.data.get("claims"),
            "proposals": m.data.get("proposals"),
            "you": None if you is None else ("full member" if you.full
                                             else "member on probation"),
            "disputed": disputed, "kind": "list council" if m.data.get("lists") else
            ("registrar" if m.data.get("claims") else "council"),
            "max_members": cn.MAX_MEMBERS}


class Councils:
    async def council(self, gid: str) -> dict:
        """``GET /api/council?group=``: the current manifest in plain fields, ``counts``
        true; with ``disputed`` when two count for one number (nothing new applies).
        For a genesis not every member has signed: ``counts`` false, its fields, and
        ``missing``, the keys still to sign."""
        from ....core.council import CouncilManifest, count_chain
        s = self._ready()
        if not gid:
            raise SessionError("which council? (group)")
        copies = await s.council_copies(gid)
        chain = count_chain(gid, copies)
        me = s.identity().public_key
        if chain.current is not None:
            return council_fields(chain.current, me, chain.disputed)
        for _, body in copies:
            try:
                m = CouncilManifest.from_body(gid, body)
            except Exception:  # noqa: BLE001  - not one we can show
                continue
            if m.seq != 1:
                continue
            signed = {a for a, b in copies if b.rstrip("\n").rstrip("\r") == m.body}
            out = council_fields(m, me)
            out.update(counts=False, missing=[crypto.key_to_text(k) for k in m.keys
                                              if k not in signed])
            return out
        raise NotFound("no council manifest for that group on your nodes")

    async def council_hearings(self, gid: str) -> dict:
        """``GET /api/council/hearings?group=``: the council's proposals that count, with
        their state and objections so far (UN-RFC 0061), newest last."""
        s = self._ready()
        hs = await s.council_hearings(gid)
        return {"group": gid, "hearings": [
            {**h, "closes": _iso(h["closes"]), "applies": _iso(h["applies"])} for h in hs]}

    async def council_post(self, body: dict) -> dict:
        """``POST /api/council`` ``{"group", "action", ...}``:

        - ``sign`` with ``body`` (the manifest's body, from a draft) and optionally
          ``also`` (``[{"group", "body"}]``, the room and other groups of the draft):
          post your copy, after the checks that say why it would not count;
        - ``admit`` and ``renounce`` (the founder), ``resign`` (a member), ``sponsor``
          and ``unsponsor`` (a full member) with ``key``; ``object`` with ``key`` (a
          shadow's or member's key, or a proposal's id) and ``reason``, ``withdraw`` to
          take an objection to a proposal back.

        Answers ``{"posted", "text"}`` - the text for people - and the council as
        ``GET`` does (``council``)."""
        s = self._ready()
        gid = str(body.get("group", ""))
        action = str(body.get("action", ""))
        if action not in ACTIONS:
            raise SessionError(f"action is one of {', '.join(ACTIONS)}")
        if action == "sign":
            text_body = str(body.get("body", ""))
            if not text_body:
                raise SessionError("sign needs the manifest's body")
            await s.council_check(gid, text_body)
            for x in body.get("also") or []:            # the room (UN-RFC 0054 section 21)
                await s.council_sign(str(x["group"]), str(x["body"]))
            mid = await s.council_sign(gid, text_body)
            text = "Your copy is posted. The council counts once every member has posted it."
        else:
            key = str(body["key"]).strip() if body.get("key") else None
            mid = await s.council_act(gid, action, key, str(body.get("reason", "")),
                                      bool(body.get("withdraw")))
            text = _DONE[action].format(key=key or "")
        try:
            now = await self.council(gid)
        except (NotFound, SessionError):
            now = None
        return {"posted": mid, "text": text, "council": now}
