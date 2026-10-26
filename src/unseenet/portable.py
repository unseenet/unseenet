"""Where the client keeps its files, and where it finds Tor.

Installed with pip, the client works in the current directory, as it always
has: ``unseenet.vault`` and ``unseenet-tor/`` next to where you start it.

A **portable build** (the zips made by unseenet-portable's
``tools/build_portable.py``, e.g. on a USB stick) is laid out like this::

    Unseenet/
      UNSEENET-PORTABLE          marker: this is a portable installation
      data/                      vault, offline cache, Tor's state - all yours
      linux/  unseenet-tui, tor/tor, ...
      windows/ unseenet-tui.exe, tor/tor.exe, ...
      macos/  unseenet-tui, tor/tor, ...

and keeps everything in ``data/`` beside the programs, whichever directory
it was started from, and uses the Tor that came with it. Nothing is written
to the computer it runs on (see docs/portable.md for what the OS itself may
record).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MARKER = "UNSEENET-PORTABLE"
DATA_DIR = "data"


def program_dir() -> Path:
    """The directory of the running program (the build's folder when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def portable_root() -> Path | None:
    """The portable installation this program belongs to, if any.

    ``UNSEENET_HOME`` overrides it (useful for testing and for unusual layouts).
    """
    env = os.environ.get("UNSEENET_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = program_dir()
    for candidate in (here, here.parent, here.parent.parent):
        if (candidate / MARKER).is_file():
            return candidate
    return None


def data_dir() -> Path:
    """Where the vault and Tor's state live: ``data/`` when portable, else the cwd."""
    root = portable_root()
    if root is None:
        return Path(".")
    path = root / DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_vault_path() -> Path:
    return data_dir() / "unseenet.vault"


def bundled_tor() -> Path | None:
    """The tor binary shipped with a portable build (``tor/`` beside the program)."""
    name = "tor.exe" if sys.platform == "win32" else "tor"
    for base in (program_dir(), program_dir().parent):
        candidate = base / "tor" / name
        if candidate.is_file():
            return candidate
    return None
