#!/usr/bin/env python3
"""Check the header blocks of the UN-RFCs (UN-RFC 0000 sections 3.3 and 3.4).

    tools/check_rfc_headers.py                 check, exit 1 on a mistake
    tools/check_rfc_headers.py --release X.Y.Z  before tagging core X.Y.Z: every
                                               "unseenet main (unreleased)" becomes
                                               "unseenet X.Y.Z", then check

Why this exists: a maintainer's acceptance of a pull request agrees to *that change*
(a new UN-RFC, an amendment, a correction). It is not a status and never changes a
document's ``Status:`` line - "Accepted" was once written there by mistake (#738).
Status follows section 3.3 only, and while Unseenet is pre-alpha every protocol
document is Draft. What is built is said by the ``Implemented:`` line instead.

Run by tools/docs_check.sh (the docs workflow, on every pull request that touches
rfc/) and by tests/test_rfc_headers.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RFC_DIR = Path(__file__).resolve().parent.parent / "rfc"

STATUSES = {"Draft", "Proposed", "Standard", "Active", "Obsoleted"}   # section 3.3
CATEGORIES = {"Standards Track", "Informational", "Experimental", "Process"}
PRE_ALPHA = True          # section 3.3: the first series stays Draft until 1.0

UNRELEASED = "unseenet main (unreleased)"
_IMPL = re.compile(r"""^(?:
      -                                                     # not built yet
    | (?P<list>[a-z][a-z-]*\ (?:\d+\.\d+\.\d+|main\ \(unreleased\))
        (?:,\ [a-z][a-z-]*\ (?:\d+\.\d+\.\d+|main\ \(unreleased\)))*)
      (?:;\ partly\ -\ .+)?                                 # what is still missing
    )$""", re.X)


def header(text: str) -> dict[str, str]:
    """The ``Key: value`` lines of the header block (the first ``` block)."""
    block = text.split("```")[1] if text.count("```") >= 2 else ""
    out = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z-]+): (.*?)\s*$", line)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2).strip()
    m = re.search(r"UN-RFC: (\d{4})", block)
    if m:
        out["UN-RFC"] = m.group(1)
    return out


def problems(path: Path) -> list[str]:
    """What is wrong with one document's header, as messages."""
    h = header(path.read_text(encoding="utf-8"))
    name, found = path.name, []
    status, cat = h.get("Status"), h.get("Category")
    if h.get("UN-RFC") != path.stem[-4:]:
        found.append(f"{name}: the header's UN-RFC number does not match the file name")
    if cat not in CATEGORIES:
        found.append(f"{name}: Category {cat!r} is not one of {sorted(CATEGORIES)}")
    if status not in STATUSES:
        found.append(f"{name}: Status {status!r} is not a status of UN-RFC 0000 section 3.3 "
                     f"({', '.join(sorted(STATUSES))}). A maintainer's acceptance agrees to a "
                     "change; it is not a status (section 3.3).")
    elif PRE_ALPHA and cat != "Process" and status != "Draft":
        found.append(f"{name}: Status {status} - every protocol document of the first series "
                     "is Draft while Unseenet is pre-alpha (UN-RFC 0000 section 3.3)")
    elif cat == "Process" and status not in ("Active", "Draft"):
        found.append(f"{name}: a Process document is Active or Draft")
    impl = h.get("Implemented")
    if cat == "Standards Track":
        if impl is None:
            found.append(f"{name}: no Implemented: line (UN-RFC 0000 section 3.4)")
        elif not _IMPL.match(impl):
            found.append(f"{name}: Implemented {impl!r} - write '-', "
                         "'unseenet 0.5.0', 'unseenet 0.4.0, unseenet-gateway 0.1.0', "
                         f"'{UNRELEASED}', and '; partly - <what is missing>' when only part is built")
    return found


def release(version: str) -> list[Path]:
    """Name ``version`` where the core's main is still marked unreleased."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"not a version: {version}")
    changed = []
    for path in sorted(RFC_DIR.glob("un-rfc-*.md")):
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("Implemented:") and UNRELEASED in line:
                lines[i] = line.replace(UNRELEASED, f"unseenet {version}")
        new = "\n".join(lines)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(path)
    return changed


def main(argv: list[str]) -> int:
    if argv[:1] == ["--release"]:
        if len(argv) != 2:
            raise SystemExit(__doc__)
        for p in release(argv[1]):
            print(f"{p.name}: Implemented now names unseenet {argv[1]}")
    found = [m for p in sorted(RFC_DIR.glob("un-rfc-*.md")) for m in problems(p)]
    for m in found:
        print(m, file=sys.stderr)
    if not found:
        print(f"{len(list(RFC_DIR.glob('un-rfc-*.md')))} UN-RFC headers are in order")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
