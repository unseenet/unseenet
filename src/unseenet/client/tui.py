"""Unseenet TUI client (Textual).

    unseenet-tui [--vault unseenet.vault]

Left: your groups with unread counts. Right: threads in the selected group
and the selected article. Everything is stored in the encrypted vault.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, DataTable, Footer, Header, Input, Label, ListItem, ListView,
                             Select, Static, TextArea)

from ..core.vault import Vault, VaultError
from .session import GroupInfo, Message, Session, SessionError, default_vault_path

REFRESH_SECONDS = 30

CSS = """
Screen { background: $surface; }
#groups-pane { width: 34; border-right: solid $primary-darken-2; }
#groups-title, #threads-title { background: $primary-darken-2; color: $text; padding: 0 1; text-style: bold; }
#groups { height: 1fr; }
#threads { height: 45%; }
#article { height: 1fr; padding: 0 1; border-top: solid $primary-darken-2; }
#article-head { color: $text-muted; }
#status { height: 1; background: $boost; color: $text-muted; padding: 0 1; }
.unread { text-style: bold; }

ModalScreen { align: center middle; }
.dialog { width: 80; height: auto; max-height: 90%; border: thick $primary; background: $panel; padding: 1 2; }
.dialog Label.title { text-style: bold; margin-bottom: 1; }
.dialog Input, .dialog Select { margin-bottom: 1; }
.dialog #body { height: 14; margin-bottom: 1; }
.dialog .buttons { height: auto; align-horizontal: right; }
.dialog Button { margin-left: 1; }
.dialog .hint { color: $text-muted; }
.dialog .error { color: $error; }
#browse-list { height: 20; }
"""


# ======================================================================
# Dialogs
# ======================================================================

class Dialog(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class UnlockDialog(Dialog):
    def __init__(self, path: Path, error: str = ""):
        super().__init__()
        self.path, self.error = path, error
        self.new = not path.exists()

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Create a new vault" if self.new else "Unlock your vault", classes="title")
            yield Label(str(self.path.resolve()), classes="hint")
            yield Input(placeholder="Passphrase", password=True, id="pw")
            if self.new:
                yield Input(placeholder="Repeat passphrase", password=True, id="pw2")
                yield Label("Everything you store is encrypted with this passphrase. "
                            "It cannot be recovered if you forget it.", classes="hint")
            if self.error:
                yield Label(self.error, classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Quit", id="cancel")
                yield Button("Create" if self.new else "Unlock", variant="primary", id="ok")

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        pw = self.query_one("#pw", Input).value
        if self.new and pw != self.query_one("#pw2", Input).value:
            self.app.notify("The passphrases do not match", severity="error")
            return
        if len(pw) < 4:
            self.app.notify("Passphrase too short", severity="error")
            return
        self.dismiss(pw)


class SetupDialog(Dialog):
    """First run: identity and node."""

    def __init__(self, need_identity: bool, need_node: bool):
        super().__init__()
        self.need_identity, self.need_node = need_identity, need_node

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Welcome to Unseenet", classes="title")
            if self.need_identity:
                yield Label("Your identity is a key pair. The name is just a label others see.",
                            classes="hint")
                yield Input(placeholder="Display name, e.g. Andreas", id="display")
            if self.need_node:
                yield Label("Which node do you want to connect to?", classes="hint")
                yield Input(placeholder="xyz...abc.onion  (or host:port for testing)", id="node")
            with Horizontal(classes="buttons"):
                yield Button("Quit", id="cancel")
                yield Button("Continue", variant="primary", id="ok")

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        result = {}
        if self.need_identity:
            result["display"] = self.query_one("#display", Input).value.strip()
            if not result["display"]:
                self.app.notify("Please choose a display name", severity="error")
                return
        if self.need_node:
            result["node"] = self.query_one("#node", Input).value.strip()
            if not result["node"]:
                self.app.notify("Please enter a node address", severity="error")
                return
        self.dismiss(result)


class ComposeDialog(Dialog):
    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "send", "Send")]

    def __init__(self, group: GroupInfo, subject: str = "", quote: str = "", is_reply: bool = False):
        super().__init__()
        self.group, self.subject, self.quote, self.is_reply = group, subject, quote, is_reply

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            kind = "Reply in" if self.is_reply else "New post in"
            lock = "  ◈ encrypted" if self.group.type == "closed" else ""
            yield Label(f"{kind} {self.group.short}{lock}", classes="title")
            yield Input(value=self.subject, placeholder="Subject", id="subject")
            yield TextArea(self.quote, id="body")
            yield Label("Ctrl+S to send. Sending takes a moment: the post carries a small "
                        "proof-of-work.", classes="hint")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Send", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#body" if self.is_reply else "#subject").focus()

    @on(Button.Pressed, "#ok")
    def action_send(self) -> None:
        subject = self.query_one("#subject", Input).value.strip()
        body = self.query_one("#body", TextArea).text
        if not subject or not body.strip():
            self.app.notify("Subject and text are required", severity="error")
            return
        self.dismiss((subject, body))


class CreateGroupDialog(Dialog):
    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Create a group", classes="title")
            yield Input(placeholder="Name, e.g. dk.snak (lowercase, dots)", id="name")
            yield Select([("Open - anyone can read and post", "open"),
                          ("Moderated - posts need a moderator", "moderated"),
                          ("Channel - only you post", "channel"),
                          ("Closed - members only, encrypted", "closed")],
                         value="open", allow_blank=False, id="type")
            yield Input(placeholder="Title (optional; keep it vague for closed groups)", id="title")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="ok")

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        name = self.query_one("#name", Input).value.strip().lower()
        if not name:
            self.app.notify("A name is required", severity="error")
            return
        self.dismiss((name, self.query_one("#type", Select).value,
                      self.query_one("#title", Input).value.strip()))


class InputDialog(Dialog):
    def __init__(self, title: str, hint: str, placeholder: str, value: str = ""):
        super().__init__()
        self.title_, self.hint, self.placeholder, self.value = title, hint, placeholder, value

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_, classes="title")
            yield Label(self.hint, classes="hint")
            yield Input(value=self.value, placeholder=self.placeholder, id="value")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("OK", variant="primary", id="ok")

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        value = self.query_one("#value", Input).value.strip()
        self.dismiss(value or None)


class InfoDialog(Dialog):
    def __init__(self, title: str, text: str):
        super().__init__()
        self.title_, self.text = title, text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_, classes="title")
            yield Input(value=self.text, id="value")   # an Input so it can be selected and copied
            with Horizontal(classes="buttons"):
                yield Button("Close", variant="primary", id="cancel")


class BrowseDialog(Dialog):
    """All groups on the node; Enter toggles subscription."""

    def __init__(self, groups: list[GroupInfo]):
        super().__init__()
        self.groups = groups

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Groups on this node", classes="title")
            yield Label("Enter: subscribe / unsubscribe.  Esc: close.", classes="hint")
            items = [ListItem(Label(self._label(g)), id=f"g{i}") for i, g in enumerate(self.groups)]
            if not items:
                items = [ListItem(Label("No groups yet - press c in the main view to create one."))]
            yield ListView(*items, id="browse-list")
            with Horizontal(classes="buttons"):
                yield Button("Close", variant="primary", id="cancel")

    @staticmethod
    def _label(g: GroupInfo) -> str:
        mark = "[x]" if g.subscribed else "[ ]"
        return f"{mark} {g.short:28} {g.description}"

    @on(ListView.Selected)
    def _toggle(self, event: ListView.Selected) -> None:
        if not event.item.id:
            return
        g = self.groups[int(event.item.id[1:])]
        g.subscribed = not g.subscribed
        self.app.session.subscribe(g.group_id, g.subscribed)
        event.item.query_one(Label).update(self._label(g))

    def action_cancel(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(True)


# ======================================================================
# Main app
# ======================================================================

class UnseenetApp(App):
    TITLE = "unseenet"
    CSS = CSS
    BINDINGS = [
        Binding("n", "new_post", "New post"),
        Binding("r", "reply", "Reply"),
        Binding("g", "browse", "Groups"),
        Binding("c", "create_group", "Create"),
        Binding("i", "invite", "Invite"),
        Binding("j", "join", "Join", show=False),
        Binding("k", "show_key", "My key"),
        Binding("f5", "refresh", "Refresh"),
        Binding("ctrl+r", "refresh", "Refresh", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, vault_path: Path):
        super().__init__()
        self.vault_path = vault_path
        self.session: Session | None = None
        self.groups: dict[str, GroupInfo] = {}
        self.current_group: str | None = None
        self.messages: dict[str, Message] = {}
        self.current_message: Message | None = None

    # --- layout ---
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="groups-pane"):
                yield Static("Groups", id="groups-title")
                yield ListView(id="groups")
            with Vertical():
                yield Static("Select a group", id="threads-title")
                yield DataTable(id="threads", cursor_type="row", zebra_stripes=True)
                with VerticalScroll(id="article"):
                    yield Static("", id="article-head")
                    yield Static("", id="article-body")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#threads", DataTable)
        table.add_column(" ", key="flag", width=2)
        table.add_column("Subject", key="subject", width=44)
        table.add_column("From", key="from", width=20)
        table.add_column("Date", key="date", width=16)
        self.start()

    def set_status(self, text: str) -> None:
        try:
            self.query_one("#status", Static).update(text)
        except Exception:  # noqa: BLE001  (before mount)
            pass

    # --- startup ---
    @work(exclusive=True, group="startup")
    async def start(self) -> None:
        passphrase = os.environ.get("UNSEENET_PASSPHRASE")
        error = ""
        kdf = {"ops": 1, "mem": 8192 * 1024} if os.environ.get("UNSEENET_INSECURE_FAST_KDF") == "1" else {}
        while self.session is None:
            if not passphrase:
                passphrase = await self.push_screen_wait(UnlockDialog(self.vault_path, error))
                if passphrase is None:
                    self.exit()
                    return
            self.set_status("Unlocking vault ...")
            try:
                vault = await asyncio.to_thread(Vault.open, self.vault_path, passphrase, **kdf)
                self.session = Session(vault, status=self.set_status)
            except VaultError as exc:
                error, passphrase = str(exc), None
        s = self.session
        if not s.has_identity() or not s.node:
            result = await self.push_screen_wait(SetupDialog(not s.has_identity(), not s.node))
            if result is None:
                self.exit()
                return
            if "display" in result:
                name = result["display"].lower().replace(" ", "-")
                await asyncio.to_thread(s.new_identity, name, result["display"])
            if "node" in result:
                await asyncio.to_thread(s.add_node, result["node"])
        ident = s.identity()
        self.sub_title = f"{s.display_name()} ({ident.fingerprint[:4]})  -  {s.node}"
        self.refresh_groups()
        self.set_interval(REFRESH_SECONDS, self.action_refresh)

    # --- groups ---
    @work(exclusive=True, group="groups")
    async def refresh_groups(self) -> None:
        s = self.session
        try:
            available = {g.group_id: g for g in await s.list_groups()}
        except (SessionError, OSError, ConnectionError) as exc:
            self.set_status(f"Cannot reach node: {exc}")
            return
        groups = {}
        for gid in s.data["subscribed"]:
            g = available.get(gid) or GroupInfo(gid, "(not on this node)")
            g.subscribed = True
            g.type = s.group_entry(gid).get("type") or g.type
            groups[gid] = g
        self.groups = groups
        for gid in groups:
            try:
                await s.fetch_group(gid)
                groups[gid].type = s.group_entry(gid).get("type")
            except (SessionError, OSError, ConnectionError):
                pass
        await self._render_groups()
        if self.current_group in groups:
            self._render_threads()
        elif groups and self.current_group is None:
            self.select_group(next(iter(groups)))
        if not groups:
            self.query_one("#threads-title", Static).update(
                "No groups yet - press g to browse the node's groups, or c to create one")
        self.set_status(f"{len(available)} groups on node, {len(groups)} subscribed")

    async def _render_groups(self) -> None:
        lv = self.query_one("#groups", ListView)
        index = lv.index
        await lv.clear()
        for gid, g in self.groups.items():
            unread = self.session.unread_count(gid)
            lock = "◈ " if g.type == "closed" else "  "
            label = Label(f"{lock}{g.short}" + (f" ({unread})" if unread else ""),
                          classes="unread" if unread else "")
            await lv.append(ListItem(label, name=gid))
        if index is not None and index < len(self.groups):
            lv.index = index

    @on(ListView.Selected, "#groups")
    def _group_selected(self, event: ListView.Selected) -> None:
        if event.item.name:
            self.select_group(event.item.name)

    @work(exclusive=True, group="fetch")
    async def select_group(self, gid: str) -> None:
        self.current_group = gid
        self.current_message = None
        self.query_one("#threads-title", Static).update(f"{self.groups[gid].short} - loading ...")
        try:
            await self.session.fetch_group(gid)
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(str(exc), severity="error")
        self.groups[gid].type = self.session.group_entry(gid).get("type")
        self._render_threads()
        self.query_one("#threads", DataTable).focus()

    # --- threads ---
    def _threaded(self, msgs: list[Message]) -> list[tuple[Message, int]]:
        by_id = {m.message_id: m for m in msgs}
        threads: dict[str, list[Message]] = {}
        for m in msgs:
            root = next((r for r in m.references if r in by_id), m.message_id)
            threads.setdefault(root, []).append(m)
        out = []
        for root, items in sorted(threads.items(),
                                  key=lambda kv: max(x.number for x in kv[1]), reverse=True):
            for m in sorted(items, key=lambda x: x.number):
                depth = 0 if m.message_id == root else min(len(m.references), 4)
                out.append((m, depth))
        return out

    def _render_threads(self) -> None:
        gid = self.current_group
        s = self.session
        msgs = sorted(s.cache.get(gid, {}).values(), key=lambda m: m.number)
        table = self.query_one("#threads", DataTable)
        keep = self.current_message.message_id if self.current_message else None
        table.clear()
        self.messages = {}
        for m, depth in self._threaded(msgs):
            self.messages[m.message_id] = m
            flag = "●" if not s.is_read(m) else " "
            subject = ("  " * (depth - 1) + "└ " if depth else "") + (m.subject or "(no subject)")
            if m.encrypted and m.readable:
                subject = "◈ " + subject
            date = m.date.astimezone().strftime("%d %b %H:%M") if m.date else ""
            table.add_row(flag, subject, f"{m.from_name} ({m.author_fp})", date, key=m.message_id)
        self._render_title()
        if keep in self.messages:
            table.move_cursor(row=table.get_row_index(keep))

    def _render_title(self) -> None:
        gid = self.current_group
        if not gid:
            return
        g = self.groups.get(gid)
        total = len(self.session.cache.get(gid, {}))
        unread = self.session.unread_count(gid)
        kind = {"closed": "◈ closed, encrypted", "moderated": "moderated",
                "channel": "channel", "open": "open"}.get(g.type if g else None, "")
        self.query_one("#threads-title", Static).update(
            f"{g.short if g else gid}  ·  {kind}  ·  {total} posts, {unread} unread")

    @on(DataTable.RowHighlighted, "#threads")
    def _row(self, event: DataTable.RowHighlighted) -> None:
        msg = self.messages.get(event.row_key.value)
        if msg is None:
            return
        self.current_message = msg
        date = msg.date.astimezone().strftime("%A %d %B %Y %H:%M") if msg.date else ""
        head = (f"[b]{msg.subject}[/b]\nFrom: {msg.from_name}  ·  key {msg.author_key[:24]}…  "
                f"({msg.author_fp})\nDate: {date}" + ("\n◈ end-to-end encrypted" if msg.encrypted else ""))
        self.query_one("#article-head", Static).update(head)
        body = msg.body if msg.readable else (msg.error or msg.subject)
        self.query_one("#article-body", Static).update("\n" + body)
        if not self.session.is_read(msg):
            self.session.mark_read(msg, save=False)
            self._save_soon()
            table = self.query_one("#threads", DataTable)
            table.update_cell(msg.message_id, "flag", " ")
            self._render_title()

    @work(exclusive=True, group="save")
    async def _save_soon(self) -> None:
        await asyncio.sleep(2)
        await asyncio.to_thread(self.session.save)
        await self._render_groups()

    # --- actions ---
    def _need_group(self) -> GroupInfo | None:
        if not self.current_group:
            self.notify("Select a group first", severity="warning")
            return None
        return self.groups[self.current_group]

    def action_new_post(self) -> None:
        g = self._need_group()
        if g:
            self.compose_post(g)

    def action_reply(self) -> None:
        g = self._need_group()
        m = self.current_message
        if not g or not m or not m.readable:
            self.notify("Select a post to reply to", severity="warning")
            return
        subject = m.subject if m.subject.lower().startswith("re:") else f"Re: {m.subject}"
        quote = f"{m.from_name} wrote:\n" + "".join(f"> {ln}\n" for ln in m.body.rstrip().split("\n")) + "\n"
        self.compose_post(g, subject, quote, references=[*m.references, m.message_id])

    @work(group="post")
    async def compose_post(self, g: GroupInfo, subject: str = "", quote: str = "",
                           references: list[str] | None = None) -> None:
        result = await self.push_screen_wait(ComposeDialog(g, subject, quote, bool(references)))
        if not result:
            return
        subject, body = result
        self.set_status("Sending (computing postage) ...")
        try:
            await self.session.post(g.group_id, subject, body, references)
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(f"Not sent: {exc}", severity="error", timeout=8)
            return
        self.notify("Sent")
        self.select_group(g.group_id)

    @work(group="dialog")
    async def action_browse(self) -> None:
        self.set_status("Fetching group list ...")
        try:
            groups = await self.session.list_groups()
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(str(exc), severity="error")
            return
        self.set_status("")
        await self.push_screen_wait(BrowseDialog(groups))
        self.refresh_groups()

    @work(group="dialog")
    async def action_create_group(self) -> None:
        result = await self.push_screen_wait(CreateGroupDialog())
        if not result:
            return
        name, gtype, title = result
        self.set_status(f"Creating {name} ...")
        try:
            gid = await self.session.create_group(name, gtype, title)
        except (SessionError, ValueError, OSError, ConnectionError) as exc:
            self.notify(f"Could not create group: {exc}", severity="error", timeout=8)
            return
        self.notify(f"Created {gid}")
        self.current_group = gid
        self.refresh_groups()

    @work(group="dialog")
    async def action_invite(self) -> None:
        g = self._need_group()
        if not g:
            return
        entry = self.session.group_entry(g.group_id)
        if g.type != "closed" or not entry.get("owner"):
            self.notify("You can only invite to closed groups you own", severity="warning")
            return
        key = await self.push_screen_wait(InputDialog(
            f"Invite to {g.short}", "Paste the new member's key (they find it with k).",
            "ed25519:..."))
        if not key:
            return
        try:
            await self.session.invite(g.group_id, key)
        except Exception as exc:  # noqa: BLE001
            self.notify(f"Invite failed: {exc}", severity="error", timeout=8)
            return
        await self.push_screen_wait(InfoDialog(
            "Invitation sent - share this with them", f"unseenet:join?g={g.group_id}&n={self.session.node}"))

    @work(group="dialog")
    async def action_join(self) -> None:
        value = await self.push_screen_wait(InputDialog(
            "Join a group", "Paste a group ID or an unseenet:join link.", "dk.snak@... or unseenet:join?g=..."))
        if not value:
            return
        gid = value
        if value.startswith("unseenet:join?"):
            params = dict(p.split("=", 1) for p in value.split("?", 1)[1].split("&") if "=" in p)
            gid = params.get("g", "")
        try:
            self.session.subscribe(gid)
        except ValueError:
            self.notify("That is not a valid group ID", severity="error")
            return
        self.current_group = gid
        self.refresh_groups()

    def action_show_key(self) -> None:
        self.push_screen(InfoDialog("Your key - give it to a group owner to be invited",
                                    self.session.identity().key_text))

    def action_refresh(self) -> None:
        if self.session:
            self.refresh_groups()

    async def action_quit(self) -> None:
        if self.session:
            await asyncio.to_thread(self.session.save)
            await self.session.close()
        self.exit()


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="unseenet-tui", description="Unseenet terminal client.")
    p.add_argument("--vault", default=str(default_vault_path()), help="encrypted vault file")
    args = p.parse_args(argv)
    UnseenetApp(Path(args.vault)).run()


if __name__ == "__main__":
    main()
