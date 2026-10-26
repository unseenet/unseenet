"""The meeting point for copying an identity (UN-RFC 0050 section 3.3): XUNMEET.

A device that copies its identities to another opens a one-time onion service and
leaves its address here under a number and a tag; the new device, which has only the
typed code, fetches it once. The table is in memory only (``Node.meetings``), never
replicated to peers and never logged: the node learns that some device copies
something, at some time, and a one-time address - no identity, key or code.

    XUNMEET OPEN <onion-address> <tag>   -> 290 <n>
    XUNMEET LOOKUP <n> <tag>             -> 291 <onion-address>  (and the record is gone)
                                         -> 490 no such meeting

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

import re

from . import *  # noqa: F403  - the module's names, as when this was one file

MEET_SECONDS = 600.0          # a record lives 10 minutes (section 3.3)
MEET_MISSES = 3               # wrong tags for one number before it is deleted
MEET_OPENS = 5                # OPENs per connection
MEET_LOOKUPS = 10             # LOOKUPs per connection
MEET_MAX = 999                # numbers 1-999
_ONION = re.compile(r"^[a-z2-7]{56}\.onion$")
_TAG = re.compile(r"^[0-9a-f]{32}$")


class MeetCommands:
    def _meetings(self) -> dict[int, dict]:
        """The node's open meetings, the expired ones gone."""
        now = time.monotonic()
        table = self.node.meetings
        for n in [n for n, m in table.items() if m["until"] < now]:
            del table[n]
        return table

    async def cmd_xunmeet(self, args):
        """``XUNMEET OPEN <address> <tag>`` or ``XUNMEET LOOKUP <n> <tag>`` (section 3.3)."""
        sub = args[0].upper() if args else ""
        if sub == "OPEN" and len(args) == 3 and _ONION.match(args[1]) and _TAG.match(args[2]):
            self._meet_opens = getattr(self, "_meet_opens", 0) + 1
            if self._meet_opens > MEET_OPENS:
                self.send("436 too many meetings on this connection")
                return
            table = self._meetings()
            free = [n for n in range(1, MEET_MAX + 1) if n not in table]
            if not free:
                self.send("436 the meeting point is full, try later")
                return
            n = random.SystemRandom().choice(free)
            table[n] = {"address": args[1], "tag": args[2], "misses": 0,
                        "until": time.monotonic() + MEET_SECONDS}
            self.send(f"290 {n}")
        elif sub == "LOOKUP" and len(args) == 3 and args[1].isdigit() and _TAG.match(args[2]):
            self._meet_lookups = getattr(self, "_meet_lookups", 0) + 1
            if self._meet_lookups > MEET_LOOKUPS:
                self.send("436 too many lookups on this connection")
                return
            table = self._meetings()
            n = int(args[1])
            record = table.get(n)
            if record is None:
                self.send("490 no such meeting")
            elif hmac.compare_digest(record["tag"], args[2]):
                del table[n]                                    # fetched once
                self.send(f"291 {record['address']}")
            else:
                record["misses"] += 1
                if record["misses"] >= MEET_MISSES:
                    del table[n]
                self.send("490 no such meeting")
        else:
            self.send("501 syntax: XUNMEET OPEN <onion-address> <tag> | XUNMEET LOOKUP <n> <tag>")
