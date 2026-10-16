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
import traceback
from datetime import datetime
from pathlib import Path

from textual import on, work
from textual.message import Message as Message_
from textual.worker import Worker, WorkerState
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from rich.text import Text
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.screen import ModalScreen, Screen
from textual.widgets import (Button, Checkbox, DataTable, Footer, Header, Input, Label, RichLog,
                             Select, Static, TextArea, Tree)

from .. import __version__
from ..console import console_css
from ..core.vault import Vault, VaultError
from ..nntp import NNTPError
from ..core import crypto
from ..core.groups import INBOX_NAME, personal_inbox_id
from . import session as _session_module
from . import naming
from .. import names as nm
from .session import (MAX_SIG_LINES, SIG_SEPARATOR, GroupInfo, Message, Session, SessionError,
                      default_vault_path, split_signature)

REFRESH_SECONDS = 60           # a fallback; new posts normally arrive by push (UN-RFC 0008)
REPO_URL = "https://github.com/unseenet/unseenet"
DOCS_URL = "https://unseenet.org/"
CONTACT = "contact:"          # tree data prefix for a contact's conversation


def node_label(address: str) -> str:
    """A short name for a node address: the start of its onion name."""
    host = address.split(":")[0]
    return host[:8] if host.endswith(".onion") else address


def sess_default_pow() -> int:
    return _session_module.DEFAULT_POW


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


GROUP_KINDS = {"open": "open - anyone can read and post", "moderated": "moderated",
               "channel": "channel - only chosen people post",
               "closed": "closed - members only, encrypted",
               "inbox": "inbox - anyone writes, only the owner reads"}


def known_node_details(n) -> str:
    """A known node (UN-RFC 0010) as a few lines, to choose the right one."""
    lines = [n.description or "(no description)"]
    if n.operator:
        lines.append(f"Run by:   {n.operator}")
    lines.append(f"Address:  {n.address}")
    return "\n".join(lines)


def node_details(address: str, info: dict | None, known=None, groups: int = 0,
                 default: bool = False) -> str:
    """One of your nodes: what it says about itself (UN-RFC 0011) and the node list."""
    i = info or {}
    p = i.get("policy", {})
    name = i.get("name") or (known.name if known else "") or address
    lines = [name + ("   ♦ default node" if default else "")]
    about = i.get("description") or (known.description if known else "")
    if about:
        lines.append(about)
    operator = i.get("operator") or (known.operator if known else "")
    if operator:
        lines.append(f"Run by:   {operator}")
    lines.append(f"Address:  {address}")
    if info is None:
        lines.append("Not reachable right now.")
    elif p:
        lines.append(f"Policy:   new groups {p.get('new_groups', '?')}, kept "
                     f"{p.get('retention_days', '?')} days, postage {p.get('min_pow', '?')} "
                     f"bits, logs {p.get('logging', '?')}")
    lines.append(f"Groups:   {groups} of yours are read from here"
                 + ("   ·   in the project's node list" if known else ""))
    return "\n".join(lines)


# Group icons: who may write and read, then how the group is shown. Only
# characters from WGL4, the set every terminal font has - even the classic
# Windows console with Consolas - and one cell wide each.
ICONS = {"threads": "≡", "chat": "»", "data": "¤", "moderated": "√", "channel": "►",
         "closed": "∩", "inbox": "@", "local": "⌂", "unknown": "·"}
ICON_LEGEND = ("≡ posts  » chat  ¤ data for programs  √ moderated  ► channel  ∩ closed  "
               "@ inbox  ⌂ local (one node)  · not known yet")


def group_icons(gtype: str | None, data: dict | None = None) -> str:
    """Two icons and a space between, e.g. '∩ »' for a closed chat group."""
    data = data or {}
    gtype = gtype or data.get("type")
    if not gtype:
        return f"{ICONS['unknown']}  "
    if gtype == "inbox":
        return f"{ICONS['inbox']}  "
    access = ICONS.get(gtype) if gtype in ("moderated", "channel", "closed") else \
        (ICONS["local"] if data.get("local") else " ")
    view = {"chat": ICONS["chat"], "data": ICONS["data"]}.get(data.get("view"), ICONS["threads"])
    return f"{access} {view}"


def is_personal_inbox(group_id: str) -> bool:
    return group_id.split("@", 1)[0] == INBOX_NAME


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
#chat { height: 1fr; display: none; }
#chat-log { height: 1fr; padding: 0 1; }
#chat-input { margin: 0 1; }
#status { height: 1; background: $boost; color: $text-muted; padding: 0 1; }
.unread { text-style: bold; }

ModalScreen { align: center middle; }
.dialog { width: 80; max-width: 100%; height: auto; max-height: 100%; overflow-y: auto;
          border: thick $primary; background: $panel; padding: 1 2; }
.dialog.list { width: 90%; max-width: 130; height: 94%; overflow-y: hidden; padding: 0 1; }
.dialog Label { width: 100%; }
.dialog.list Tree, .dialog.list DataTable { height: 1fr; min-height: 3; }
.dialog .details { height: auto; max-height: 10; margin-top: 1; padding: 0 1;
                   border-left: thick $primary-darken-2; color: $text; }
#names-details { margin: 1 0 1 0; }        /* the key line must not touch the field below */
.dialog Label.title { text-style: bold; margin-bottom: 1; }
.dialog Input, .dialog Select { margin-bottom: 1; }
.dialog.compose { width: 96%; height: 94%; max-height: 100%; }
.dialog.compose #body { height: 1fr; margin-bottom: 1; }
.dialog .buttons { height: auto; align-horizontal: right; dock: bottom; }
.dialog Button { margin-left: 1; min-width: 8; width: auto; }
.dialog .hint { color: $text-muted; }
.dialog .error { color: $error; }
#groups { padding: 0 1; }
"""


# ======================================================================
# Dialogs
# ======================================================================

class Dialog(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CANCEL_RESULT = None          # what closing with Esc or the cancel button returns

    def dismiss(self, result=None):
        # Only the dialog on top can close, and only once: two handlers for one
        # button press must not pop the screen below it (ScreenStackError).
        if self.app.screen is not self:
            return None
        return super().dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(self.CANCEL_RESULT)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(self.CANCEL_RESULT)


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


OTHER_NODE = "__other__"


class SetupDialog(Dialog):
    """First run: identity and node."""

    def __init__(self, need_identity: bool, need_node: bool, known: list | None = None):
        super().__init__()
        self.need_identity, self.need_node = need_identity, need_node
        from ..known_nodes import KNOWN_NODES
        self.known = list(known or KNOWN_NODES)

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Welcome to Unseenet", classes="title")
            if self.need_identity:
                yield Label("Your identity is a key pair. The name is just a label others see.",
                            classes="hint")
                yield Input(placeholder="Display name, e.g. Andreas", id="display")
            if self.need_node:
                yield Label("Which node do you want to connect to? Pick one of the known nodes, "
                            "or enter the address of another you were given.", classes="hint")
                choices = [(f"{n.name} - {n.description}", n.address) for n in self.known]
                choices.append(("Another node - enter its address", OTHER_NODE))
                yield Select(choices, value=choices[0][1], allow_blank=False, id="known")
                other = Input(placeholder="xyz...abc.onion  (or host:port for testing)", id="node")
                other.display = False
                yield other
                yield Static(known_node_details(self.known[0]) if self.known else "",
                             id="known-details", classes="details", markup=False)
                yield Checkbox("Also use the other known nodes as backups", value=True, id="backups")
            with Horizontal(classes="buttons"):
                yield Button("Quit", id="cancel")
                yield Button("Continue", variant="primary", id="ok")

    @on(Select.Changed, "#known")
    def _known_changed(self, event: Select.Changed) -> None:
        self.query_one("#node").display = event.value == OTHER_NODE
        if event.value == OTHER_NODE:
            self.query_one("#node").focus()
        n = next((k for k in self.known if k.address == event.value), None)
        details = self.query_one("#known-details", Static)
        details.display = n is not None
        if n:
            details.update(known_node_details(n))

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
            known = self.query_one("#known", Select).value
            node = self.query_one("#node", Input).value.strip() if known == OTHER_NODE else known
            if not node:
                self.app.notify("Please enter a node address", severity="error")
                return
            result["node"] = node
            if self.query_one("#backups", Checkbox).value:
                result["backups"] = [n.address for n in self.known if n.address != node]
        self.dismiss(result)


class ComposeDialog(Dialog):
    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "send", "Send")]

    def __init__(self, group: GroupInfo, subject: str = "", quote: str = "", is_reply: bool = False,
                 heading: str | None = None, signature: str = "", has_rules: bool = False):
        super().__init__()
        self.group, self.subject, self.quote, self.is_reply = group, subject, quote, is_reply
        self.heading, self.signature, self.has_rules = heading, signature, has_rules

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog compose"):
            kind = "Reply in" if self.is_reply else "New post in"
            lock = "  ∩ encrypted" if self.group.type == "closed" else ""
            yield Label(self.heading or f"{kind} {self.app.session.group_label(self.group.group_id)}{lock}", classes="title",
                        markup=False)
            yield Input(value=self.subject, placeholder="Subject", id="subject")
            text = self.quote + (("\n" if self.quote else "\n\n") + SIG_SEPARATOR + self.signature
                                 if self.signature else "")
            yield TextArea(text, id="body", soft_wrap=True)
            yield Label(("This group has rules - press Esc and ? to read them.  " if self.has_rules
                         else "") + "Ctrl+S to send. Sending takes a moment: the post carries a "
                        "small proof-of-work.", classes="hint")
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


class BridgesDialog(Dialog):
    """How Tor connects: directly, or through bridges where Tor is blocked."""

    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "save", "Save")]
    CHOICES = [("Off - connect to Tor directly (best when Tor is not blocked)", "off"),
               ("Built-in obfs4 bridges - Tor traffic disguised as random data", "obfs4"),
               ("Built-in Snowflake - through volunteers' browsers, hard to block", "snowflake"),
               ("My own bridges - lines from bridges.torproject.org", "custom")]

    def __init__(self, setting: dict):
        super().__init__()
        self.setting = setting

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Tor bridges", classes="title")
            yield Label("If Tor cannot connect - at work, at school, or in a country that blocks "
                        "Tor - bridges are hidden entrances to the Tor network. The built-in ones "
                        "come with the portable builds. For your own, ask bridges.torproject.org "
                        "or email bridges@torproject.org, and paste the lines below.",
                        classes="hint", markup=False)
            yield Select(self.CHOICES, value=self.setting.get("mode", "off"), allow_blank=False,
                         id="mode")
            lines = TextArea("\n".join(self.setting.get("custom", [])), id="lines", soft_wrap=True)
            lines.display = self.setting.get("mode") == "custom"     # before the first paint
            yield lines
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#lines", TextArea).styles.height = 6
        self._show_lines()

    @on(Select.Changed, "#mode")
    def _show_lines(self, event=None) -> None:
        self.query_one("#lines").display = self.query_one("#mode", Select).value == "custom"

    @on(Button.Pressed, "#ok")
    def action_save(self) -> None:
        mode = self.query_one("#mode", Select).value
        lines = [ln.strip() for ln in self.query_one("#lines", TextArea).text.splitlines()
                 if ln.strip()]
        if mode == "custom" and not lines:
            self.app.notify("Paste at least one bridge line", severity="warning")
            return
        self.dismiss({"mode": mode, "custom": lines})


DELIVERY_CHOICES = [("Discussion - shown as threads", "threads"),
                    ("Chat - shown as a conversation", "chat"),
                    ("Chat, fast delivery - gives up some anonymity", "fastchat"),
                    ("Data for programs - hidden when people browse", "data")]
DELIVERY = {"threads": ("threads", False), "chat": ("chat", False), "fastchat": ("chat", True),
            "data": ("data", False)}


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
            yield Select(DELIVERY_CHOICES, value="threads", allow_blank=False, id="view")
            yield Input(placeholder="Title (optional; keep it vague for closed groups)", id="title")
            yield Label("Rules (optional) - shown to people before they post:", classes="hint")
            yield TextArea("", id="rules", soft_wrap=True)
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#rules", TextArea).styles.height = 6

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
            # said under the name field, not in a toast that would cover the buttons
            help_label = self.query_one("#name-help", Label)
            help_label.update(f"Not valid yet: {problem}")
            help_label.set_class(True, "error")
            self.query_one("#name", Input).focus()
            return
        view, fast = DELIVERY[self.query_one("#view", Select).value]
        self.dismiss({"name": name, "gtype": self.query_one("#type", Select).value,
                      "title": self.query_one("#title", Input).value.strip(),
                      "local": self.query_one("#where", Select).value == "local",
                      "rules": self.query_one("#rules", TextArea).text.strip(),
                      "view": view, "low_latency": fast})


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


class KeyListDialog(Dialog):
    """A list of people (key, label); pick one for an action."""

    def __init__(self, title: str, hint: str, people: list[tuple[str, str]], action: str):
        super().__init__()
        self.title_, self.hint, self.people, self.action = title, hint, people, action

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_, classes="title", markup=False)
            yield Label(self.hint, classes="hint", markup=False)
            yield Select([(f"{label}  ({key[:20]}...)", key) for key, label in self.people],
                         prompt="Choose someone", id="who")
            with Horizontal(classes="buttons"):
                yield Button("Close", id="cancel")
                yield Button(self.action, variant="primary", id="ok")

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        who = self.query_one("#who", Select).value
        if isinstance(who, str):
            self.dismiss(who)


class ModerationDialog(Dialog):
    """Submissions to groups you moderate (UN-RFC 0009 section 3)."""

    def __init__(self, items: list[tuple[str, str, str]]):
        super().__init__()
        self.items = items                  # (id, label, preview)

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog list"):
            yield Label("Moderation queue", classes="title")
            yield Label("Posts waiting for a moderator. Approving posts them unchanged; the "
                        "first moderator to act decides.", classes="hint")
            yield Select([(label, i) for i, label, _ in self.items], prompt="Choose a post",
                         id="which")
            yield Static("", id="preview", classes="details", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Close", id="cancel")
                yield Button("Reject", variant="error", id="reject")
                yield Button("Approve", variant="primary", id="approve")

    @on(Select.Changed, "#which")
    def _show(self, event: Select.Changed) -> None:
        text = next((p for i, _, p in self.items if i == event.value), "")
        self.query_one("#preview", Static).update(text)

    @on(Button.Pressed, "#approve")
    @on(Button.Pressed, "#reject")
    def _act(self, event: Button.Pressed) -> None:
        which = self.query_one("#which", Select).value
        if isinstance(which, str):
            self.dismiss((event.button.id, which))


class NamesDialog(Dialog):
    """Your names (UN-RFC 0019): those you hold, those you asked for, and a field to claim one."""

    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Your names", classes="title")
            yield Label("A name lets others see @yourname instead of Name~abcd. A name "
                        "without a dot (lorensen) is first come, first served; a domain "
                        "(lorensen.dk) needs a DNS record that shows it is yours.", classes="hint")
            yield Static(self.text, id="names-details", classes="details", markup=False)
            yield Input(placeholder="lorensen  or  lorensen.dk", id="value")
            with Horizontal(classes="buttons"):
                yield Button("Close", id="cancel")
                yield Button("Release", id="release")
                yield Button("Transfer", id="transfer")
                yield Button("Renew", id="renew")
                yield Button("Claim", variant="primary", id="claim")

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#claim")
    @on(Button.Pressed, "#renew")
    @on(Button.Pressed, "#transfer")
    @on(Button.Pressed, "#release")
    def _act(self, event) -> None:
        name = self.query_one("#value", Input).value.strip().lower().lstrip("@")
        button = getattr(event, "button", None)
        action = button.id if button is not None else "claim"
        if name:
            self.dismiss((action, name))
        else:
            self.notify("Type the name first", severity="warning")


class GroupInfoDialog(Dialog):
    """Title, type, owner and rules of a group (UN-RFC 0014)."""

    def __init__(self, gid: str, data: dict, owner_label: str, can_edit: bool, first_time: bool,
                 node: str = ""):
        super().__init__()
        self.gid, self.data, self.owner_label, self.node = gid, data, owner_label, node
        self.can_edit, self.first_time = can_edit, first_time

    def compose(self) -> ComposeResult:
        d = self.data
        kinds = GROUP_KINDS
        lines = [f"Group:     {self.gid}",
                 f"Type:      {kinds.get(d.get('type', ''), d.get('type', '?'))}",
                 f"Owner:     {self.owner_label}",
                 f"Shown as:  {d.get('view', 'threads')}"
                 + ("   fast delivery (less anonymity about who posts from where)"
                    if d.get("low_latency") else ""),
                 f"Postage:   {d.get('min_pow', 0)} bits     Kept for: {d.get('retention_days', 90)} days"
                 + ("     Local to one node" if d.get("local") else ""),
                 f"Version:   {d.get('serial', 1)}"]
        if self.node:
            lines.append(f"Read from: {self.node}")
        label = getattr(self.app.session, "identity_label", None)
        for role, title in (("moderators", "Moderators:"), ("posters", "Posters:  ")):
            if d.get(role):
                names = [label(k) if label else k[:20] for k in d[role][:6]]
                lines.append(f"{title} " + ", ".join(names) + (" ..." if len(d[role]) > 6 else ""))
        bans = [b for b in d.get("banned", []) if isinstance(b, dict)]
        if bans:                                  # public on purpose (UN-RFC 0004, 5.1)
            lines.append(f"Banned:    {len(bans)} "
                         + ("person" if len(bans) == 1 else "people") + " - "
                         + "; ".join(f"{b.get('key', '')[8:16]}...: {b.get('reason') or 'no reason given'}"
                                     for b in bans[:5]) + (" ..." if len(bans) > 5 else ""))
        if d.get("description"):
            lines += ["", d["description"]]
        with Vertical(classes="dialog"):
            yield Label(("Before you post - the rules of " if self.first_time and d.get("rules")
                         else "About ") + (d.get("title") or self.gid.rpartition("@")[0]),
                        classes="title", markup=False)
            yield Static("\n".join(lines), markup=False)
            yield Label("Rules" if d.get("rules") else "This group has no rules.", classes="title")
            if d.get("rules"):
                with VerticalScroll(id="rules-view"):
                    yield Static(d["rules"], markup=False)
            with Horizontal(classes="buttons"):
                if self.can_edit:
                    yield Button("Edit group", id="edit")
                yield Button("OK" if self.first_time else "Close", variant="primary", id="cancel")

    def on_mount(self) -> None:
        if self.data.get("rules"):
            self.query_one("#rules-view").styles.max_height = 14

    @on(Button.Pressed, "#edit")
    def _edit(self) -> None:
        self.dismiss("edit")


class EditGroupDialog(Dialog):
    """Owner: change title, description, rules, view and delivery (a new manifest)."""

    def __init__(self, data: dict):
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        d = self.data
        current = "fastchat" if d.get("low_latency") else d.get("view", "threads")
        if current not in DELIVERY:                  # a view this client does not know
            current = "threads"
        with Vertical(classes="dialog compose"):
            yield Label(f"Edit {d.get('name', '')} - every node gets the new version", classes="title",
                        markup=False)
            yield Input(value=d.get("title", ""), placeholder="Title", id="title")
            yield Input(value=d.get("description", ""), placeholder="Description (one paragraph)",
                        id="description")
            yield Select(DELIVERY_CHOICES, value=current, allow_blank=False, id="view")
            yield Input(value=str(d.get("min_pow", 0)), placeholder="Minimum postage in bits (16-24)",
                        id="min_pow")
            yield Label("Rules - shown to people before their first post:", classes="hint")
            yield TextArea(d.get("rules", ""), id="body", soft_wrap=True)
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Publish", variant="primary", id="ok")

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        try:
            min_pow = int(self.query_one("#min_pow", Input).value.strip() or 0)
        except ValueError:
            self.app.notify("Postage must be a number", severity="error")
            return
        if not 0 <= min_pow <= 28:
            self.app.notify("Postage between 0 and 28 bits, please", severity="error")
            return
        view, fast = DELIVERY[self.query_one("#view", Select).value]
        self.dismiss({"title": self.query_one("#title", Input).value.strip(),
                      "description": self.query_one("#description", Input).value.strip(),
                      "rules": self.query_one("#body", TextArea).text.strip(),
                      "view": view, "low_latency": fast, "min_pow": min_pow})


class ReadScreen(Screen):
    """One message on the whole screen. r replies, m writes privately, n and p
    go to the next and previous message, Esc goes back."""
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "back", "Back", show=False),
        Binding("r", "reply", "Reply"),
        Binding("m", "message", "Message"),
        Binding("n", "next", "Next"),
        Binding("p", "previous", "Previous"),
        Binding("space", "page", "Page down", show=False),
    ]
    CSS = """
    ReadScreen #read-head { padding: 0 1; background: $boost; color: $text; }
    ReadScreen #read-scroll { height: 1fr; padding: 0 2; }
    """

    def __init__(self, msg: Message):
        super().__init__()
        self.msg = msg

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="read-head")
        with VerticalScroll(id="read-scroll"):
            yield Static("", id="read-body")
        yield Footer()

    def on_mount(self) -> None:
        self.show(self.msg)
        self.query_one("#read-scroll").focus()

    def show(self, msg: Message) -> None:
        self.msg = msg
        head, body = self.app.article(msg)
        self.query_one("#read-head", Static).update(head)
        self.query_one("#read-body", Static).update(body)
        self.query_one("#read-scroll").scroll_home(animate=False)

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_reply(self) -> None:
        self.app.action_reply()

    def action_message(self) -> None:
        self.app.action_message()

    def action_next(self) -> None:
        if self.app.neighbour(+1) is None:
            self.app.notify("That was the last one")

    def action_previous(self) -> None:
        if self.app.neighbour(-1) is None:
            self.app.notify("That was the first one")

    def action_page(self) -> None:
        scroll = self.query_one("#read-scroll")
        if scroll.scroll_y >= scroll.max_scroll_y:
            self.action_next()                 # like the old newsreaders: space reads on
        else:
            scroll.scroll_page_down(animate=False)


class AboutDialog(Dialog):
    """F1: what this program is, and where the project lives."""

    def compose(self) -> ComposeResult:
        text = (
            f"Unseenet {__version__}\n"
            "\n"
            "Discussion groups the old Usenet way, carried over Tor. Nodes, run by\n"
            "anyone, replicate groups to each other; this client talks to one of\n"
            "them and keeps everything in a single encrypted vault, so it can live\n"
            "on a USB stick and leave nothing behind.\n"
            "\n"
            "Every post is signed, paid for with a little proof of work instead of\n"
            "an account, and closed groups and private messages are encrypted end\n"
            "to end. No central server, no company, no ads.\n"
            "\n"
            "The protocol is written down as open UN-RFCs, so anyone can build a\n"
            "compatible node or client. Free software, Apache License 2.0.\n"
            "\n"
            f"Source:         {REPO_URL}\n"
            f"Documentation:  {DOCS_URL}"
        )
        with Vertical(classes="dialog"):
            yield Label("About Unseenet", classes="title")
            yield Static(text, markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Close", id="cancel")
                yield Button("GitHub", id="repo")
                yield Button("Documentation", variant="primary", id="docs")

    @on(Button.Pressed, "#repo")
    def _repo(self) -> None:
        self.app.open_url(REPO_URL)

    @on(Button.Pressed, "#docs")
    def _docs(self) -> None:
        self.app.open_url(DOCS_URL)


class NodesDialog(Dialog):
    """Your nodes. Your key is in the vault, so you are the same person on all of them."""

    def __init__(self, nodes: list[str], infos: dict, counts: dict[str, int], known: list | None = None):
        super().__init__()
        self.nodes, self.infos, self.counts = nodes, infos, counts
        self.known = {n.address: n for n in (known or [])}

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog list"):
            yield Label("Your nodes", classes="title")
            yield Label("You are the same on every node - your key lives in your vault. "
                        "Each group is read from one node; new groups and your inbox go to "
                        "the default node (♦).", classes="hint")
            yield DataTable(id="nodes-table", cursor_type="row", zebra_stripes=True)
            yield Static("", id="node-details", classes="details", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("OK", id="cancel")
                yield Button("Add", id="add")
                yield Button("Remove", id="remove")
                yield Button("Make default", id="default")
                yield Button("Details", variant="primary", id="info")

    def on_mount(self) -> None:
        table = self.query_one("#nodes-table", DataTable)
        table.add_columns("", "Name", "Address", "Your groups", "")
        for i, address in enumerate(self.nodes):
            info = self.infos.get(address)
            known = self.known.get(address)
            name = (info or {}).get("name", "") or (known.name if known else "")
            state = "unreachable" if info is None else "ok"
            short = address if len(address) <= 34 else address[:16] + "…" + address[-14:]
            table.add_row("♦" if i == 0 else "", Text(name), Text(short),
                          str(self.counts.get(address, 0)), state, key=address)
        table.focus()

    def _selected(self) -> str | None:
        table = self.query_one("#nodes-table", DataTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    @on(DataTable.RowHighlighted, "#nodes-table")
    def _highlighted(self, event: DataTable.RowHighlighted) -> None:
        address = event.row_key.value
        self.query_one("#node-details", Static).update(node_details(
            address, self.infos.get(address), self.known.get(address),
            self.counts.get(address, 0), default=address == self.nodes[0]))

    @on(DataTable.RowSelected, "#nodes-table")
    def _row(self, event: DataTable.RowSelected) -> None:
        self.dismiss(("info", event.row_key.value))

    @on(Button.Pressed, "#add")
    def _add(self) -> None:
        self.dismiss(("add", None))

    @on(Button.Pressed, "#remove")
    @on(Button.Pressed, "#default")
    @on(Button.Pressed, "#info")
    def _act(self, event: Button.Pressed) -> None:
        address = self._selected()
        if address:
            self.dismiss((event.button.id, address))


class AddNodeDialog(Dialog):
    """Add a node: one of the known nodes you do not use yet, or any address."""

    def __init__(self, known: list, used: list[str]):
        super().__init__()
        self.known = [n for n in known if n.address not in used]
        self.choices = [(f"{n.name} - {n.description}", n.address) for n in self.known]
        self.choices.append(("Another node - enter its address", OTHER_NODE))

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Add a node", classes="title")
            yield Label("You keep your key and your groups; the node's groups are added to "
                        "what you can browse (g).", classes="hint")
            yield Select(self.choices, value=self.choices[0][1], allow_blank=False, id="known")
            other = Input(placeholder="xyz...abc.onion  (add :port if it is not 119)", id="node")
            other.display = len(self.choices) == 1
            yield other
            details = Static(known_node_details(self.known[0]) if self.known else "",
                             id="known-details", classes="details", markup=False)
            details.display = bool(self.known)
            yield details
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Add", variant="primary", id="ok")

    @on(Select.Changed, "#known")
    def _changed(self, event: Select.Changed) -> None:
        self.query_one("#node").display = event.value == OTHER_NODE
        n = next((k for k in self.known if k.address == event.value), None)
        details = self.query_one("#known-details", Static)
        details.display = n is not None
        if n:
            details.update(known_node_details(n))

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        choice = self.query_one("#known", Select).value
        address = self.query_one("#node", Input).value.strip() if choice == OTHER_NODE else choice
        if not address:
            self.app.notify("Enter the node's address", severity="error")
            return
        self.dismiss(address)


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
            if i.get("node_key"):
                lines.append(f"Node key:  {i['node_key']}")
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


class BrowseTree(Tree):
    """The tree of all groups. Space or Enter subscribes; with the mouse, only a
    click on the [ ] box does - a click on the rest of the line only shows what
    the group is."""
    BINDINGS = [Binding("space", "toggle_subscription", "Subscribe", show=False)]
    BOX = 3                                      # "[x]" at the start of a group's label

    class Toggle(Message_):
        def __init__(self, node) -> None:
            super().__init__()
            self.node = node

    def action_toggle_subscription(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if isinstance(node.data, GroupInfo):
            self.post_message(self.Toggle(node))
        else:
            node.toggle()                        # a hierarchy: open or close it

    async def _on_click(self, event) -> None:
        meta = event.style.meta
        node = self.get_node_at_line(meta["line"]) if "line" in meta else None
        if node is None or not isinstance(node.data, GroupInfo) or meta.get("toggle"):
            return                               # Tree's own handler: hierarchies as before
        event.prevent_default()                  # not Tree's: a click must not subscribe
        self.cursor_line = meta["line"]          # shows the group's details
        region = self._get_label_region(meta["line"])
        x = event.x + self.scroll_offset.x - self.gutter.left
        if region is not None and region.x <= x < region.x + self.BOX:
            self.post_message(self.Toggle(node))


class BrowseDialog(Dialog):
    """All groups on the node, by hierarchy; Enter toggles subscription."""
    CANCEL_RESULT = True

    def __init__(self, groups: list[GroupInfo]):
        super().__init__()
        self.groups = groups
        self.known = {g.group_id for g in groups}
        self.current: GroupInfo | None = None
        self.peeked: dict[str, tuple[dict, int] | str] = {}   # group -> (manifest, posts) or error

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog list"):
            several = len(self.app.session.nodes) > 1
            yield Label("Groups on your nodes" if several else "Groups on this node", classes="title")
            yield Label("Space, Enter or a click on [ ]: subscribe or unsubscribe. "
                        "Enter on a hierarchy opens or closes it.  Esc: close.", classes="hint")
            yield Label(ICON_LEGEND, classes="hint", markup=False)
            tree: Tree = BrowseTree("groups", id="browse-tree")
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
                tree.root.add_leaf(Text("No groups yet - use Ctrl+P, Create group, to create one."))
            yield tree
            yield Static("Move to a group to see what it is.", id="group-details",
                         classes="details", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("OK", variant="primary", id="cancel")

    def _label(self, g: GroupInfo) -> Text:
        mark = "[x]" if g.subscribed else "[ ]"
        peek = self.peeked.get(g.group_id)
        data = peek[0] if isinstance(peek, tuple) else self.app.session.manifest_data(g.group_id)
        icons = group_icons(g.type, data)
        where = ""
        if len(self.app.session.nodes) > 1 and g.nodes:
            where = f"   @ {node_label(g.nodes[0])}" + (f" +{len(g.nodes) - 1}" if len(g.nodes) > 1 else "")
        return Text(f"{mark} {icons} {self.app.session.group_label(g.group_id, self.known)}   {g.description}{where}")

    def on_mount(self) -> None:
        self.query_one("#browse-tree", Tree).focus()

    @on(Tree.NodeHighlighted, "#browse-tree")
    def _highlighted(self, event: Tree.NodeHighlighted) -> None:
        g = event.node.data
        self.current = g if isinstance(g, GroupInfo) else None
        if self.current is None:
            return
        self._show(g)
        if g.group_id not in self.peeked:
            self._peek(g)

    @work(group="peek", exit_on_error=False)
    async def _peek(self, g: GroupInfo) -> None:
        # Not exclusive: cancelling a request half-way would break the connection.
        # Wait a moment instead, so scrolling through the list asks for nothing.
        await asyncio.sleep(0.5)
        if self.current is not g or g.group_id in self.peeked:
            return
        self.peeked[g.group_id] = "asking the node ..."
        self._show(g)
        try:
            self.peeked[g.group_id] = await asyncio.wait_for(
                self.app.session.peek_group(g.group_id, g.nodes[0] if g.nodes else None), 60)
        except (SessionError, OSError, ConnectionError, NNTPError, ValueError,
                asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            self.peeked[g.group_id] = f"could not ask the node ({exc})"
        peek = self.peeked[g.group_id]
        if isinstance(peek, tuple) and peek[0].get("type"):
            g.type = peek[0]["type"]          # its icons, now that they are known
            node = self.query_one("#browse-tree", Tree).cursor_node
            if node is not None and node.data is g:
                node.set_label(self._label(g))
        if self.current is g:
            self._show(g)

    def _owner(self, g: GroupInfo, data: dict) -> str:
        from ..known_nodes import NODES_GROUP
        s = self.app.session
        fp = g.group_id.rpartition("@")[2]
        if fp == s.my_inbox.rpartition("@")[2]:
            return "you"
        if fp == NODES_GROUP.rpartition("@")[2]:
            return "the Unseenet project"
        name = s.contact_name(data["owner"]) if data.get("owner") else None
        return f"{name} √ ({fp})" if name else fp

    def _show(self, g: GroupInfo) -> None:
        peek = self.peeked.get(g.group_id)
        data = peek[0] if isinstance(peek, tuple) else self.app.session.manifest_data(g.group_id)
        lines = [g.group_id]
        title = data.get("title") or g.description
        if title:
            lines.append(title)
        if data.get("description") and data["description"] != title:
            lines.append(data["description"])
        if data:
            facts = [GROUP_KINDS.get(data.get("type", ""), data.get("type", "?"))]
            if isinstance(peek, tuple):
                facts.append(f"{peek[1]} posts")
            facts.append(f"kept {data.get('retention_days', 90)} days")
            lines.append("Type:   " + ",  ".join(facts))
        elif isinstance(peek, str):
            lines.append(f"({peek})")
        lines.append(f"Owner:  {self._owner(g, data)}")
        warning = naming.group_warning(self.app.session, g.group_id, self.known)
        if warning:
            lines.append(("Name:   " if warning.startswith("Endorsed") else "! ") + warning)
        if len(g.nodes) > 1 or len(self.app.session.nodes) > 1:
            lines.append("On:     " + ", ".join(node_label(n) for n in g.nodes))
        if data.get("type") == "closed":
            lines.append("Members only: you need an invitation from the owner to read it.")
        if self._not_mine_inbox(g):
            lines.append("An inbox: anyone can write to it, only its owner can read it.")
        if data.get("view") == "data":
            lines.append("Data for programs (lists, certificates), not posts for people.")
        if data.get("rules"):
            first = data["rules"].strip().splitlines()[0]
            lines.append(f"Rules:  {first[:90]}" + (" ..." if len(data["rules"].strip()) > len(first) else ""))
        try:
            self.query_one("#group-details", Static).update("\n".join(lines))
        except Exception:  # noqa: BLE001  (the dialog was closed meanwhile)
            pass

    def _not_mine_inbox(self, g: GroupInfo) -> bool:
        """An inbox someone else owns (a person's, or a node operator's contact
        inbox): you can write to it, but only its owner can read it."""
        peek = self.peeked.get(g.group_id)
        data = peek[0] if isinstance(peek, tuple) else self.app.session.manifest_data(g.group_id)
        kind = data.get("type") or g.type
        return kind == "inbox" and g.group_id.rpartition("@")[2] != \
            self.app.session.my_inbox.rpartition("@")[2]

    @on(Tree.NodeSelected, "#browse-tree")
    def _selected(self, event: Tree.NodeSelected) -> None:
        self._toggle(event.node)

    @on(BrowseTree.Toggle)
    def _clicked(self, event: "BrowseTree.Toggle") -> None:
        self._toggle(event.node)

    def _toggle(self, node) -> None:
        g = node.data
        if not isinstance(g, GroupInfo):
            return
        if not g.subscribed and self._not_mine_inbox(g):
            self.app.notify(f"{self.app.session.group_label(g.group_id, self.known)} is an inbox: anyone can write to it, only its owner "
                            "can read it. To write to a node's operator: Ctrl+P, Your nodes, "
                            "Details, Write to operator.", severity="warning", timeout=10)
            return
        g.subscribed = not g.subscribed
        self.app.session.subscribe(g.group_id, g.subscribed,
                                   node=g.nodes[0] if g.subscribed and g.nodes else None)
        node.set_label(self._label(g))



# ======================================================================
# Main app
# ======================================================================

class UnseenetApp(App):
    TITLE = "unseenet"
    CSS = CSS + console_css()
    BINDINGS = [
        # chat: the input line takes the letters; Esc leaves it, Enter goes back
        # (first, so the footer always has room for them)
        Binding("escape", "leave_input", "Shortcuts"),
        Binding("enter", "write", "Write"),
        Binding("n", "new_post", "New post"),
        Binding("r", "reply", "Reply"),
        Binding("g", "browse", "Groups"),
        Binding("j", "join", "Join", show=False),
        Binding("m", "message", "Message"),
        Binding("o", "node_info", "Nodes", show=False),
        Binding("k", "show_key", "My key", show=False),
        Binding("at", "names", "Names", show=False),
        Binding("s", "signature", "Signature", show=False),
        Binding("a", "add_contact", "Add contact", show=False),
        Binding("D", "withdraw", "Withdraw", show=False),
        Binding("question_mark", "group_info", "About group"),
        Binding("v", "toggle_view", "Chat/threads"),
        Binding("f", "read", "Full screen", show=False),
        Binding("f5", "refresh", "Refresh"),
        Binding("ctrl+r", "refresh", "Refresh", show=False),
        Binding("f1", "about", "About", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Show only the shortcuts that do something where you are (False hides one)."""
        s = self.session
        if isinstance(self.screen, ReadScreen):
            return action in ("about", "refresh")    # it has its own r, m, n, p
        if s is None or not s.has_identity():
            return True
        gid = self.current_group or ""
        contact = gid.startswith(CONTACT)
        group = gid in self.groups
        m = self.current_message
        chat = bool(gid) and self.view_of(gid) == "chat"
        typing = getattr(self.focused, "id", None) == "chat-input"
        if action == "leave_input":
            return typing
        if action == "write":
            return chat and not typing
        if action == "new_post":
            return contact or (group and s.may_post(gid))
        if action == "reply":
            return contact or (m is not None and m.readable and (m.private or s.may_post(gid)))
        if action == "invite":
            g = self.groups.get(gid)
            return bool(g and g.type == "closed" and s.group_entry(gid).get("owner"))
        if action == "withdraw":
            return bool(m and group and s.may_cancel(m))
        if action == "add_contact":
            return bool(m and m.readable and m.author_key
                        and m.author_key != s.identity().key_text)
        if action in ("group_info", "toggle_view"):
            return group and gid != s.my_inbox
        return True

    def action_leave_input(self) -> None:
        self.query_one("#chat-log").focus()          # now the letters are shortcuts again

    def action_write(self) -> None:
        self.query_one("#chat-input").focus()

    def __init__(self, vault_path: Path):
        super().__init__()
        self.vault_path = vault_path
        self.session: Session | None = None
        self.groups: dict[str, GroupInfo] = {}
        self.current_group: str | None = None
        self.messages: dict[str, Message] = {}
        self.current_message: Message | None = None
        self._inbox_ready = False
        self._watching: set[str] = set()

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
                with Vertical(id="chat"):
                    yield RichLog(id="chat-log", wrap=True, markup=False, highlight=False)
                    yield Input(placeholder="Write a message - Enter sends, Esc for the shortcuts",
                                id="chat-input")
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
    @work(exclusive=True, group="startup", exit_on_error=False)
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
            result = await self.push_screen_wait(SetupDialog(not s.has_identity(), not s.node,
                                                             s.known_nodes()))
            if result is None:
                self.exit()
                return
            if "display" in result:
                name = result["display"].lower().replace(" ", "-")
                s.new_identity(name, result["display"])
            if "node" in result:
                s.add_node(result["node"])
                for backup in result.get("backups", []):    # read from if the first is down
                    s.add_node(backup)
        s.subscribe_starter_groups()
        self._update_subtitle()
        await self.show_offline()
        self.refresh_groups()
        self.set_interval(REFRESH_SECONDS, self.action_refresh)

    @work(group="known-nodes", exclusive=True, exit_on_error=False)
    async def update_known_nodes(self) -> None:
        """Read the signed node list (UN-RFC 0010) in the background; quiet on failure."""
        try:
            await self.session.refresh_known_nodes()
        except (SessionError, OSError, ConnectionError, NNTPError, ValueError):
            pass
        try:                                    # names of groups and people (UN-RFC 0018, 0019)
            if await self.session.refresh_naming():
                await self._render_groups()
                if self.current_group:
                    self._render_threads()
        except (SessionError, OSError, ConnectionError, NNTPError, ValueError):
            pass

    def _update_subtitle(self) -> None:
        s = self.session
        more = f"  (+{len(s.nodes) - 1} more)" if len(s.nodes) > 1 else ""
        self.sub_title = (f"{s.display_name()} ({s.identity().fingerprint[:4]})  -  {s.node}{more}")

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
                    g.description = "(not on your nodes)"
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

    @work(exclusive=True, group="groups", exit_on_error=False)
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
                self._start_watches()
                self.update_known_nodes()
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
                "No groups yet - press g to browse the node's groups, or Ctrl+P to create one")
        where = f"{len(s.nodes)} nodes" if len(s.nodes) > 1 else "node"
        down = f" - not reachable: {', '.join(node_label(n) for n in s.unreachable)}" if s.unreachable else ""
        self.set_status(f"{len(available)} groups on {where}, {len(groups)} subscribed{down}")

    async def _render_groups(self) -> None:
        tree = self.query_one("#groups", Tree)
        tree.show_root = False
        def folder_key(node) -> str:
            return str(node.label).split(" (")[0].split(".*")[0]
        cursor = tree.cursor_node
        keep = (cursor.data if cursor is not None and cursor.data is not None
                else ("folder", folder_key(cursor)) if cursor is not None else None)
        scroll_y = tree.scroll_y
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
        nodes: dict = {}
        groups = list(self.groups.values())
        mine = [g for g in groups if g.group_id == self.session.my_inbox]
        for g in mine:                                   # private messages always first
            node = tree.root.add_leaf(label(g), data=g.group_id)
            nodes[g.group_id] = node
        contacts = self.session.contacts()
        if contacts:
            total = sum(self.session.unread_from(k) for k, _ in contacts)
            folder = Text("Contacts" + (f" ({total})" if total else ""))
            if total:
                folder.stylize("bold")
            cnode = tree.root.add(folder, expand="Contacts" in was_open or "Contacts" not in known)
            nodes[("folder", "Contacts")] = cnode
            for key, name in contacts:
                unread = self.session.unread_from(key)
                text = Text(f"• {name}" + (f" ({unread})" if unread else ""))
                if unread:
                    text.stylize("bold")
                nodes[CONTACT + key] = cnode.add_leaf(text, data=CONTACT + key)
        for top, items in by_hierarchy([g for g in groups if g not in mine]):
            parent = tree.root
            if top:
                unread = sum(self.session.unread_count(g.group_id) for g in items)
                folder = Text(f"{top}.*" + (f" ({unread})" if unread else ""))
                if unread:
                    folder.stylize("bold")
                parent = tree.root.add(folder, expand=top in was_open or top not in known)
                nodes[("folder", top)] = parent
            for g in items:
                nodes[g.group_id] = parent.add_leaf(label(g), data=g.group_id)
        # Put the cursor back where it was (or on the current group); the tree computes
        # line numbers on its next refresh, so do it after that.
        select = nodes.get(keep) or nodes.get(self.current_group)

        def restore() -> None:
            if select is not None and select.line >= 0:
                tree.move_cursor(select, animate=False)
            tree.scroll_to(y=scroll_y, animate=False)
        self.call_after_refresh(restore)

    def _group_label(self, g: GroupInfo) -> str:
        if g.group_id == self.session.my_inbox:
            return f"{group_icons('inbox')} Private messages"
        return f"{group_icons(g.type, self.session.manifest_data(g.group_id))} {self.session.group_label(g.group_id)}"

    @on(Tree.NodeSelected, "#groups")
    def _group_selected(self, event: Tree.NodeSelected) -> None:
        if isinstance(event.node.data, str):
            self.select_group(event.node.data)

    @work(exclusive=True, group="fetch", exit_on_error=False)
    async def select_group(self, gid: str) -> None:
        self.current_group = gid
        self.current_message = None
        self.refresh_bindings()
        if gid.startswith(CONTACT):
            try:
                await self.session.fetch_group(self.session.my_inbox)
            except (SessionError, OSError, ConnectionError) as exc:
                self.set_status(f"Offline ({exc}) - showing saved messages")
            self._render_threads()
            self.query_one("#chat-input" if self.view_of(gid) == "chat" else "#threads").focus()
            return
        g = self.groups.get(gid) or GroupInfo(gid)
        self.query_one("#threads-title", Static).update(f"{self.session.group_label(g.group_id)} - loading ...")
        try:
            await self.session.fetch_group(gid)
        except SessionError as exc:
            if "removed by its owner" in str(exc):
                self.notify(f"{self.session.group_label(g.group_id)} was removed by its owner. "
                            "Use 'Unsubscribe from group' (Ctrl+P) to forget it.",
                            severity="warning", timeout=10)
            else:
                self.set_status(f"{exc}")
        except (OSError, ConnectionError) as exc:
            self.set_status(f"Offline ({exc}) - showing saved posts")
        if self.current_group != gid:            # the user moved on, or the group was removed
            return
        if gid in self.groups:
            self.groups[gid].type = self.session.group_entry(gid).get("type")
        self._render_threads()
        self.query_one("#chat-input" if self.view_of(gid) == "chat" else "#threads").focus()
        if self.session.rules_unseen(gid) and isinstance(self.screen, Screen) \
                and not isinstance(self.screen, ModalScreen):
            self.action_group_info(first_time=True)

    # --- threads ---
    def _threaded(self, msgs: list[Message]) -> list[tuple[Message, int]]:
        """Threads, newest first; ``msgs`` is in the order the messages came."""
        pos = {m.message_id: i for i, m in enumerate(msgs)}
        by_id = {m.message_id: m for m in msgs}
        threads: dict[str, list[Message]] = {}
        for m in msgs:
            root = next((r for r in m.references if r in by_id), m.message_id)
            threads.setdefault(root, []).append(m)
        out = []
        for root, items in sorted(threads.items(),
                                  key=lambda kv: max(pos[x.message_id] for x in kv[1]), reverse=True):
            for m in sorted(items, key=lambda x: pos[x.message_id]):
                depth = 0 if m.message_id == root else min(len(m.references), 4)
                out.append((m, depth))
        return out

    def _render_threads(self) -> None:
        gid = self.current_group
        s = self.session
        if gid and gid.startswith(CONTACT):
            rows = [(m, 0) for m in s.conversation(gid[len(CONTACT):])]   # oldest first, like a chat
        elif gid == s.my_inbox:
            rows = self._threaded(s.visible(s.private_messages()))   # what you sent, too
        else:
            msgs = sorted(s.cache.get(gid, {}).values(), key=lambda m: m.number)
            rows = self._threaded(s.visible(msgs))      # replies to ignored people stay
        table = self.query_one("#threads", DataTable)
        keep = self.current_message.message_id if self.current_message else None
        table.clear()
        self.messages = {}
        for m, depth in rows:
            self.messages[m.message_id] = m
            flag = "●" if not s.is_read(m) else " "
            subject = ("  " * (depth - 1) + "└ " if depth else "") + (m.subject or "(no subject)")
            if m.private:
                subject = f"{ICONS['inbox']} " + subject
            elif m.encrypted and m.readable:
                subject = f"{ICONS['closed']} " + subject
            date = m.date.astimezone().strftime("%d %b %H:%M") if m.date else ""
            table.add_row(flag, Text(subject), Text(self._who(m)), date, key=m.message_id)
        self._render_title()
        mode = self.view_of(gid)
        self._apply_view(mode)
        if mode == "chat":
            chron = [m for m, _ in rows] if gid and gid.startswith(CONTACT) \
                else sorted((m for m, _ in rows), key=lambda m: m.number)
            self._render_chat(chron)
            return
        if keep in self.messages:
            table.move_cursor(row=table.get_row_index(keep))
        elif gid and gid.startswith(CONTACT) and rows:
            table.move_cursor(row=len(rows) - 1)                  # newest at the bottom

    # --- chat view (UN-RFC 0008 section 5) ---
    def view_of(self, gid: str | None) -> str:
        if not gid or gid == self.session.my_inbox:
            return "threads"
        views = self.session.data.setdefault("views", {})
        if gid in views:
            return views[gid]
        if gid.startswith(CONTACT):
            return "chat"
        return self.session.manifest_data(gid).get("view", "threads")

    def _apply_view(self, mode: str) -> None:
        chat = mode == "chat"
        self.query_one("#threads").display = not chat
        self.query_one("#article").display = not chat
        self.query_one("#chat").display = chat

    def _render_chat(self, msgs: list[Message]) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        mine = self.session.identity().key_text
        changed = False
        for m in msgs:
            own = m.author_key == mine
            who = "You" if own else (self.session.identity_label(m.author_key, m.from_name)
                                     if m.author_key else "anonymous")
            when = m.date.astimezone().strftime("%H:%M") if m.date else "     "
            text = split_signature(m.body)[0].rstrip() if m.readable else f"({m.subject})"
            line = Text(f"{when} ", style="dim")
            line.append(who, style="bold green" if own else "bold")
            if not own and self.session.contact_name(m.author_key):
                line.append(" √", style="green")
            line.append(": " + text.replace("\n", "\n" + " " * (len(when) + len(who) + 3)))
            log.write(line)
            if not self.session.is_read(m):
                self.session.mark_read(m, save=False)
                changed = True
        if changed:
            self._save_soon()

    def action_toggle_view(self) -> None:
        gid = self.current_group
        if not gid or gid == self.session.my_inbox:
            self.notify("Private messages are always shown as a list; open a contact for a chat",
                        severity="warning")
            return
        new = "threads" if self.view_of(gid) == "chat" else "chat"
        self.session.data.setdefault("views", {})[gid] = new
        self.session.save()
        self._render_threads()
        if new == "chat":
            self.query_one("#chat-input").focus()

    @on(Input.Submitted, "#chat-input")
    def _chat_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text or not self.current_group:
            return
        event.input.value = ""
        self.send_chat(self.current_group, text)

    @work(group="post", exit_on_error=False)
    async def send_chat(self, gid: str, text: str) -> None:
        subject = text.split("\n", 1)[0][:60] + ("…" if len(text) > 60 else "")
        self.set_status("Sending (computing postage) ...")
        try:
            if gid.startswith(CONTACT):
                key = gid[len(CONTACT):]
                owner = crypto.key_from_text(key)
                await self.session.send_private(personal_inbox_id(owner), subject, text, owner_key=owner)
            else:
                msgid = await self.session.post(gid, subject, text)
                if self.session.was_submitted(gid, msgid):
                    self.notify("Sent to the moderators for approval", timeout=8)
                await self.session.fetch_group(gid)
        except (SessionError, OSError, ConnectionError, ValueError) as exc:
            self.notify(f"Not sent: {exc}", severity="error", timeout=8)
            self.query_one("#chat-input", Input).value = text       # give the text back
            return
        self.set_status("")
        if self.current_group == gid:
            self._render_threads()

    def _who(self, m: Message) -> str:
        if m.to_key and self.current_group == self.session.my_inbox:
            return f"You → {self._key_label(m.to_key)}"
        if m.from_name == "You" and m.author_key == self.session.identity().key_text:
            return "You"
        if not m.author_key:
            return m.from_name or "anonymous"
        # your petname, else a registered name, else what they call themselves (UN-RFC 0019)
        return self.session.identity_label(m.author_key, m.from_name)

    def _key_label(self, key_text: str) -> str:
        """A contact's name, else the start of the key and its fingerprint."""
        if self.session.contact_name(key_text) or naming.names_of(self.session, key_text):
            return self.session.identity_label(key_text)
        try:
            fp = crypto.fingerprint(crypto.key_from_text(key_text))[:4]
        except crypto.CryptoError:
            fp = "????"
        return f"{key_text[8:20]}… ({fp})"

    def _render_title(self) -> None:
        gid = self.current_group
        if not gid:
            return
        if gid.startswith(CONTACT):
            key = gid[len(CONTACT):]
            msgs = self.session.conversation(key)
            self.query_one("#threads-title", Static).update(
                f"@ {self.session.contact_name(key) or key[:20]}  ·  {len(msgs)} messages, "
                f"{self.session.unread_from(key)} unread  ·  only the two of you can read them")
            return
        g = self.groups.get(gid)
        total = len(self.session.cache.get(gid, {}))
        unread = self.session.unread_count(gid)
        kind = {"closed": "closed, encrypted", "moderated": "moderated", "channel": "channel",
                "open": "open", "inbox": "inbox - only the owner can read"}.get(g.type if g else None, "")
        name = self._group_label(g).strip() if g else gid
        fast = "  ·  fast delivery" if self.session.manifest_data(gid).get("low_latency") else ""
        rules = "  ·  ? rules" if self.session.manifest_data(gid).get("rules") else ""
        hidden = self.session.hidden_by_blocks(gid)
        blocked = ("  ·  " + "; ".join(f"{n} hidden: blocked in {h}.*: {r}" for h, r, n in hidden[:2])
                   if hidden else "")
        self.query_one("#threads-title", Static).update(
            f"{name}  ·  {kind}{fast}  ·  {total} posts, {unread} unread{rules}{blocked}")

    def article(self, msg: Message) -> tuple[str, Text]:
        """The header (markup) and the body of a message, as the reader shows them."""
        date = msg.date.astimezone().strftime("%A %d %B %Y %H:%M") if msg.date else ""
        if msg.to_key:
            who = f"you  ·  to [b]{escape(self._key_label(msg.to_key))}[/b]"
        elif msg.private and msg.readable and not msg.sender_key:
            who = "anonymous (the sender did not identify themselves)"
        else:
            petname = self.session.contact_name(msg.author_key)
            registered = " ".join("@" + c.name for c in naming.names_of(self.session, msg.author_key))
            who = (f"{escape(msg.from_name)}  ·  key {escape(msg.author_key[:24])}…  ({msg.author_fp})"
                   + ("  ·  verified" if msg.sender_key else "")
                   + (f"  ·  registered [b]{escape(registered)}[/b]" if registered else "")
                   + (f"  ·  your contact [b]{escape(petname)}[/b]" if petname else ""))
        note = ("\n@ private message you sent - only they can read the copy on the node"
                if msg.to_key else
                "\n@ private message - only you can read it" if msg.private
                else "\n∩ end-to-end encrypted" if msg.encrypted else "")
        head = f"[b]{escape(msg.subject)}[/b]\nFrom: {who}\nDate: {date}{note}"
        if msg.readable:
            text, sig = split_signature(msg.body)
            body = Text("\n" + text)
            if sig is not None:
                body.append(SIG_SEPARATOR + sig, style="dim")
        else:
            body = Text("\n" + (msg.error or msg.subject))
        return head, body

    def neighbour(self, step: int) -> Message | None:
        """Move to the next (+1) or previous (-1) message in the list."""
        table = self.query_one("#threads", DataTable)
        row = table.cursor_row + step
        if not table.row_count or not 0 <= row < table.row_count:
            return None
        table.move_cursor(row=row)
        return self.messages.get(table.coordinate_to_cell_key((row, 0)).row_key.value)

    @on(DataTable.RowSelected, "#threads")
    def _open(self, event: DataTable.RowSelected) -> None:
        """Enter on a message: read it on the whole screen."""
        msg = self.messages.get(event.row_key.value)
        if msg is not None:
            self.current_message = msg
            self.push_screen(ReadScreen(msg))

    def action_read(self) -> None:
        if self.current_message is None:
            self.notify("Select a post first", severity="warning")
            return
        self.push_screen(ReadScreen(self.current_message))

    @on(DataTable.RowHighlighted, "#threads")
    def _row(self, event: DataTable.RowHighlighted) -> None:
        msg = self.messages.get(event.row_key.value)
        if msg is None:
            return
        self.current_message = msg
        self.refresh_bindings()
        head, body = self.article(msg)
        self.query_one("#article-head", Static).update(head)
        self.query_one("#article-body", Static).update(body)
        if isinstance(self.screen, ReadScreen):
            self.screen.show(msg)
        if not self.session.is_read(msg):
            self.session.mark_read(msg, save=False)
            self._save_soon()
            table = self.query_one("#threads", DataTable)
            table.update_cell(msg.message_id, "flag", " ")
            self._render_title()

    @work(exclusive=True, group="save", exit_on_error=False)
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
        if m.private and m.to_key:               # one you sent: write to them again
            self.compose_private(m.reply_inbox or personal_inbox_id(crypto.key_from_text(m.to_key)),
                                 f"Private message to {self._key_label(m.to_key)}", subject, quote,
                                 owner_key=crypto.key_from_text(m.to_key),
                                 references=[*m.references, m.message_id])
            return
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

    @work(group="post", exit_on_error=False)
    async def compose_private(self, target: str, heading: str, subject: str = "", quote: str = "",
                              owner_key: bytes | None = None,
                              references: list[str] | None = None) -> None:
        g = GroupInfo(target, type="inbox")
        result = await self.push_screen_wait(ComposeDialog(
            g, subject, quote, bool(references), heading=heading + "  @ only they can read it",
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

    @work(group="dialog", exit_on_error=False)
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

    @work(group="dialog", exit_on_error=False)
    async def action_bridges(self) -> None:
        result = await self.push_screen_wait(BridgesDialog(self.session.bridge_setting()))
        if not result:
            return
        await self.session.set_bridges(result["mode"], result["custom"])
        self.notify("Saved - Tor reconnects " +
                    ("directly" if result["mode"] == "off" else f"with {result['mode']} bridges"))
        self._watching.clear()
        self.refresh_groups()
        self._start_watches()

    def action_about(self) -> None:
        self.push_screen(AboutDialog())

    @work(group="dialog", exit_on_error=False)
    async def action_node_info(self) -> None:
        """Your nodes: add, remove, choose the default, see who runs them."""
        s = self.session
        while True:
            self.set_status("Asking your nodes ...")
            infos: dict = {}

            async def ask(address: str) -> None:
                try:
                    infos[address] = await asyncio.wait_for(s.node_info(address), 60)
                except (SessionError, OSError, ConnectionError, NNTPError, ValueError,
                        asyncio.TimeoutError, asyncio.IncompleteReadError):
                    infos[address] = None
            await asyncio.gather(*(ask(n) for n in s.nodes))
            self.set_status("")
            counts = {n: sum(1 for g in s.data["subscribed"] if s.node_for(g) == n) for n in s.nodes}
            result = await self.push_screen_wait(NodesDialog(s.nodes, infos, counts,
                                                             s.known_nodes()))
            if not result:
                return
            action, address = result
            if action == "add":
                value = await self.push_screen_wait(AddNodeDialog(s.known_nodes(), s.nodes))
                if value:
                    s.add_node(value)
                    self.notify(f"Added {value} - its groups are now in the group list (g)")
                    self._start_watches()
                    self._update_subtitle()
                    self.refresh_groups()
            elif action == "default":
                s.add_node(address, default=True)
                self._update_subtitle()
                self.notify(f"New groups and your inbox now go to {node_label(address)}")
            elif action == "remove":
                if not await self.push_screen_wait(ConfirmDialog(
                        "Stop using this node?",
                        f"{address}\n\nGroups you read from it move to your default node "
                        "(if it carries them). Nothing is deleted on the node itself.",
                        "Remove", danger=True)):
                    continue
                try:
                    s.remove_node(address)
                except SessionError as exc:
                    self.notify(str(exc), severity="error")
                    continue
                self._watching.discard(address)
                self._update_subtitle()
                self.refresh_groups()
            elif action == "info":
                if infos.get(address) is None:
                    self.notify(f"{node_label(address)} does not answer right now", severity="warning")
                    continue
                if await self.push_screen_wait(NodeInfoDialog(infos[address], address)):
                    break
        info = infos[address]
        try:
            operator = crypto.key_from_text(info["operator"])
        except (KeyError, crypto.CryptoError):
            self.notify("The node gives no valid operator key", severity="error")
            return
        self.compose_private(info["contact"], f"Message to the operator of {info.get('name', 'this node')}",
                             owner_key=operator)

    @work(group="post", exit_on_error=False)
    async def compose_post(self, g: GroupInfo, subject: str = "", quote: str = "",
                           references: list[str] | None = None) -> None:
        result = await self.push_screen_wait(ComposeDialog(
            g, subject, quote, bool(references), signature=self.session.signature(),
            has_rules=bool(self.session.manifest_data(g.group_id).get("rules"))))
        if not result:
            return
        subject, body = result
        self.set_status("Sending (computing postage) ...")
        try:
            msgid = await self.session.post(g.group_id, subject, body, references)
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(f"Not sent: {exc}", severity="error", timeout=8)
            return
        if self.session.was_submitted(g.group_id, msgid):
            self.notify("Sent to the moderators. It appears in the group when one of them "
                        "approves it.", timeout=10)
        else:
            self.notify("Sent")
        self.select_group(g.group_id)

    @work(group="dialog", exit_on_error=False)
    async def action_browse(self) -> None:
        self.set_status("Fetching group list ...")
        try:
            groups = await self.session.list_groups()
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(str(exc), severity="error")
            return
        self.set_status("")
        # other people's inboxes are not groups to read (only the owner can);
        # you write to someone from Contacts
        groups = [g for g in groups if not is_personal_inbox(g.group_id)
                  or g.group_id == self.session.my_inbox]
        # groups for programs (node list, root list, names) are not for reading,
        # unless you already follow one (UN-RFC 0008 section 3.1.1)
        groups = [g for g in groups if g.subscribed or not self.session.is_data_group(g.group_id)]
        await self.push_screen_wait(BrowseDialog(groups))
        self.refresh_groups()

    @work(group="dialog", exit_on_error=False)
    async def action_create_group(self) -> None:
        result = await self.push_screen_wait(CreateGroupDialog())
        if not result:
            return
        self.set_status(f"Creating {result['name']} ...")
        try:
            gid = await self.session.create_group(
                result["name"], result["gtype"], result["title"], local=result["local"],
                rules=result["rules"], view=result["view"], low_latency=result["low_latency"],
                min_pow=16 if result["low_latency"] else sess_default_pow())
        except (SessionError, ValueError, OSError, ConnectionError) as exc:
            self.notify(f"Could not create group: {exc}", severity="error", timeout=8)
            return
        self.notify(f"Created {gid}")
        self.current_group = gid
        self.refresh_groups()

    @work(group="dialog", exit_on_error=False)
    async def action_invite(self) -> None:
        g = self._need_group()
        if not g:
            return
        entry = self.session.group_entry(g.group_id)
        if g.type != "closed" or not entry.get("owner"):
            self.notify("You can only invite to closed groups you own", severity="warning")
            return
        key = await self.push_screen_wait(InputDialog(
            f"Invite to {self.session.group_label(g.group_id)}", "Paste the new member's key (they find it with k).",
            "ed25519:..."))
        if not key:
            return
        try:
            await self.session.invite(g.group_id, key)
        except Exception as exc:  # noqa: BLE001
            self.notify(f"Invite failed: {exc}", severity="error", timeout=8)
            return
        await self.push_screen_wait(InfoDialog(
            "Invitation sent - share this with them", f"unseenet:join?g={g.group_id}&n={self.session.node_for(g.group_id)}"))

    @work(group="dialog", exit_on_error=False)
    async def action_join(self) -> None:
        value = await self.push_screen_wait(InputDialog(
            "Join a group", "Paste a group ID or an unseenet:join link.", "dk.snak@... or unseenet:join?g=..."))
        if not value:
            return
        gid, node = value, None
        if value.startswith("unseenet:join?"):
            params = dict(p.split("=", 1) for p in value.split("?", 1)[1].split("&") if "=" in p)
            gid, node = params.get("g", ""), params.get("n") or None
        if node and node not in self.session.nodes:
            if await self.push_screen_wait(ConfirmDialog(
                    "The group is on another node",
                    f"{node}\n\nYou do not use this node yet. Add it? You keep your key; "
                    "the group is read from there.", "Add node")):
                self.session.add_node(node)
                self._start_watches()
                self._update_subtitle()
            else:
                node = None
        try:
            self.session.subscribe(gid, node=node if node in self.session.nodes else None)
        except ValueError:
            self.notify("That is not a valid group ID", severity="error")
            return
        self.current_group = gid
        self.refresh_groups()

    def _names_text(self) -> str:
        s = self.session
        mine = naming.my_names(s)
        lines = []
        for c in mine:
            lines.append(f"@{c.name}  ({c.kind}, until {c.expires.astimezone():%d %B %Y})")
        held = {c.name for c in mine}
        for name, action, when in naming.pending(s):
            if name not in held:
                lines.append(f"{action} {name}: sent {nm.parse_rfc3339(when).astimezone():%d %B %H:%M}, "
                             "waiting for the registrar (it decides after about an hour)")
        if not lines:
            lines.append("You have no names yet.")
        lines.append("")
        lines.append(f"Your key: {s.identity().key_text}")
        return "\n".join(lines)

    @work(group="dialog", exit_on_error=False)
    async def action_names(self) -> None:
        """Claim a name for your key, and see the ones you have (UN-RFC 0019)."""
        s = self.session
        self.set_status("Reading the registrar ...")
        try:
            await asyncio.wait_for(s.refresh_naming(), 120)
        except (SessionError, OSError, ConnectionError, NNTPError, ValueError, asyncio.TimeoutError):
            pass                                  # show what we have
        self.set_status("")
        result = await self.push_screen_wait(NamesDialog(self._names_text()))
        if not result:
            return
        action, name = result
        try:
            kind = nm.check_name(name)
        except nm.NameProblem as exc:
            self.notify(str(exc), severity="error")
            return
        to = None
        if action == "release":
            if not await self.push_screen_wait(ConfirmDialog(
                    f"Release @{name}?",
                    "You give the name up at once. Others can then claim it, and your "
                    "posts no longer show it.", "Release", danger=True)):
                return
        elif action == "transfer":
            to = await self.push_screen_wait(InputDialog(
                f"Transfer @{name} to another key",
                "Paste the key that should hold the name from now on - your new "
                "identity's, or someone else's. Your own key loses it.",
                "ed25519:..."))
            if not to:
                return
            try:
                crypto.key_from_text(to)
            except crypto.CryptoError:
                self.notify("That is not a key (ed25519:...)", severity="error")
                return
            if to == s.identity().key_text:
                self.notify("That is your own key", severity="warning")
                return
            if not await self.push_screen_wait(ConfirmDialog(
                    f"Transfer @{name}?", f"From now on the name belongs to\n\n{to}\n\n"
                    "Only that key can give it back.", "Transfer", danger=True)):
                return
        if kind == "domain" and action == "claim":
            record = f"{nm.dns_record_name(name)}  TXT  \"{nm.dns_record_value(s.identity().key_text)}\""
            if not await self.push_screen_wait(ConfirmDialog(
                    f"Claim {name}?",
                    "The registrar looks for this DNS record. Add it at your DNS provider "
                    f"first, then claim:\n\n{record}\n\nKeep it there: the name is renewed "
                    "every month for as long as the record is there.", "Claim")):
                return
        self.set_status(f"Sending your {action} for {name} ...")
        try:
            await naming.claim(s, name, action, to)
        except (SessionError, OSError, ConnectionError, NNTPError, nm.NameProblem) as exc:
            self.set_status("")
            self.notify(f"Could not send the claim: {exc}", severity="error")
            return
        self.set_status("")
        done = {"claim": "the name shows under @ when it is yours",
                "renew": "the new expiry shows under @",
                "transfer": "the name then belongs to the other key",
                "release": "the name is then free"}[action]
        self.notify(f"Sent your {action} of @{name} to the registrar. It decides after about an "
                    f"hour; the answer comes to your private messages, and {done}.", timeout=12)

    def action_show_key(self) -> None:
        self.push_screen(InfoDialog("Your key - share it to get private messages or invitations",
                                    self.session.identity().key_text))

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """A failing background task is reported and logged, never fatal."""
        if event.state != WorkerState.ERROR:
            return
        err = event.worker.error
        log = self.vault_path.resolve().parent / "unseenet-tui-errors.log"
        try:
            with open(log, "a") as f:
                f.write(f"--- {datetime.now().isoformat(timespec='seconds')} "
                        f"in {event.worker.name}\n")
                f.write("".join(traceback.format_exception(type(err), err, err.__traceback__)))
            where = f" - details in {log.name}"
        except OSError:
            where = ""
        self.notify(f"Something went wrong ({type(err).__name__}: {err}){where}",
                    severity="error", timeout=10)

    # --- push (UN-RFC 0008 section 2) ---
    def _start_watches(self) -> None:
        for address in self.session.nodes:
            if address not in self._watching:
                self._watching.add(address)
                self.watch_loop(address)

    @work(group="watch", exit_on_error=False)
    async def watch_loop(self, node: str) -> None:
        """Keep a second connection to a node open so new posts show up at once."""
        async def on_new(gid: str, message_id: str) -> None:
            if self.session.node_for(gid) == node:     # read from this node
                await self._on_push(gid, message_id)
        while node in self.session.nodes and node in self._watching:
            try:
                if await self.session.watch(on_new, node=node) is False:
                    return                         # the node cannot push; polling only
            except (OSError, ConnectionError, SessionError, NNTPError, asyncio.IncompleteReadError):
                pass
            await asyncio.sleep(15)                # reconnect after a pause

    async def _on_push(self, gid: str, message_id: str) -> None:
        s = self.session
        if gid in s.data["subscribed"] or gid == s.my_inbox:
            self.run_worker(self._fetch_and_show(gid), group="push", exit_on_error=False)

    async def _fetch_and_show(self, gid: str) -> None:
        s = self.session
        before = s.unread_count(gid)
        try:
            await s.fetch_group(gid)
        except (SessionError, OSError, ConnectionError):
            return
        current = self.current_group or ""
        if current == gid or (current.startswith(CONTACT) and gid == s.my_inbox):
            self._render_threads()
        elif gid == s.my_inbox and s.unread_count(gid) > before:
            self.notify("New private message")
        await self._render_groups()

    def get_system_commands(self, screen):
        """Everything the keys do is also in the command palette (Ctrl+P)."""
        yield from super().get_system_commands(screen)
        yield SystemCommand("About Unseenet", "The client, the project, source and documentation  [F1]",
                            self.action_about)
        yield SystemCommand("Tor bridges", "Connect through bridges where Tor is blocked",
                            self.action_bridges)
        if self.session is None:
            return
        commands = [
            ("New post", "Write a new post in the current group  [n]", self.action_new_post),
            ("Reply", "Reply to the selected post  [r]", self.action_reply),
            ("Private message", "Write privately to someone by their key  [m]", self.action_message),
            ("Browse groups", "See all groups on the node, subscribe or unsubscribe  [g]",
             self.action_browse),
            ("Create group", "Create an open, moderated, channel, closed or inbox group",
             self.action_create_group),
            ("Invite to closed group", "Give someone access to a closed group you own",
             self.action_invite),
            ("Join group", "Subscribe by group ID or unseenet:join link  [j]", self.action_join),
            ("Nodes", "Your nodes: add, remove, default, who runs them, write to an operator  [o]",
             self.action_node_info),
            ("Show my key", "Your key, to share for private messages and invitations  [k]",
             self.action_show_key),
            ("Names", "Claim a name such as @lorensen, see the names you hold  [@]",
             self.action_names),
            ("Edit signature", "The few lines added below '-- ' in your posts  [s]",
             self.action_signature),
            ("About this group", "Its rules, type, owner and settings  [?]", self.action_group_info),
            ("Switch chat / threads", "Show the current group as a chat or as threads  [v]",
             self.action_toggle_view),
            ("Edit group", "Owner: change title, description, rules, view and delivery",
             self.action_edit_group),
            ("Add contact", "Give the selected author, or any key, a name of your own  [a]",
             self.action_add_contact),
            ("Ignore this person", "Hide everything the selected post's author writes - only "
             "you know", self.action_ignore),
            ("People you ignore", "See who you ignore, and show someone again",
             self.action_ignored),
            ("Moderation queue", "Moderators: posts waiting for approval in groups you "
             "moderate", self.action_moderation),
            ("Make moderator", "Owner: let someone approve and withdraw posts in this group",
             lambda: self.action_add_role("moderators")),
            ("Make poster", "Owner of a channel: let someone post in it",
             lambda: self.action_add_role("posters")),
            ("Moderators and posters", "Owner: see them, and remove one",
             self.action_roles),
            ("Members of closed group", "Owner: see whom you invited, and remove a member",
             self.action_members),
            ("Ban from group", "Owner: the selected post's author may no longer post in this "
             "group", self.action_ban),
            ("Block in hierarchy", "Maintainer: block the selected post's author in your whole "
             "hierarchy", self.action_block),
            ("Show posts blocked by maintainers" if not self.session.data.get("show_blocked")
             else "Hide posts blocked by maintainers",
             "Maintainers of hierarchies can block people; you decide whether to see them",
             self.action_toggle_blocked),
            ("Banned from group", "Owner: see who is banned and why, and lift a ban",
             self.action_banned),
            ("Rename contact", "Change the name of the selected contact", self.action_rename_contact),
            ("Remove contact", "Forget the selected contact (your messages stay)",
             self.action_remove_contact),
            ("Refresh", "Fetch new posts now  [F5]", self.action_refresh),
            ("Private messages", "Open your inbox", self.action_open_inbox),
            ("Mark group as read", "Mark every post in the current group as read",
             self.action_mark_all_read),
            ("Unsubscribe from group", "Stop following the current group and forget it locally",
             self.action_unsubscribe),
            ("Withdraw post", "Take your post (or one in a group you own) back from the network  [D]",
             self.action_withdraw),
            ("Remove group from the network", "Delete a group you own from every node - final",
             self.action_remove_group),
        ]
        for title, help_text, callback in commands:
            yield SystemCommand(title, help_text, callback)

    def _owner_label(self, data: dict) -> str:
        key = data.get("owner", "")
        if key == self.session.identity().key_text:
            return "you"
        name = self.session.contact_name(key)
        return f"{name} √  ({key[:28]}…)" if name else f"{key[:36]}…"

    @work(group="dialog", exit_on_error=False)
    async def action_group_info(self, first_time: bool = False) -> None:
        g = self._need_group()
        if not g:
            return
        data = self.session.manifest_data(g.group_id)
        if not data:
            self.notify("Nothing known about this group yet - try again after a refresh",
                        severity="warning")
            return
        owner = bool(self.session.group_entry(g.group_id).get("owner"))
        result = await self.push_screen_wait(GroupInfoDialog(
            g.group_id, data, self._owner_label(data), owner, first_time,
            node=self.session.node_for(g.group_id) or ""))
        if data.get("rules"):
            self.session.mark_rules_seen(g.group_id)
        if result == "edit":
            self.action_edit_group()

    @work(group="dialog", exit_on_error=False)
    async def action_edit_group(self) -> None:
        g = self._need_group()
        if not g:
            return
        if not self.session.group_entry(g.group_id).get("owner"):
            self.notify("Only the group's owner can change it", severity="warning")
            return
        changes = await self.push_screen_wait(EditGroupDialog(self.session.manifest_data(g.group_id)))
        if not changes:
            return
        self.set_status("Publishing the new version of the group ...")
        try:
            await self.session.update_group(g.group_id, **changes)
        except (SessionError, OSError, ConnectionError, ValueError) as exc:
            self.notify(f"Not changed: {exc}", severity="error", timeout=8)
            return
        self.session.mark_rules_seen(g.group_id)
        self.notify("Group updated")
        self._render_threads()

    @work(group="dialog", exit_on_error=False)
    async def action_ignore(self) -> None:
        """Ignore the selected post's author (#72)."""
        m, s = self.current_message, self.session
        key = (m.sender_key or m.author_key) if m else ""
        if not key or key == s.identity().key_text:
            self.notify("Select a post by the person you want to ignore", severity="warning")
            return
        who = s.identity_label(key, m.from_name)
        if not await self.push_screen_wait(ConfirmDialog(
                f"Ignore {who}?",
                f"{key}\n\nTheir posts and private messages are hidden from you in every "
                "group. Others still see them, and they are not told. You can show them "
                "again under 'People you ignore' (Ctrl+P).", "Ignore")):
            return
        try:
            s.ignore(key, who)
        except (SessionError, crypto.CryptoError) as exc:
            self.notify(f"Not ignored: {exc}", severity="error")
            return
        self.current_message = None
        self.notify(f"Ignoring {who}")
        await self._render_groups()
        self._render_threads()

    @work(group="dialog", exit_on_error=False)
    async def action_ban(self) -> None:
        """Owner: ban the selected post's author from the group (UN-RFC 0004, 5.1)."""
        m, s, gid = self.current_message, self.session, self.current_group
        if not gid or not s.group_entry(gid).get("owner"):
            self.notify("Only a group's owner can ban people from it. You can ignore them "
                        "(Ctrl+P: Ignore this person).", severity="warning")
            return
        if m is None or m.private or not m.author_key or m.author_key == s.identity().key_text:
            self.notify("Select a post by the person you want to ban", severity="warning")
            return
        who = s.identity_label(m.author_key, m.from_name)
        reason = await self.push_screen_wait(InputDialog(
            f"Ban {who} from {s.group_label(gid)}?",
            "Nodes refuse their new posts here, and clients hide the old ones. The ban and "
            "its reason are public: anyone can read them in the group's settings. Give a short "
            "reason:", "e.g. threats against other members"))
        if not reason:
            return
        self.set_status("Banning ...")
        try:
            await s.ban(gid, m.author_key, reason)
        except (SessionError, OSError, ConnectionError, crypto.CryptoError) as exc:
            self.set_status("")
            self.notify(f"Not banned: {exc}", severity="error", timeout=8)
            return
        self.set_status("")
        self.current_message = None
        self.notify(f"{who} is banned from {s.group_label(gid)}")
        self._render_threads()

    @work(group="dialog", exit_on_error=False)
    async def action_moderation(self) -> None:
        """Approve or reject submissions (UN-RFC 0009 section 3)."""
        s = self.session
        try:
            await s.fetch_group(s.my_inbox)
        except (SessionError, OSError, ConnectionError):
            pass                                  # show what we have
        queue = s.submissions()
        if not queue:
            self.notify("Nothing waiting for approval")
            return
        items = []
        for m, art in queue:
            who = s.identity_label(art["Author-Key"], art.get("From", ""))
            items.append((m.message_id, f"{s.group_label(art.group)}: {art.get('Subject', '')} - {who}",
                          f"From: {who}\nGroup: {s.group_label(art.group)}\n"
                          f"Subject: {art.get('Subject', '')}\n\n{art.body}"))
        result = await self.push_screen_wait(ModerationDialog(items))
        if not result:
            return
        action, which = result
        msg, art = next((m, a) for m, a in queue if m.message_id == which)
        try:
            if action == "approve":
                await s.approve_submission(msg, art)
                self.notify("Approved and posted")
            else:
                if not await self.push_screen_wait(ConfirmDialog(
                        "Reject this post?", "It is not posted, and the queue forgets it. "
                        "The author is not told unless you write to them.", "Reject")):
                    return
                await s.reject_submission(msg)
                self.notify("Rejected")
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(f"Not done: {exc}", severity="error", timeout=8)
            return
        if self.current_group == art.group:
            self.select_group(art.group)

    def _owned_group(self, kind: str | None = None) -> str | None:
        s, gid = self.session, self.current_group
        if not gid or not s.group_entry(gid).get("owner"):
            self.notify("Only the group's owner can do this", severity="warning")
            return None
        if kind and s.group_entry(gid).get("type") != kind:
            self.notify(f"This is only for {kind} groups", severity="warning")
            return None
        return gid

    @work(group="dialog", exit_on_error=False)
    async def action_add_role(self, role: str) -> None:
        """Owner: add a moderator or (in a channel) a poster (UN-RFC 0004)."""
        gid = self._owned_group("channel" if role == "posters" else None)
        if not gid:
            return
        s, m = self.session, self.current_message
        mine = s.identity().key_text
        key = m.author_key if m and not m.private and m.author_key and m.author_key != mine else ""
        what = "moderator" if role == "moderators" else "poster"
        key = await self.push_screen_wait(InputDialog(
            f"Make a {what} of {s.group_label(gid)}",
            ("Moderators can post directly, approve others' posts and withdraw any post. "
             if role == "moderators" else "Posters can post in this channel. ")
            + "Their key - filled in from the selected post:", "ed25519:...", value=key))
        if not key:
            return
        try:
            await s.set_role(gid, role, key.strip(), True)
        except (SessionError, OSError, ConnectionError, crypto.CryptoError) as exc:
            self.notify(f"Not changed: {exc}", severity="error", timeout=8)
            return
        self.notify(f"{s.identity_label(key.strip())} is now a {what}")

    @work(group="dialog", exit_on_error=False)
    async def action_roles(self) -> None:
        gid = self._owned_group()
        if not gid:
            return
        s = self.session
        data = s.manifest_data(gid)
        people = [(k, f"{s.identity_label(k)} (moderator)") for k in data.get("moderators", [])]
        people += [(k, f"{s.identity_label(k)} (poster)") for k in data.get("posters", [])]
        if not people:
            self.notify("This group has no moderators or posters. Ctrl+P: Make moderator.")
            return
        key = await self.push_screen_wait(KeyListDialog(
            f"Moderators and posters of {s.group_label(gid)}",
            "Removing someone takes their role away from now on.", people, "Remove"))
        if not key:
            return
        role = "moderators" if key in data.get("moderators", []) else "posters"
        try:
            await s.set_role(gid, role, key, False)
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(f"Not changed: {exc}", severity="error", timeout=8)
            return
        self.notify("Removed")

    @work(group="dialog", exit_on_error=False)
    async def action_members(self) -> None:
        gid = self._owned_group("closed")
        if not gid:
            return
        s = self.session
        people = [(k, s.identity_label(k)) for k in s.members(gid)]
        if not people:
            self.notify("No members recorded here. Members you invited from another device, "
                        "or before version 0.3.0, are not listed.", timeout=10)
            return
        key = await self.push_screen_wait(KeyListDialog(
            f"Members of {s.group_label(gid)}",
            "The people you invited from this client. Removing one gives everyone else a new "
            "key; members you invited elsewhere are not listed and lose access too, so invite "
            "them again.", people, "Remove member"))
        if not key:
            return
        if not await self.push_screen_wait(ConfirmDialog(
                f"Remove {s.identity_label(key)}?",
                "The group gets a new key that the others receive. They cannot read anything "
                "new - but they keep everything they have already read.", "Remove",
                danger=True)):
            return
        self.set_status("Making a new key for the group ...")
        try:
            await s.remove_member(gid, key)
        except (SessionError, OSError, ConnectionError) as exc:
            self.set_status("")
            self.notify(f"Not removed: {exc}", severity="error", timeout=8)
            return
        self.set_status("")
        self.notify("Removed. The others have the new key.")

    @work(group="dialog", exit_on_error=False)
    async def action_block(self) -> None:
        """Maintainer: block the selected author across the hierarchy (UN-RFC 0018, 5.4)."""
        m, s, gid = self.current_message, self.session, self.current_group
        me = s.identity().key_text
        mine = [h for h in naming.governing(s, gid or "") if h.maintainer == me] if gid else []
        if not mine:
            self.notify("Only the maintainer of a hierarchy above this group can block "
                        "people in it", severity="warning")
            return
        if m is None or m.private or not m.author_key or m.author_key == me:
            self.notify("Select a post by the person you want to block", severity="warning")
            return
        who = s.identity_label(m.author_key, m.from_name)
        reason = await self.push_screen_wait(InputDialog(
            f"Block {who} in {mine[0].name}.*?",
            "Nodes that honour blocks refuse their posts in every group under "
            f"{mine[0].name}, and readers hide them unless they choose to see them. The "
            "block and its reason are public. Reason (required):",
            "e.g. threats against members in several groups"))
        if not reason:
            return
        self.set_status("Posting your hierarchy list ...")
        try:
            where = await naming.block(s, gid, m.author_key, reason)
        except (SessionError, OSError, ConnectionError, ValueError, crypto.CryptoError) as exc:
            self.set_status("")
            self.notify(f"Not blocked: {exc}", severity="error", timeout=8)
            return
        self.set_status("")
        self.current_message = None
        self.notify(f"{who} is blocked in {where}.*")
        self._render_threads()

    def action_toggle_blocked(self) -> None:
        on = not self.session.data.get("show_blocked")
        self.session.set_show_blocked(on)
        self.notify("Showing posts blocked by maintainers" if on
                    else "Hiding posts blocked by maintainers")
        self._render_threads()

    @work(group="dialog", exit_on_error=False)
    async def action_banned(self) -> None:
        s, gid = self.session, self.current_group
        if not gid or not s.group_entry(gid).get("owner"):
            self.notify("Only a group's owner can see and lift its bans here; "
                        "? shows the group's settings", severity="warning")
            return
        people = [(k, (s.identity_label(k) + (f" - {r}" if r else ""))) for k, r in s.banned(gid)]
        if not people:
            self.notify("Nobody is banned from this group")
            return
        key = await self.push_screen_wait(KeyListDialog(
            f"Banned from {s.group_label(gid)}", "Lifting a ban lets them post here again.",
            people, "Lift ban"))
        if not key:
            return
        try:
            await s.unban(gid, key)
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(f"Not lifted: {exc}", severity="error")
            return
        self.notify("Ban lifted")
        self._render_threads()

    @work(group="dialog", exit_on_error=False)
    async def action_ignored(self) -> None:
        people = self.session.ignored()
        if not people:
            self.notify("You do not ignore anyone")
            return
        key = await self.push_screen_wait(KeyListDialog(
            "People you ignore", "Their posts and messages are hidden from you, everywhere. "
            "Nobody else knows: the list stays in your vault.", people, "Show again"))
        if not key:
            return
        self.session.unignore(key)
        self.notify("Shown again")
        await self._render_groups()
        self._render_threads()

    @work(group="dialog", exit_on_error=False)
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

    @work(group="dialog", exit_on_error=False)
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

    @work(group="dialog", exit_on_error=False)
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

    @work(group="dialog", exit_on_error=False)
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

    @work(group="dialog", exit_on_error=False)
    async def action_unsubscribe(self) -> None:
        g = self._need_group()
        if not g:
            return
        if g.group_id == self.session.my_inbox:
            self.notify("Your private messages cannot be unsubscribed", severity="warning")
            return
        if not await self.push_screen_wait(ConfirmDialog(
                f"Unsubscribe from {self.session.group_label(g.group_id)}?",
                "You stop following the group, and its saved posts are deleted from this "
                "computer. The group stays on the network; you can subscribe again with g.",
                "Unsubscribe")):
            return
        self.session.forget_group(g.group_id)
        self.current_group = None
        self.notify(f"Unsubscribed from {self.session.group_label(g.group_id)}")
        self.refresh_groups()

    @work(group="dialog", exit_on_error=False)
    async def action_remove_group(self) -> None:
        g = self._need_group()
        if not g:
            return
        if not self.session.group_entry(g.group_id).get("owner"):
            self.notify("Only the group's owner can remove it. You can unsubscribe instead.",
                        severity="warning")
            return
        if not await self.push_screen_wait(ConfirmDialog(
                f"Remove {self.session.group_label(g.group_id)} from the network?",
                "Every node deletes the group and all its posts, and the name can never be "
                "used again - not even by you. This cannot be undone.\n\n"
                "Copies people have already saved cannot be deleted.",
                "Remove for good", danger=True)):
            return
        self.set_status(f"Removing {self.session.group_label(g.group_id)} ...")
        try:
            await self.session.remove_group(g.group_id)
        except (SessionError, OSError, ConnectionError) as exc:
            self.notify(f"Not removed: {exc}", severity="error", timeout=8)
            return
        self.current_group = None
        self.notify(f"{self.session.group_label(g.group_id)} removed")
        self.refresh_groups()

    @work(group="dialog", exit_on_error=False)
    async def action_withdraw(self) -> None:
        """Withdraw the selected post (UN-RFC 0004, section 7)."""
        m, s = self.current_message, self.session
        if m is None or not s.may_cancel(m):
            self.notify("You can withdraw your own posts, and any post in a group you own "
                        "or moderate.", severity="warning")
            return
        mine = m.author_key == s.identity().key_text
        if not await self.push_screen_wait(ConfirmDialog(
                f"Withdraw \"{m.subject or '(no subject)'}\"?",
                ("Your post" if mine else "This post") + " is taken back from every node "
                "that follows the protocol, and other clients stop showing it.\n\n"
                "It is withdrawn, not deleted: people who have read it may have kept a "
                "copy, and nodes or programs that ignore withdrawals can keep it.",
                "Withdraw", danger=True)):
            return
        self.set_status("Withdrawing ...")
        try:
            await s.cancel(m)
        except (SessionError, OSError, ConnectionError) as exc:
            self.set_status("")
            self.notify(f"Not withdrawn: {exc}", severity="error", timeout=8)
            return
        self.set_status("")
        self.current_message = None
        self._render_threads()
        self.notify("Withdrawn")

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
