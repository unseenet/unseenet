"""`unseenet council`: council groups (UN-RFC 0054) from the command line.

Belongs here: making a new council's genesis as a draft file to hand to the other
members (``create``), posting one's own copy of a draft after seeing in plain words
what it says (``sign``), and showing a council - its members, and while the genesis
does not count yet, who has still to sign (``show``). All through ``Session``
(``client/session/council.py``).

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # noqa: F401  names tests patch on the module, read at call time


def council_parsers(sub) -> None:
    """The parser of ``unseenet council``."""
    s = sub.add_parser("council", help="councils: groups owned by several keys together "
                                       "(UN-RFC 0054)")
    t = s.add_subparsers(dest="what")
    p = t.add_parser("create", help="a new council: write its genesis to a draft file that "
                                    "every member signs")
    p.add_argument("name", help="the group's name, e.g. dk.lists")
    p.add_argument("--member", action="append", default=[], metavar="KEY",
                   help="another member's key (repeat); you are a member too")
    p.add_argument("--type", choices=("channel", "open"), default="channel",
                   help="channel: only members post (default); open: anybody")
    p.add_argument("--title", default="")
    p.add_argument("--description", default="")
    p.add_argument("--min-pow", type=int, default=None, help="postage to post in it")
    p.add_argument("--retention-days", type=int, default=None)
    p.add_argument("--min-level", type=int, default=None,
                   help="ripening level a newcomer's key needs (default 4)")
    p.add_argument("--sponsors", type=int, default=None,
                   help="full members who must sponsor a newcomer (default 0)")
    p.add_argument("--founding", type=int, default=None, metavar="YEARS",
                   help="a founding period of up to 3 years in which you, as founder, can "
                        "admit members faster (UN-RFC 0054 section 19)")
    p.add_argument("--founding-size", type=int, default=9,
                   help="... ending early once the council has this many full members (default 9)")
    p.add_argument("--out", default=None, help="the draft file (default: <name>.council.json)")
    p.add_argument("--sign", action="store_true", help="also post your own copy now")
    p = t.add_parser("sign", help="post your own copy of a council draft, after seeing it")
    p.add_argument("draft", help="the draft file you were given")
    p.add_argument("--yes", action="store_true", help="do not ask")
    p = t.add_parser("show", help="a council's members, and who still has to sign")
    p.add_argument("group")


def _short(key: bytes) -> str:
    return crypto.key_to_text(key)


def _describe(m, me: bytes) -> list[str]:
    """A council manifest in plain words, for a person about to sign it."""
    kind = "only members post" if m.type == "channel" else "anybody may post"
    lines = [f"Group      {m.group_id}",
             f"Manifest   number {m.seq}, dated {m.date:%Y-%m-%d}",
             f"Kind       {m.type} ({kind})"]
    if m.data.get("title"):
        lines.append(f"Title      {m.data['title']}")
    lines.append(f"Members    {len(m.members)} ({len(m.full)} full)")
    for x in m.members:
        tag = (" (you)" if x.key == me else "") + (" (admitted by the founder)" if x.by else "")
        lines.append(f"  {'full     ' if x.full else 'probation'}  {_short(x.key)}{tag}")
    f = m.founding
    if f is not None:
        who = _short(f.founder) + (" (you)" if f.founder == me else "")
        if f.renounced:
            lines.append(f"Founding   renounced; the founder was {who}")
        elif m.founding_lasts(m.date):
            lines.append(f"Founding   until {f.until:%Y-%m-%d} at the latest, or {f.size} full "
                         f"members; founder: {who}")
        else:
            lines.append(f"Founding   over; the founder was {who}")
    lines.append(f"Newcomers  key ripened to level {m.min_level}; {m.sponsors} sponsor(s); "
                 f"at most {m.max_probation} on probation at a time")
    return lines


async def c_council(app: App, args) -> None:
    """``unseenet council create|sign|show``: see ``unseenet council -h``."""
    from ..client.session import SessionError
    from ..core.council import CouncilManifest
    s = _session(app, args)
    what = getattr(args, "what", None) or "show"
    try:
        if what == "create":
            me = s.identity()
            fields = {k: v for k, v in (("title", args.title), ("description", args.description),
                                        ("min_pow", args.min_pow),
                                        ("retention_days", args.retention_days)) if v}
            gid, body = s.council_genesis(args.name, args.type, [me.key_text, *args.member],
                                          fields=fields, min_level=args.min_level,
                                          sponsors=args.sponsors,
                                          founding_years=getattr(args, "founding", None),
                                          founding_size=getattr(args, "founding_size", 9))
            out = Path(args.out or f"{args.name}.council.json")
            out.write_text(json.dumps({"v": 1, "group": gid, "body": body}, indent=2,
                                      ensure_ascii=False) + "\n", encoding="utf-8")
            text = [f"Draft written to {out}.", "",
                    *_describe(CouncilManifest.from_body(gid, body), me.public_key), "",
                    "The council exists when every member has posted exactly this. Send the",
                    "file to the others; each runs:  unseenet council sign " + out.name]
            mid = None
            if args.sign:
                mid = await s.council_sign(gid, body)
                text.append("Your own copy is posted.")
            emit(args, "\n".join(text), {"group": gid, "draft": str(out), "posted": mid})
        elif what == "sign":
            draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
            gid, body = draft["group"], draft["body"]
            m, _ = await s.council_check(gid, body)
            if not args.json:
                print("\n".join(_describe(m, s.identity().public_key)))
            if not args.yes:
                if not sys.stdin.isatty():
                    sys.exit("Not signed. Add --yes to confirm when not running interactively.")
                if input("Post your copy of this? [y/N] ").strip().lower() not in ("y", "yes", "j", "ja"):
                    sys.exit("Not signed.")
            mid = await s.council_sign(gid, body)
            emit(args, f"Posted your copy ({mid}). Check with: unseenet council show {gid}",
                 {"group": gid, "posted": mid})
        elif what == "show":
            copies = await s.council_copies(args.group)
            from ..core.council import count_chain
            chain = count_chain(args.group, copies)
            me = s.identity().public_key
            if chain.current is not None:
                lines = _describe(chain.current, me)
                if chain.disputed:
                    lines.append(f"DISPUTED: two different manifests number {chain.fork_seq} "
                                 "count; nothing new is applied (UN-RFC 0054 section 5).")
                emit(args, "\n".join(lines), {"group": args.group, "seq": chain.current.seq,
                                              "members": [x.as_json() for x in chain.current.members],
                                              "disputed": chain.disputed})
                return
            genesis = []
            for _, body in copies:
                try:
                    m = CouncilManifest.from_body(args.group, body)
                except Exception:  # noqa: BLE001  - not one we can show
                    continue
                if m.seq == 1:
                    genesis.append(m)
            if not genesis:
                sys.exit("No council manifest for that group on this node.")
            m = genesis[0]
            signed = {a for a, b in copies if b.rstrip("\n").rstrip("\r") == m.body}
            missing = [k for k in m.keys if k not in signed]
            lines = ["Not a council yet: the genesis counts when every member has signed.",
                     *_describe(m, me), "Still to sign:",
                     *(f"  {_short(k)}{' (you)' if k == me else ''}" for k in missing)]
            emit(args, "\n".join(lines), {"group": args.group, "seq": 0,
                                          "missing": [_short(k) for k in missing]})
    except SessionError as exc:
        sys.exit(str(exc))


__all__ = ["c_council", "council_parsers"]
