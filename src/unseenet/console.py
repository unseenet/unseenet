"""Looking right on the Linux console (TERM=linux), e.g. on the bootable image.

The console's built-in font has the box-drawing characters of CP437 (─ │ ┌ ┐ ═
█ ▀ ▄ and friends) but not the thin blocks (▔ ▁) Textual draws its input
fields, buttons and lists with, nor rounded corners (╭ ╮), so they come out as
"#". On the console the apps use borders the font has.
"""

from __future__ import annotations

import os

LINUX_CONSOLE_CSS = """
Input, TextArea, OptionList, SelectCurrent { border: solid $primary-darken-2; }
Input:focus, TextArea:focus, OptionList:focus, Select:focus > SelectCurrent { border: solid $accent; }
Button { border: none; height: 1; min-width: 10; margin: 0 1; }
Button:focus { text-style: bold reverse; }
.dialog .buttons { height: 1; margin-top: 1; }
#status-box, .round { border: solid $primary-darken-2; }
"""


def on_linux_console() -> bool:
    return os.environ.get("TERM") == "linux"


def console_css() -> str:
    """Extra CSS for an App's CSS when it runs on the Linux console."""
    return LINUX_CONSOLE_CSS if on_linux_console() else ""
