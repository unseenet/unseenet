"""Unseenet TUI client (Textual).

    unseenet-tui [--vault unseenet.vault]

Left: your groups with unread counts. Right: threads in the selected group
and the selected article. Everything is stored in the encrypted vault.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from rich.text import Text
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widgets import (Button, DataTable, Footer, Header, Input, Label, Select, Static,
                             TextArea, Tree)

from .. import __version__
from ..core.vault import Vault, VaultError
from ..core import crypto
from ..core.groups import personal_inbox_id
from .session import (MAX_SIG_LINES, SIG_SEPARATOR, GroupInfo, Message, Session, SessionError,
                      default_vault_path, split_signature)

REFRESH_SECONDS = 30
CONTACT = "contact:"          # tree data prefix for a contact's conversation


def group_name_problem(name: str) -> str | None:
    """Why a group name is not valid (UN-RFC 0004 section 1), or None."""
    if len(name) > 128:
        return "at most 128 characters"
    bad = sorted({c for c in name if not re.match(r"[a-z0-9.+_-]", c)})
    if bad:
        shown = " ".join("space" if c == " " else repr(c) for c in bad)
        return f"these characters are not allowed: {shown}"
    if name.startswith(".") or name.endswith(".") or ".." in name:
        return "a dot must sit between two parts"
    if any(not part[0].isalnum() for part in name.split(".")):
        return "each part must start with a letter or digit"
    return None


def by_hierarchy(groups: list[GroupInfo]) -> list[tuple[str, list[GroupInfo]]]:
    """Group by the first part of the name, as Usenet hierarchies (dk.*, comp.*, ...).

    A hierarchy with a single group is returned as ('', [group]) so it can be shown
    without a folder of its own.
    """
    buckets: dict[str, list[GroupInfo]] = {}
    for g in groups:
        name = g.group_id.rpartition("@")[0]
        buckets.setdefault(name.split(".", 1)[0], []).append(g)
    out = []
    for top in sorted(buckets):
        items = sorted(buckets[top], key=lambda g: (g.group_id.rpartition("@")[0], g.group_id))
        out.append((top if len(items) > 1 else "", items))
    return out

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
.dialog.compose { width: 96%; height: 94%; max-height: 100%; }
.dialog.compose #body { height: 1fr; margin-bottom: 1; }
.dialog .buttons { height: auto; align-horizontal: right; }
.dialog Button { margin-left: 1; }
.dialog .hint { color: $text-muted; }
.dialog .error { color: $error; }
#browse-tree { height: 22; }
#groups { padding: 0 1; }
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

    def __init__(self, group: GroupInfo, subject: str = "", quote: str = "", is_reply: bool = False,
                 heading: str | None = None, signature: str = ""):
        super().__init__()
        self.group, self.subject, self.quote, self.is_reply = group, subject, quote, is_reply
        self.heading, self.signature = heading, signature

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog compose"):
            kind = "Reply in" if self.is_reply else "New post in"
            lock = "  ◈ encrypted" if self.group.type == "closed" else ""
            yield Label(self.heading or f"{kind} {self.group.short}{lock}", classes="title",
                        markup=False)
            yield Input(value=self.subject, placeholder="Subject", id="subject")
            text = self.quote + (("\n" if self.quote else "\n\n") + SIG_SEPARATOR + self.signature
                                 if self.signature else "")
            yield TextArea(text, id="body", soft_wrap=True)
            yield Label("Ctrl+S to send. Sending takes a moment: the post carries a small "
                        "proof-of-work.", classes="hint")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Send", variant="primary", id="ok")

    def on_mount(self) -> None:
        body = self.query_one("#body", TextArea)
        # the cursor goes below the quote, above the signature
        body.move_cursor((self.quote.count("\n"), 0) if self.signature else body.document.end)
        if self.is_reply:
            body.focus()
        else:
            self.query_one("#subject").focus()

    @on(Button.Pressed, "#ok")
    def action_send(self) -> None:
        subject = self.query_one("#subject", Input).value.strip()
        body = self.query_one("#body", TextArea).text
        if not subject or not split_signature(body)[0].strip():
            self.app.notify("Subject and text are required", severity="error")
            return
        self.dismiss((subject, body))


class SignatureDialog(Dialog):
    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "save", "Save")]

    def __init__(self, template: str):
        super().__init__()
        self.template = template or "{name}  ·  {key}"

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Your signature", classes="title")
            yield Label(f"Added below '-- ' at the end of your posts. At most {MAX_SIG_LINES} lines. "
                        "{name}, {key} and {fp} are filled in. Leave empty for none.",
                        classes="hint", markup=False)
            yield TextArea(self.template, id="sig", soft_wrap=True)
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#sig", TextArea).styles.height = MAX_SIG_LINES + 2
        self.query_one("#sig").focus()

    @on(Button.Pressed, "#ok")
    def action_save(self) -> None:
        text = self.query_one("#sig", TextArea).text
        if len([ln for ln in text.strip("\n").split("\n") if text.strip()]) > MAX_SIG_LINES:
            self.app.notify(f"At most {MAX_SIG_LINES} lines, please - that was the rule on Usenet too",
                            severity="warning")
            return
        self.dismiss(text)


GROUP_NAME_HELP = ("Lowercase letters, digits and - _ +, parts separated by dots, "
                   "e.g. dk.snak or andlo.test. The first part is the hierarchy.")


class CreateGroupDialog(Dialog):
    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Create a group", classes="title")
            yield Input(placeholder="Name, e.g. dk.snak", id="name")
            yield Label(GROUP_NAME_HELP, id="name-help", classes="hint", markup=False)
            yield Select([("Open - anyone can read and post", "open"),
                          ("Moderated - posts need a moderator", "moderated"),
                          ("Channel - only you post", "channel"),
                          ("Closed - members only, encrypted", "closed"),
                          ("Inbox - anyone writes, only you read", "inbox")],
                         value="open", allow_blank=False, id="type")
            yield Select([("Replicated to other nodes", "everywhere"),
                          ("Only on this node (local)", "local")],
                         value="everywhere", allow_blank=False, id="where")
            yield Input(placeholder="Title (optional; keep it vague for closed groups)", id="title")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="ok")

    @on(Input.Changed, "#name")
    def _check_name(self, event: Input.Changed) -> None:
        help_label = self.query_one("#name-help", Label)
        name = event.value.strip().lower()
        problem = group_name_problem(name) if name else None
        help_label.update(f"Not valid yet: {problem}" if problem else GROUP_NAME_HELP)
        help_label.set_class(bool(problem), "error")

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        name = self.query_one("#name", Input).value.strip().lower()
        problem = group_name_problem(name) if name else "a name is required"
        if problem:                       # stay open, keep what was typed
            self.app.notify(f"Group name: {problem}", severity="error")
            self.query_one("#name", Input).focus()
            return
        self.dismiss((name, self.query_one("#type", Select).value,
                      self.query_one("#title", Input).value.strip(),
                      self.query_one("#where", Select).value == "local"))


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


class ConfirmDialog(Dialog):
    def __init__(self, title: str, text: str, confirm: str = "OK", danger: bool = False):
        super().__init__()
        self.title_, self.text, self.confirm, self.danger = title, text, confirm, danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_, classes="title", markup=False)
            yield Static(self.text, markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(self.confirm, variant="error" if self.danger else "primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#cancel").focus()

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.dismiss(True)


class NodeInfoDialog(Dialog):
    """UN-RFC 0011 node information; can start a message to the operator."""

    def __init__(self, info: dict, address: str):
        super().__init__()
        self.info, self.address = info, address

    def compose(self) -> ComposeResult:
        i, p = self.info, self.info.get("policy", {})
        can_write = bool(i.get("contact") and i.get("operator"))
        lines = [f"Address:   {self.address}"]
        if not i:
            lines.append("This node publishes no information about itself.")
        else:
            lines += [f"Name:      {i.get('name', '')}",
                      f"Software:  {i.get('software', '')}"]
            if i.get("description"):
                lines.append(f"About:     {i['description']}")
            lines += ["",
                      f"New groups:       {p.get('new_groups', '?')}",
                      f"Kept for:         {p.get('retention_days', '?')} days",
                      f"Minimum postage:  {p.get('min_pow', '?')} bits",
                      f"Logs:             {p.get('logging', '?')}",
                      "",
                      ("Operator:  " + i["operator"]) if i.get("operator") else "No operator contact given."]
        with Vertical(classes="dialog"):
            yield Label("About this node", classes="title")
            yield Static("\n".join(lines), markup=False)
            yield Label("The node states this itself; the protocol does not enforce it.", classes="hint")
            with Horizontal(classes="buttons"):
                yield Button("Close", id="cancel")
                if can_write:
                    yield Button("Write to operator", variant="primary", id="ok")

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.dismiss(True)


class BrowseDialog(Dialog):
    """All groups on the node, by hierarchy; Enter toggles subscription."""

    def __init__(self, groups: list[GroupInfo]):
        super().__init__()
        self.groups = groups

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Groups on this node", classes="title")
            yield Label("Enter: subscribe or unsubscribe a group, open or close a "
                        "hierarchy.  Esc: close.", classes="hint")
            tree: Tree = Tree("groups", id="browse-tree")
            tree.show_root = False
            expand = len(self.groups) <= 15
            for top, items in by_hierarchy(self.groups):
                parent = tree.root
                if top:
                    subs = sum(1 for g in items if g.subscribed)
                    parent = tree.root.add(Text(f"{top}.*   {len(items)} groups"
                                                + (f", {subs} subscribed" if subs else "")),
                                           expand=expand or subs > 0)
                for g in items:
                    parent.add_leaf(self._label(g), data=g)
            if not self.groups:
                tree.root.add_leaf(Text("No groups yet - press c in the main view to create one."))
            yield tree
            with Horizontal(classes="buttons"):
                yield Button("Close", variant="primary", id="cancel")

    @staticmethod
    def _label(g: GroupInfo) -> Text:
        mark = "[x]" if g.subscribed else "[ ]"
        kind = {"closed": " ◈", "inbox": " ✉"}.get(g.type or "", "")
        return Text(f"{mark} {g.short}{kind}   {g.description}")

    def on_mount(self) -> None:
        self.query_one("#browse-tree", Tree).focus()

    @on(Tree.NodeSelected, "#browse-tree")
    def _toggle(self, event: Tree.NodeSelected) -> None:
        g = event.node.data
        if not isinstance(g, GroupInfo):
            return
        g.subscribed = not g.subscribed
        self.app.session.subscribe(g.group_id, g.subscribed)
        event.node.set_label(self._label(g))

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
        Binding("m", "message", "Message"),
        Binding("o", "node_info", "Node"),
        Binding("k", "show_key", "My key"),
        Binding("s", "signature", "Signature", show=False),
        Binding("a", "add_contact", "Add contact", show=False),
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
        self._inbox_ready = False

    # --- layout ---
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="groups-pane"):
                yield Static("Groups", id="groups-title")
                yield Tree("groups", id="groups")
            with Vertical():
                yield Static("Select a group", id="threads-title", markup=False)
                yield DataTable(id="threads", cursor_type="row", zebra_stripes=True)
                with VerticalScroll(id="article"):
                    yield Static("", id="article-head")
                    yield Static("", id="article-body", markup=False)
        yield Static("", id="status", markup=False)
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
                s.new_identity(name, result["display"])
            if "node" in result:
                s.add_node(result["node"])
        ident = s.identity()
        self.sub_title = f"{s.display_name()} ({ident.fingerprint[:4]})  -  {s.node}"
        await self.show_offline()
        self.refresh_groups()
        self.set_interval(REFRESH_SECONDS, self.action_refresh)

    # --- groups ---
    def _groups_from_vault(self, available: dict[str, GroupInfo] | None = None) -> dict[str, GroupInfo]:
        groups = {}
        for gid in self.session.data["subscribed"]:
            entry = self.session.group_entry(gid)
            if available is not None and gid in available:
                g = available[gid]
            else:
                g = GroupInfo(gid, entry.get("title", ""))
                if available is not None:
                    g.description = "(not on this node)"
            g.subscribed = True
            g.type = entry.get("type") or g.type
            groups[gid] = g
        return groups

    async def show_offline(self) -> None:
        """Show what is in the encrypted local cache before any network access."""
        loaded = self.session.load_offline()
        self.groups = self._groups_from_vault()
        await self._render_groups()
        if self.groups:
            self.current_group = next(iter(self.groups))
            self._render_threads()
        self.set_status(f"{loaded} saved posts available offline - connecting ...")

    @work(exclusive=True, group="groups")
    async def refresh_groups(self) -> None:
        s = self.session
        try:
            available = {g.group_id: g for g in await s.list_groups()}
        except (SessionError, OSError, ConnectionError) as exc:
            self.set_status(f"Offline ({exc}) - showing saved posts")
            return
        if not self._inbox_ready:
            try:
                await s.ensure_inbox()
                self._inbox_ready = True
                available = {g.group_id: g for g in await s.list_groups()}
            except (SessionError, OSError, ConnectionError) as exc:
                self.set_status(f"Could not set up your inbox: {exc}")
        groups = self._groups_from_vault(available)
        self.groups = groups
        for gid in groups:
            try:
                await s.fetch_group(gid)
                groups[gid].type = s.group_entry(gid).get("type")
            except (SessionError, OSError, ConnectionError):
                pass
        await self._render_groups()
        if self.current_group in groups or self._current_contact():
            self._render_threads()
        elif groups:
            self.select_group(next(iter(groups)))
        if not groups:
            self.query_one("#threads-title", Static).update(
                "No groups yet - press g to browse the node's groups, or c to create one")
        self.set_status(f"{len(available)} groups on node, {len(groups)} subscribed")

    async def _render_groups(self) -> None:
        tree = self.query_one("#groups", Tree)
        tree.show_root = False
        def folder_key(node) -> str:
            return str(node.label).split(" (")[0].split(".*")[0]
        was_open = {folder_key(n) for n in tree.root.children if n.children and n.is_expanded}
        known = {folder_key(n) for n in tree.root.children if n.children}
        tree.clear()

        def label(g: GroupInfo) -> Text:
            unread = self.session.unread_count(g.group_id)
            text = Text(self._group_label(g) + (f" ({unread})" if unread else ""))
            if unread:
                text.stylize("bold")
            return text

        select = None
        groups = list(self.groups.values())
        mine = [g for g in groups if g.group_id == self.session.my_inbox]
        for g in mine:                                   # private messages always first
            node = tree.root.add_leaf(label(g), data=g.group_id)
            select = node if g.group_id == self.current_group else select
        contacts = self.session.contacts()
        if contacts:
            total = sum(self.session.unread_from(k) for k, _ in contacts)
            folder = Text("Contacts" + (f" ({total})" if total else ""))
            if total:
                folder.stylize("bold")
            cnode = tree.root.add(folder, expand="Contacts" in was_open or "Contacts" not in known)
            for key, name in contacts:
                unread = self.session.unread_from(key)
                text = Text(f"• {name}" + (f" ({unread})" if unread else ""))
                if unread:
                    text.stylize("bold")
                leaf = cnode.add_leaf(text, data=CONTACT + key)
                select = leaf if self.current_group == CONTACT + key else select
        for top, items in by_hierarchy([g for g in groups if g not in mine]):
            parent = tree.root
            if top:
                unread = sum(self.session.unread_count(g.group_id) for g in items)
                folder = Text(f"{top}.*" + (f" ({unread})" if unread else ""))
                if unread:
                    folder.stylize("bold")
                parent = tree.root.add(folder, expand=top in was_open or top not in known)
            for g in items:
                node = parent.add_leaf(label(g), data=g.group_id)
                select = node if g.group_id == self.current_group else select
        if select is not None:
            tree.move_cursor(select)

    def _group_label(self, g: GroupInfo) -> str:
        if g.group_id == self.session.my_inbox:
            return "✉ Private messages"
        mark = {"closed": "◈ ", "inbox": "✉ "}.get(g.type or "", "  ")
        return f"{mark}{g.short}"

    @on(Tree.NodeSelected, "#groups")
    def _group_selected(self, event: Tree.NodeSelected) -> None:
        if isinstance(event.node.data, str):
            self.select_group(event.node.data)

    @work(exclusive=True, group="fetch")
    async def select_group(self, gid: str) -> None:
        self.current_group = gid
        self.current_message = None
        if gid.startswith(CONTACT):
            try:
                await self.session.fetch_group(self.session.my_inbox)
            except (SessionError, OSError, ConnectionError) as exc:
                self.set_status(f"Offline ({exc}) - showing saved messages")
            self._render_threads()
            self.query_one("#threads", DataTable).focus()
            return
        self.query_one("#threads-title", Static).update(f"{self.groups[gid].short} - loading ...")
        try:
            await self.session.fetch_group(gid)
        except SessionError as exc:
            if "removed by its owner" in str(exc):
                self.notify(f"{self.groups[gid].short} was removed by its owner. "
                            "Use 'Unsubscribe from group' (Ctrl+P) to forget it.",
                            severity="warning", timeout=10)
            else:
                self.set_status(f"{exc}")
        except (OSError, ConnectionError) as exc:
            self.set_status(f"Offline ({exc}) - showing saved posts")
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
        if gid and gid.startswith(CONTACT):
            rows = [(m, 0) for m in s.conversation(gid[len(CONTACT):])]   # oldest first, like a chat
        else:
            msgs = sorted(s.cache.get(gid, {}).values(), key=lambda m: m.number)
            rows = self._threaded(msgs)
        table = self.query_one("#threads", DataTable)
        keep = self.current_message.message_id if self.current_message else None
        table.clear()
        self.messages = {}
        for m, depth in rows:
            self.messages[m.message_id] = m
            flag = "●" if not s.is_read(m) else " "
            subject = ("  " * (depth - 1) + "└ " if depth else "") + (m.subject or "(no subject)")
            if m.private:
                subject = "✉ " + subject
            elif m.encrypted and m.readable:
                subject = "◈ " + subject
            date = m.date.astimezone().strftime("%d %b %H:%M") if m.date else ""
            table.add_row(flag, Text(subject), Text(self._who(m)), date, key=m.message_id)
        self._render_title()
        if keep in self.messages:
            table.move_cursor(row=table.get_row_index(keep))
        elif gid and gid.startswith(CONTACT) and rows:
            table.move_cursor(row=len(rows) - 1)                  # newest at the bottom

    def _who(self, m: Message) -> str:
        if m.from_name == "You" and m.author_key == self.session.identity().key_text:
            return "You"
        petname = self.session.contact_name(m.author_key)
        if petname:
            return f"{petname} ✓ ({m.author_fp})"         # your own name for a key you know
        return f"{m.from_name} ({m.author_fp})"

    def _render_title(self) -> None:
        gid = self.current_group
        if not gid:
            return
        if gid.startswith(CONTACT):
            key = gid[len(CONTACT):]
            msgs = self.session.conversation(key)
            self.query_one("#threads-title", Static).update(
                f"✉ {self.session.contact_name(key) or key[:20]}  ·  {len(msgs)} messages, "
                f"{self.session.unread_from(key)} unread  ·  only the two of you can read them")
            return
        g = self.groups.get(gid)
        total = len(self.session.cache.get(gid, {}))
        unread = self.session.unread_count(gid)
        kind = {"closed": "◈ closed, encrypted", "moderated": "moderated", "channel": "channel",
                "open": "open", "inbox": "✉ inbox - only the owner can read"}.get(g.type if g else None, "")
        name = self._group_label(g).strip() if g else gid
        self.query_one("#threads-title", Static).update(
            f"{name}  ·  {kind}  ·  {total} posts, {unread} unread")

    @on(DataTable.RowHighlighted, "#threads")
    def _row(self, event: DataTable.RowHighlighted) -> None:
        msg = self.messages.get(event.row_key.value)
        if msg is None:
            return
        self.current_message = msg
        date = msg.date.astimezone().strftime("%A %d %B %Y %H:%M") if msg.date else ""
        if msg.private and msg.readable and not msg.sender_key:
            who = "anonymous (the sender did not identify themselves)"
        else:
            petname = self.session.contact_name(msg.author_key)
            who = (f"{escape(msg.from_name)}  ·  key {escape(msg.author_key[:24])}…  ({msg.author_fp})"
                   + ("  ·  verified" if msg.sender_key else "")
                   + (f"  ·  your contact [b]{escape(petname)}[/b]" if petname else ""))
        note = ("\n✉ private message - only you can read it" if msg.private
                else "\n◈ end-to-end encrypted" if msg.encrypted else "")
        head = f"[b]{escape(msg.subject)}[/b]\nFrom: {who}\nDate: {date}{note}"
        self.query_one("#article-head", Static).update(head)
        if msg.readable:
            text, sig = split_signature(msg.body)
            body = Text("\n" + text)
            if sig is not None:
                body.append(SIG_SEPARATOR + sig, style="dim")
        else:
            body = Text("\n" + (msg.error or msg.subject))
        self.query_one("#article-body", Static).update(body)
        if not self.session.is_read(msg):
            self.session.mark_read(msg, save=False)
            self._save_soon()
            table = self.query_one("#threads", DataTable)
            table.update_cell(msg.message_id, "flag", " ")
            self._render_title()

    @work(exclusive=True, group="save")
    async def _save_soon(self) -> None:
        await asyncio.sleep(2)
        self.session.save()
        await self._render_groups()

    # --- actions ---
    def _need_group(self) -> GroupInfo | None:
        if not self.current_group or self.current_group not in self.groups:
            self.notify("Select a group first", severity="warning")
            return None
        return self.groups[self.current_group]

    def _current_contact(self) -> str | None:
        gid = self.current_group or ""
        return gid[len(CONTACT):] if gid.startswith(CONTACT) else None

    def _write_to_contact(self, key: str, subject: str = "", quote: str = "",
                          references: list[str] | None = None) -> None:
        name = self.session.contact_name(key) or key[:20]
        owner = crypto.key_from_text(key)
        self.compose_private(personal_inbox_id(owner), f"Message to {name}", subject, quote,
                             owner_key=owner, references=references)

    def action_new_post(self) -> None:
        contact = self._current_contact()
        if contact:
            self._write_to_contact(contact)
            return
        g = self._need_group()
        if g:
            self.compose_post(g)

    def action_reply(self) -> None:
        contact = self._current_contact()
        m = self.current_message
        if contact:
            if not m:
                self._write_to_contact(contact)
                return
            subject = m.subject if m.subject.lower().startswith("re:") else f"Re: {m.subject}"
            self._write_to_contact(contact, subject, references=[*m.references, m.message_id])
            return
        g = self._need_group()
        if not g or not m or not m.readable:
            self.notify("Select a post to reply to", severity="warning")
            return
        subject = m.subject if m.subject.lower().startswith("re:") else f"Re: {m.subject}"
        text = split_signature(m.body)[0]          # never quote the signature
        quote = f"{m.from_name} wrote:\n" + "".join(f"> {ln}\n" for ln in text.rstrip().split("\n")) + "\n"
        if m.private:
            target = self.session.reply_target(m)
            if not target:
                self.notify("Anonymous message - there is nobody to reply to", severity="warning")
                return
            key = crypto.key_from_text(m.sender_key) if m.sender_key and not m.reply_inbox else None
            self.compose_private(target, f"Private reply to {m.from_name}", subject, quote,
                                 owner_key=key, references=[*m.references, m.message_id])
            return
        self.compose_post(g, subject, quote, references=[*m.references, m.message_id])

    @work(group="post")
    async def compose_private(self, target: str, heading: str, subject: str = "", quote: str = "",
                              owner_key: bytes | None = None,
                              references: list[str] | None = None) -> None:
        g = GroupInfo(target, type="inbox")
        result = await self.push_screen_wait(ComposeDialog(
            g, subject, quote, bool(references), heading=heading + "  ✉ only they can read it",
            signature=self.session.signature()))
        if not result:
            return
        subject, body = result
        self.set_status("Sending (computing postage) ...")
        try:
            await self.session.send_private(target, subject, body, owner_key=owner_key,
                                            references=references)
        except (SessionError, OSError, ConnectionError, ValueError) as exc:
            self.notify(f"Not sent: {exc}", severity="error", timeout=8)
            return
        self.notify("Private message sent")
        self.set_status("")
        if self._current_contact():
            self._render_threads()

    @work(group="dialog")
    async def action_message(self) -> None:
        m = self.current_message
        known = (m.sender_key or m.author_key) if m and m.readable else ""
        if m and m.private and not m.sender_key:
            known = ""
        key = await self.push_screen_wait(InputDialog(
            "Private message", "Paste the recipient's key (they find it with k). "
            "Only they will be able to read the message.", "ed25519:...", value=known))
        if not key:
            return
        try:
            owner = crypto.key_from_text(key)
        except crypto.CryptoError:
            self.notify("That is not a valid key", severity="error")
            return
        self.compose_private(personal_inbox_id(owner), f"Private message to {key[:20]}…",
                             owner_key=owner)

    @work(group="dialog")
    async def action_node_info(self) -> None:
        try:
            info = await self.session.node_info()
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(f"Cannot reach node: {exc}", severity="error")
            return
        if not await self.push_screen_wait(NodeInfoDialog(info, self.session.node or "")):
            return
        try:
            operator = crypto.key_from_text(info["operator"])
        except (KeyError, crypto.CryptoError):
            self.notify("The node gives no valid operator key", severity="error")
            return
        self.compose_private(info["contact"], f"Message to the operator of {info.get('name', 'this node')}",
                             owner_key=operator)

    @work(group="post")
    async def compose_post(self, g: GroupInfo, subject: str = "", quote: str = "",
                           references: list[str] | None = None) -> None:
        result = await self.push_screen_wait(ComposeDialog(g, subject, quote, bool(references),
                                                           signature=self.session.signature()))
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
        name, gtype, title, local = result
        self.set_status(f"Creating {name} ...")
        try:
            gid = await self.session.create_group(name, gtype, title, local=local)
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
        self.push_screen(InfoDialog("Your key - share it to get private messages or invitations",
                                    self.session.identity().key_text))

    def get_system_commands(self, screen):
        """Everything the keys do is also in the command palette (Ctrl+P)."""
        yield from super().get_system_commands(screen)
        if self.session is None:
            return
        commands = [
            ("New post", "Write a new post in the current group  [n]", self.action_new_post),
            ("Reply", "Reply to the selected post  [r]", self.action_reply),
            ("Private message", "Write privately to someone by their key  [m]", self.action_message),
            ("Browse groups", "See all groups on the node, subscribe or unsubscribe  [g]",
             self.action_browse),
            ("Create group", "Create an open, moderated, channel, closed or inbox group  [c]",
             self.action_create_group),
            ("Invite to closed group", "Give someone access to a closed group you own  [i]",
             self.action_invite),
            ("Join group", "Subscribe by group ID or unseenet:join link  [j]", self.action_join),
            ("Node information", "Who runs this node, its policy, write to the operator  [o]",
             self.action_node_info),
            ("Show my key", "Your key, to share for private messages and invitations  [k]",
             self.action_show_key),
            ("Edit signature", "The few lines added below '-- ' in your posts  [s]",
             self.action_signature),
            ("Add contact", "Give the selected author, or any key, a name of your own  [a]",
             self.action_add_contact),
            ("Rename contact", "Change the name of the selected contact", self.action_rename_contact),
            ("Remove contact", "Forget the selected contact (your messages stay)",
             self.action_remove_contact),
            ("Refresh", "Fetch new posts now  [F5]", self.action_refresh),
            ("Private messages", "Open your inbox", self.action_open_inbox),
            ("Mark group as read", "Mark every post in the current group as read",
             self.action_mark_all_read),
            ("Unsubscribe from group", "Stop following the current group and forget it locally",
             self.action_unsubscribe),
            ("Remove group from the network", "Delete a group you own from every node - final",
             self.action_remove_group),
        ]
        for title, help_text, callback in commands:
            yield SystemCommand(title, help_text, callback)

    @work(group="dialog")
    async def action_add_contact(self) -> None:
        m = self.current_message
        mine = self.session.identity().key_text
        key = m.author_key if m and m.readable and m.author_key and m.author_key != mine else ""
        key = await self.push_screen_wait(InputDialog(
            "Add contact", "The person's key. If you had a post by them selected, it is filled in.",
            "ed25519:...", value=key))
        if not key:
            return
        suggestion = self.session.contact_name(key) or (m.from_name if m and m.author_key == key else "")
        name = await self.push_screen_wait(InputDialog(
            "Name this contact", "A name of your own choosing. Only you see it, and nobody can "
            "pretend to be this contact under it: it is tied to the key.", "e.g. Sonia",
            value=suggestion))
        if not name:
            return
        try:
            self.session.add_contact(key.strip(), name)
        except (SessionError, crypto.CryptoError) as exc:
            self.notify(f"Not added: {exc}", severity="error")
            return
        self.notify(f"Added {name}")
        await self._render_groups()
        self._render_threads()

    @work(group="dialog")
    async def action_rename_contact(self) -> None:
        key = self._current_contact()
        if not key:
            self.notify("Select a contact first", severity="warning")
            return
        name = await self.push_screen_wait(InputDialog(
            "Rename contact", "", "Name", value=self.session.contact_name(key) or ""))
        if name:
            self.session.add_contact(key, name)
            await self._render_groups()
            self._render_title()

    @work(group="dialog")
    async def action_remove_contact(self) -> None:
        key = self._current_contact()
        if not key:
            self.notify("Select a contact first", severity="warning")
            return
        name = self.session.contact_name(key) or key[:20]
        if not await self.push_screen_wait(ConfirmDialog(
                f"Remove {name}?", "The contact is forgotten. Messages stay in Private messages.",
                "Remove")):
            return
        self.session.remove_contact(key)
        self.current_group = self.session.my_inbox
        await self._render_groups()
        self.select_group(self.session.my_inbox)

    @work(group="dialog")
    async def action_signature(self) -> None:
        text = await self.push_screen_wait(SignatureDialog(self.session.signature_template()))
        if text is None:
            return
        try:
            self.session.set_signature(text)
        except SessionError as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify("Signature saved" if text.strip() else "Signature removed")

    @work(group="dialog")
    async def action_unsubscribe(self) -> None:
        g = self._need_group()
        if not g:
            return
        if g.group_id == self.session.my_inbox:
            self.notify("Your private messages cannot be unsubscribed", severity="warning")
            return
        if not await self.push_screen_wait(ConfirmDialog(
                f"Unsubscribe from {g.short}?",
                "You stop following the group, and its saved posts are deleted from this "
                "computer. The group stays on the network; you can subscribe again with g.",
                "Unsubscribe")):
            return
        self.session.forget_group(g.group_id)
        self.current_group = None
        self.notify(f"Unsubscribed from {g.short}")
        self.refresh_groups()

    @work(group="dialog")
    async def action_remove_group(self) -> None:
        g = self._need_group()
        if not g:
            return
        if not self.session.group_entry(g.group_id).get("owner"):
            self.notify("Only the group's owner can remove it. You can unsubscribe instead.",
                        severity="warning")
            return
        if not await self.push_screen_wait(ConfirmDialog(
                f"Remove {g.short} from the network?",
                "Every node deletes the group and all its posts, and the name can never be "
                "used again - not even by you. This cannot be undone.\n\n"
                "Copies people have already saved cannot be deleted.",
                "Remove for good", danger=True)):
            return
        self.set_status(f"Removing {g.short} ...")
        try:
            await self.session.remove_group(g.group_id)
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(f"Not removed: {exc}", severity="error", timeout=8)
            return
        self.current_group = None
        self.notify(f"{g.short} removed")
        self.refresh_groups()

    def action_open_inbox(self) -> None:
        gid = self.session.my_inbox
        if gid in self.groups:
            self.select_group(gid)
        else:
            self.notify("Your inbox is not ready yet - it is created when the node is reachable",
                        severity="warning")

    def action_mark_all_read(self) -> None:
        g = self._need_group()
        if not g:
            return
        for m in self.session.cache.get(g.group_id, {}).values():
            self.session.mark_read(m, save=False)
        self.session.save()
        self._render_threads()
        self._save_soon()

    def action_refresh(self) -> None:
        if self.session:
            self.refresh_groups()

    async def action_quit(self) -> None:
        if self.session:
            self.session.save()
            await self.session.close()
        self.exit()


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="unseenet-tui", description="Unseenet terminal client.")
    p.add_argument("--vault", default=str(default_vault_path()), help="encrypted vault file")
    p.add_argument("--version", action="version", version=f"unseenet-tui {__version__}")
    args = p.parse_args(argv)
    UnseenetApp(Path(args.vault)).run()


if __name__ == "__main__":
    main()
