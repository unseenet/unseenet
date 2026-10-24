"""Reading: GROUP, ARTICLE, HEAD, BODY, STAT, OVER, HDR (RFC 3977, UN-RFC 0005 section 2.4).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class ReadingCommands:
    # --- group navigation ---
    async def cmd_group(self, args):
        """``GROUP <group>`` (RFC 3977 6.1.1): select a group - ``211`` with count, low
        and high; ``411`` when the node does not carry it, or it was removed or dropped."""
        removed = self.node.store.tombstone(args[0]) if args else None
        if removed:
            self.send("411 no such group (removed by its owner)" if removed == "owner"
                      else "411 no such group (dropped by this node)")
            return
        if not args or self.node.store.manifest(args[0]) is None:
            self.send("411 no such group")
            return
        self.group = args[0]
        nums = self.node.store.numbers(self.group)
        self.current = nums[0] if nums else None
        low, high = (nums[0], nums[-1]) if nums else (1, 0)
        self.send(f"211 {len(nums)} {low} {high} {self.group}")

    async def cmd_listgroup(self, args):
        """``LISTGROUP [group [range]]`` (RFC 3977 6.1.2): the article numbers of the
        selected group - ``211``."""
        if args:
            await self.cmd_group(args[:1])
            if self.group != args[0]:
                return
        if not self.group:
            self.send("412 no group selected")
            return
        nums = self.node.store.numbers(self.group)
        low, high = (nums[0], nums[-1]) if nums else (1, 0)
        self.send(f"211 {len(nums)} {low} {high} {self.group} list follows")
        for n in nums:
            self.send(str(n))
        self.send(".")

    def _lookup(self, args) -> tuple[int, str, bytes] | None:
        store = self.node.store
        if args and args[0].startswith("<"):
            raw = store.get(args[0])
            if raw is None:
                self.send("430 no such article")
                return None
            return 0, args[0], raw
        if not self.group:
            self.send("412 no group selected")
            return None
        number = int(args[0]) if args and args[0].isdigit() else self.current
        found = store.by_number(self.group, number) if number else None
        if not found:
            self.send("423 no such article number")
            return None
        self.current = number
        return number, found[0], found[1]

    def _reader_headers(self, number: int) -> bytes:
        # Synthesized for newsreaders only, never part of the article (UN-RFC 0005, 3).
        xref = f"\r\nXref: unseenet {self.group}:{number}" if number and self.group else ""
        return ("Path: not-for-mail" + xref).encode()

    async def _send_part(self, args, code: int, part: str):
        found = self._lookup(args)
        if not found:
            return
        number, msgid, raw = found
        head, _, body = raw.partition(b"\r\n\r\n")
        if not self.peer:
            head = head + b"\r\n" + self._reader_headers(number)
        payload = {"article": head + b"\r\n\r\n" + body, "head": head + b"\r\n", "body": body,
                   "stat": None}[part]
        self.send(f"{code} {number} {msgid}")
        if payload is not None:
            self.writer.write(dot_stuff(payload))
        if part in ("article", "body") and not self.peer:
            self.node.stats.served_one()          # how many, never which (UN-RFC 0011)

    async def cmd_article(self, args):
        """``ARTICLE <message-id>|<number>`` (RFC 3977 6.2.1): the whole article - ``220``,
        or ``430``/``423`` when there is none. The node's own headers are not sent."""
        await self._send_part(args, 220, "article")

    async def cmd_head(self, args):
        """``HEAD <message-id>|<number>``: the article's headers - ``221``."""
        await self._send_part(args, 221, "head")

    async def cmd_body(self, args):
        """``BODY <message-id>|<number>``: the article's body - ``222``."""
        await self._send_part(args, 222, "body")

    async def cmd_stat(self, args):
        """``STAT <message-id>|<number>``: whether the article is here - ``223``."""
        await self._send_part(args, 223, "stat")

    # --- overview (RFC 3977 sections 8.3-8.5; UN-RFC 0005 section 2.4) ---
    OVERVIEW_FMT = ("Subject:", "From:", "Date:", "Message-ID:", "References:",
                    ":bytes", ":lines", "Xref:full")

    def _range(self, args) -> list[tuple[int, str, bytes]] | None:
        """Articles named by a message-id, a number, n-, n-m or (none) the current one."""
        store = self.node.store
        if args and args[0].startswith("<"):
            raw = store.get(args[0])
            if raw is None:
                self.send("430 no such article")
                return None
            return [(0, args[0], raw)]
        if not self.group:
            self.send("412 no group selected")
            return None
        nums = store.numbers(self.group)
        if not args:
            if self.current is None:
                self.send("420 no current article")
                return None
            lo = hi = self.current
        else:
            first, dash, last = args[0].partition("-")
            try:
                lo = int(first)
                hi = (int(last) if last else (nums[-1] if nums else lo)) if dash else lo
            except ValueError:
                self.send("501 syntax: range n, n- or n-m")
                return None
        out = []
        for n in nums:
            if lo <= n <= hi:
                found = store.by_number(self.group, n)
                if found:
                    out.append((n, found[0], found[1]))
        if not out:
            self.send("423 no articles in that range")
            return None
        return out

    @staticmethod
    def _clean(value: str) -> str:
        return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")

    def _overview_fields(self, number: int, raw: bytes) -> dict[str, str]:
        """The overview of one article. Articles a newsreader cannot show get a
        fixed subject, so readers do not show empty lines (#21)."""
        try:
            art = Article.from_bytes(raw)
        except ArticleError:
            return {"Subject:": "(invalid article)"}
        ctl = art.control
        encrypted = art.get("Encrypted", "")
        if ctl and ctl[0] == "manifest":
            subject = "(group settings)"
        elif ctl:
            subject = f"(control: {ctl[0]})"
        elif encrypted.strip() in INBOX_SCHEMES or art.group.startswith("inbox@"):
            subject = "(private message)"
        elif encrypted:
            subject = "(encrypted)"
        else:
            subject = art.get("Subject") or "(no subject)"
        head, _, body = raw.partition(b"\r\n\r\n")
        group = self.group or art.group
        return {
            "Subject:": subject, "From:": art.get("From") or "(unknown)",
            "Date:": art.get("Date", ""), "Message-ID:": art.message_id,
            "References:": art.get("References", ""), ":bytes": str(len(raw)),
            ":lines": str(body.count(b"\n") + (1 if body and not body.endswith(b"\n") else 0)),
            "Xref:full": f"Xref: unseenet {group}:{number}" if number else "",
        }

    async def cmd_over(self, args):
        """``OVER [range|message-id]`` (RFC 3977 8.3, also ``XOVER``): the overview of many
        articles - ``224``, with the Unseenet fields of UN-RFC 0005 section 2.4."""
        found = self._range(args)
        if found is None:
            return
        self.send("224 overview information follows")
        for number, _, raw in found:
            f = self._overview_fields(number, raw)
            self.send("\t".join([str(number)] + [self._clean(f.get(k, "")) for k in self.OVERVIEW_FMT]))
        self.send(".")

    cmd_xover = cmd_over

    async def cmd_list_overview_fmt(self, args):
        """``LIST OVERVIEW.FMT`` (RFC 3977 8.4): the fields of OVER, with
        Unseenet's at the end (UN-RFC 0005 section 2.4)."""
        self.send("215 order of fields in overview database")
        for field_ in self.OVERVIEW_FMT:
            self.send(field_)
        self.send(".")

    async def cmd_hdr(self, args, code: int = 225):
        """``HDR <field> [range|message-id]`` (RFC 3977 8.5): one header of many
        articles - ``225``. Unseenet headers are allowed too (UN-RFC 0005 section 2.4)."""
        if not args:
            self.send("501 syntax: HDR field [range|message-id]")
            return
        name = args[0]
        found = self._range(args[1:])
        if found is None:
            return
        key = name if name.startswith(":") else name.rstrip(":").lower()
        self.send(f"{code} headers follow")
        for number, _, raw in found:
            f = self._overview_fields(number, raw)
            if key.startswith(":"):
                value = f.get(key, "")
            else:
                over = {k.rstrip(":").lower(): v for k, v in f.items() if not k.startswith(":")}
                if key in over and key != "xref:full":
                    value = over[key]
                else:
                    try:
                        value = Article.from_bytes(raw).get(name.rstrip(":"), "") or ""
                    except ArticleError:
                        value = ""
            self.send(f"{number} {self._clean(value)}")
        self.send(".")

    async def cmd_xhdr(self, args):
        """``XHDR`` (RFC 2980): HDR with the old code ``221``, for older newsreaders."""
        await self.cmd_hdr(args, code=221)

    async def cmd_list_headers(self, args):
        """``LIST HEADERS`` (RFC 3977 8.6): HDR takes any header (``:``)."""
        self.send("215 headers and metadata items supported")
        self.send(":")
        self.send(".")
