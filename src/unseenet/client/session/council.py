"""Session: council groups (UN-RFC 0054 Part I) from the client's side.

A client does not take a council manifest on a node's word: it reads every member's
copy from the group and counts the chain itself (``core.council``), as nodes do.

Belongs here: reading the copies and counting the chain, the current manifest of a
council group, making a genesis for a new council, and posting one's own copy of a
council manifest (signing) - with the checks that tell a person, before they sign,
why it would not count.

Not here: the rules (``core/council.py``), carrying council groups (the node).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names: SessionError, Message, ...
from ...core import council as cn


class CouncilMixin:
    async def _council_copies_on(self, c: Client, group_id: str) -> list[tuple[bytes, str, bytes]]:
        """(author, body, raw) of every valid council manifest copy the node holds for
        ``group_id``. Each is a signed article, checked here; nothing else is trusted."""
        try:
            _, low, high = await c.group(group_id)
        except NNTPError:
            return []
        if high < low:
            return []
        out = []
        for line in await c.multiline(f"HDR Control {low}-{high}", 225):
            number, _, value = line.partition(" ")
            if value.strip().lower() != "manifest":
                continue
            try:
                raw = strip_reader_headers(await c.article(number))
                art = Article.from_bytes(raw)
                validate_structure(art, raw_size=len(raw))
            except (ArticleError, NNTPError, ValueError, TypeError):
                continue
            if art.group == group_id and cn.is_council_manifest(art):
                out.append((art.author_key, art.body, raw))
        return out

    async def _council_current_on(self, c: Client, group_id: str):
        """The current manifest of a council group, counted from the node's copies,
        as a ``Manifest``; None when nothing counts."""
        from ...core.groups import Manifest
        copies = await self._council_copies_on(c, group_id)
        chain = cn.count_chain(group_id, [(a, b) for a, b, _ in copies])
        if chain.current is None:
            return None
        for author, body, raw in copies:
            if author in chain.signers[-1] and body.rstrip("\n").rstrip("\r") == chain.current.body:
                return Manifest.from_article(Article.from_bytes(raw), council_ok=True)
        return None

    async def council_copies(self, group_id: str, node: str | None = None) -> list[tuple[bytes, str]]:
        """(author, body) of every council manifest copy a node holds for the group."""
        async def run(c: Client):
            return [(a, b) for a, b, _ in await self._council_copies_on(c, group_id)]
        return await self._call(run, node or self.node_for(group_id))

    async def council_chain(self, group_id: str, node: str | None = None) -> cn.Chain:
        """The council group's chain, counted here from the copies (UN-RFC 0054, 5)."""
        return cn.count_chain(group_id, await self.council_copies(group_id, node))

    # --- a new council ---
    @staticmethod
    def council_genesis(name: str, gtype: str, members: list[str], *,
                        fields: dict | None = None, min_level: int | None = None,
                        sponsors: int | None = None, date: datetime | None = None,
                        founding_years: int | None = None, founding_size: int = 9,
                        founder: str | None = None) -> tuple[str, str]:
        """(group ID, body) of a new council's genesis: ``members`` as key texts, all
        full, joined on ``date`` (today, 00:00 UTC, by default). Nothing is posted:
        every member posts the same body with ``council_sign``. ``founding_years``: a
        founding period (UN-RFC 0054 section 19) of that many years, at most 3, whose
        founder is ``founder`` - the first member by default."""
        keys = []
        for k in members:
            pk = crypto.key_from_text(k)
            if pk not in keys:
                keys.append(pk)
        if len(keys) < cn.MIN_FULL:
            raise SessionError("a council needs at least 2 members")
        if gtype not in cn.COUNCIL_TYPES:
            raise SessionError("a council group is open or a channel")
        day = (date or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
        founding = None
        if founding_years:
            if not 0 < founding_years <= 3:
                raise SessionError("a founding period lasts 1 to 3 years")
            try:
                until = day.replace(year=day.year + founding_years)
            except ValueError:                         # 29 February
                until = day.replace(year=day.year + founding_years, day=28)
            founding = cn.Founding(crypto.key_from_text(founder) if founder else keys[0],
                                   until, founding_size)
            if founding.founder not in keys:      # so that nodes take its ``admit`` (19)
                fields = dict(fields or {})
                fields["posters"] = sorted({*fields.get("posters", []),
                                            crypto.key_to_text(founding.founder)})
        body = cn.council_body(name, gtype, seq=1, date=day,
                               members=[cn.Member(k, day, True) for k in keys],
                               min_level=min_level, sponsors=sponsors, founding=founding,
                               fields=fields)
        return cn.make_council_group_id(name, body), body

    async def council_check(self, group_id: str, body: str, node: str | None = None) -> tuple[cn.CouncilManifest, cn.Chain]:
        """Why ``body`` would not count if this identity signed it - raised as a
        SessionError in plain words - or the manifest and the chain it would join."""
        try:
            m = cn.CouncilManifest.from_body(group_id, body)
        except ArticleError as exc:
            raise SessionError(f"not a council manifest: {exc}") from exc
        me = self.identity().public_key
        if m.seq == 1:
            if cn.council_fingerprint(m.body) != split_group_id(group_id)[1]:
                raise SessionError("this genesis does not belong to that group")
            if me not in m.keys:
                raise SessionError("you are not one of its members")
            return m, cn.Chain(group_id)
        chain = await self.council_chain(group_id, node)
        cur = chain.current
        if chain.disputed:
            raise SessionError("this council's chain is disputed: nothing new counts")
        if cur is None or m.seq != cur.seq + 1 or m.prev != cur.hash:
            raise SessionError("it does not follow the council's current manifest")
        if me not in cur.full:
            raise SessionError("only full members' copies count")
        why = cn.change_ok(cur, m, chain.last_admission)
        if why:
            raise SessionError(f"it would not count: {why}")
        return m, chain

    async def council_sign(self, group_id: str, body: str, node: str | None = None) -> str:
        """Post this identity's own copy of a council manifest. Returns its Message-ID."""
        await self.council_check(group_id, body, node)
        art = new_article(group_id, None, body.rstrip("\n").rstrip("\r"),
                          extra=[("Control", "manifest"), ("Content-Type", "application/json")])
        return await self.post_article(art, node, sign_with=self.identity())

    # --- what members, the founder and anybody post (UN-RFC 0054 sections 11.1, 13.1, 19, 20)
    COUNCIL_ACTS = {"admit": "council", "renounce": "council", "resign": "council",
                    "sponsor": "claims", "unsponsor": "claims", "object": "claims"}

    async def council_act(self, group_id: str, act: str, key: str | None = None,
                          reason: str = "") -> str:
        """Post one of the articles a council's replicas read: the founder's ``admit
        <key>`` or ``renounce``, a member's ``resign`` (in the council group), a full
        member's ``sponsor``/``unsponsor <key>``, or anybody's ``object <key>`` with a
        reason (in its claims group, or the council group if it has none). Checks
        first that this identity may, and says why not in plain words."""
        if act not in self.COUNCIL_ACTS:
            raise SessionError(f"unknown council act {act!r}")
        chain = await self.council_chain(group_id)
        cur = chain.current
        if cur is None:
            raise SessionError("that council does not count yet")
        me = self.identity().public_key
        if act in ("admit", "renounce"):
            if cur.founding is None or cur.founding.founder != me:
                raise SessionError("only the council's founder can do that")
            if cur.founding.renounced:
                raise SessionError("the founding period was renounced")
        if act == "resign" and cur.member(me) is None:
            raise SessionError("you are not a member of this council")
        if act in ("sponsor", "unsponsor") and me not in cur.full:
            raise SessionError("only full members sponsor")
        if act in ("admit", "sponsor", "unsponsor", "object"):
            if not key:
                raise SessionError(f"{act} needs the key it is about")
            crypto.key_from_text(key)
        where = group_id
        if self.COUNCIL_ACTS[act] == "claims":
            where = cur.data.get("claims") or group_id
        subject = f"{act} {key}" if key else act
        if act == "object":
            if not reason.strip():
                raise SessionError("say why you object: replicas show it to the operators")
            return await self.post(where, subject, reason.strip() + "\n")
        from ...core.groups import canonical_json
        body = "{}\n" if act in ("admit", "renounce", "resign") else \
            canonical_json({"sponsor": key, "v": 1}) + "\n"
        return await self.post(where, subject, body, content_type="application/json")
