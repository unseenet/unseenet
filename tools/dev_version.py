"""The version of a development build, from git: ``0.2.1.dev3`` is the third
commit after v0.2.0.

    python tools/dev_version.py            print it
    python tools/dev_version.py --write    also put it in src/unseenet/__init__.py
                                           (for the build only; never committed)

Versions follow PEP 440, so pip and the client sort them correctly:
0.2.0 < 0.2.1.dev3 < 0.2.1a1 < 0.2.1. After an alpha, development builds
lead to the next one: v0.2.1a1 + 2 commits is 0.2.1a2.dev2.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "src" / "unseenet" / "__init__.py"
_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")


def dev_version(tag: str, distance: int) -> str:
    """The version ``distance`` commits after release tag ``tag``."""
    m = _TAG.match(tag)
    if not m:
        raise ValueError(f"not a release tag: {tag!r}")
    major, minor, patch, pre, num = m.groups()
    if distance == 0:
        return tag[1:]                      # the release itself
    if pre:
        return f"{major}.{minor}.{patch}{pre}{int(num) + 1}.dev{distance}"
    return f"{major}.{minor}.{int(patch) + 1}.dev{distance}"


def _key(tag: str) -> tuple:
    m = _TAG.match(tag)
    major, minor, patch, pre, num = m.groups()
    return (int(major), int(minor), int(patch), pre is None, pre or "", int(num or 0))


def newest_of_series(tag: str, tags: list[str]) -> str:
    """``tag``, or a newer release of the same MAJOR.MINOR tagged on a release branch
    (v0.6.1 on release/0.6 while main is past v0.6.0): main's development builds then
    count on from it - 0.6.2.devN, not 0.6.1.devN, which PEP 440 sorts below 0.6.1."""
    m = _TAG.match(tag)
    if not m or m.group(4):
        return tag
    same = [t for t in tags if _TAG.match(t) and not _TAG.match(t).group(4)
            and _TAG.match(t).groups()[:2] == m.groups()[:2]]
    return max([tag, *same], key=_key)


def from_git() -> str:
    out = subprocess.run(["git", "describe", "--tags", "--long", "--match", "v[0-9]*"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    tag, distance, _sha = out.rsplit("-", 2)
    if int(distance):
        tags = subprocess.run(["git", "tag", "--list", "v[0-9]*"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.split()
        tag = newest_of_series(tag, tags)
    return dev_version(tag, int(distance))


def write(version: str) -> None:
    text = INIT.read_text()
    new, n = re.subn(r'__version__ = "[^"]+"', f'__version__ = "{version}"', text)
    if n != 1:
        sys.exit("no __version__ in src/unseenet/__init__.py")
    INIT.write_text(new)


if __name__ == "__main__":
    v = from_git()
    if "--write" in sys.argv[1:]:
        write(v)
    print(v)
