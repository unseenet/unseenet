"""Markdown trees (core.markup, UN-RFC 0031) as Rich text for the terminal client.

Links show where they go; images show their alt text; emoji show as the
glyph, or as the shortcode on a terminal without the glyphs (the Linux
console of the bootable image).
"""

from __future__ import annotations

import os

from rich.style import Style
from rich.text import Text

from ..core.groups import GROUP_REF_RE

QUOTE = "│ "
WIDE = 60


def _glyphs() -> bool:
    return os.environ.get("TERM", "") not in ("linux", "dumb")


def group_links(text: str, base: str = "") -> Text:
    """Text with its #group references (unseenet #172) shown as links: a click runs
    the app's group_ref action, which opens the group or asks before subscribing."""
    out = Text()
    last = 0
    for m in GROUP_REF_RE.finditer(text):
        if m.start() > last:
            out.append(text[last:m.start()], style=base or None)
        ref = m.group(0)
        out.append(ref, style=Style.parse((base + " bold underline").strip())
                   + Style.from_meta({"@click": f"app.group_ref({ref!r})"}))
        last = m.end()
    if last < len(text):
        out.append(text[last:], style=base or None)
    return out


def inline(nodes: list[dict], base: str = "", refs: bool = True) -> Text:
    out = Text()
    glyphs = _glyphs()
    for n in nodes:
        t = n.get("t")
        if t == "text":
            out.append(group_links(n["v"], base) if refs else Text(n["v"], style=base or ""))
        elif t == "br":
            out.append("\n")
        elif t == "code":
            out.append(n["v"], style="bold " + (base + " " if base else "") + "on grey23")
        elif t == "emoji":
            out.append(n["v"] if glyphs else f":{n['name']}:", style=base or None)
        elif t == "image":
            out.append(f"[image: {n['alt'] or 'no description'}]", style="dim")
        elif t == "link":
            inner = inline(n["c"], (base + " underline").strip(), refs=False)
            out.append(inner)
            shown = inner.plain.strip()
            if shown != n["href"]:                 # always show the real address (section 3.4)
                out.append(f" <{n['href']}>", style="dim")
        elif t in ("em", "strong", "del"):
            style = {"em": "italic", "strong": "bold", "del": "strike"}[t]
            out.append(inline(n["c"], (base + " " + style).strip(), refs))
    return out


def blocks(tree: list[dict], prefix: str = "", tight: bool = False) -> Text:
    out = Text()
    first = True
    for b in tree:
        if not first:
            out.append("\n" if tight else "\n" + (prefix.rstrip() + "\n" if prefix else "\n"))
        first = False
        t = b.get("t")
        if t == "p":
            out.append(_prefixed(inline(b["c"]), prefix))
        elif t == "h":
            style = "bold underline" if b["n"] == 1 else "bold"
            out.append(_prefixed(inline(b["c"], style), prefix))
        elif t == "code":
            code = Text(b["v"], style="on grey15")
            if b.get("lang"):
                out.append(prefix + b["lang"] + "\n", style="dim")
            out.append(_prefixed(code, prefix + "  "))
        elif t == "hr":
            out.append(prefix + "─" * WIDE, style="dim")
        elif t == "quote":
            out.append(_dim(blocks(b["c"], prefix + QUOTE)))
        elif t in ("ul", "ol"):
            for i, item in enumerate(b["items"]):
                if i:
                    out.append("\n")
                mark = "• " if t == "ul" else f"{b['start'] + i}. "
                for j, line in enumerate(blocks(item, tight=True).split("\n")):
                    if j:
                        out.append("\n")
                    out.append(prefix)
                    out.append(mark if j == 0 else " " * len(mark), style="bold" if j == 0 else None)
                    out.append(line)
    return out


def _prefixed(text: Text, prefix: str) -> Text:
    if not prefix:
        return text
    out = Text()
    for i, line in enumerate(text.split("\n")):
        if i:
            out.append("\n")
        out.append(prefix, style="dim")
        out.append(line)
    return out


def _dim(text: Text) -> Text:
    text.stylize("italic")
    return text
