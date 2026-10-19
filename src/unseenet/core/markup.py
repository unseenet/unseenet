"""Markdown and emoji (UN-RFC 0031): a message's text as a small, safe tree.

Both clients render the same tree, so they agree on what a message says:
the terminal client as Rich text, the web client as DOM nodes. The tree is
plain dicts and lists (JSON as it is):

blocks:  {"t": "p", "c": inl}          {"t": "h", "n": 1-3, "c": inl}
         {"t": "quote", "c": blocks}   {"t": "code", "lang": str, "v": str}
         {"t": "ul"|"ol", "start": n, "items": [blocks, ...]}   {"t": "hr"}
inline:  {"t": "text", "v": str}   {"t": "br"}   {"t": "code", "v": str}
         {"t": "em"|"strong"|"del", "c": inl}
         {"t": "link", "href": str, "c": inl}
         {"t": "image", "blob": hash, "alt": str}
         {"t": "emoji", "v": glyph, "name": shortcode}

Nothing in the tree points outside the network except links, which only a
reader's click follows (section 3.4); images point only at blobs (3.5).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources

from markdown_it import MarkdownIt

KIND_CHAT = "chat"
MARKDOWN_TYPE = "text/markdown; charset=utf-8; variant=unseenet"
PLAIN_TYPE = "text/plain; charset=utf-8"
LINK_SCHEMES = ("http", "https", "unseenet", "news")
MAX_HEADING = 3
MAX_LIST_DEPTH = 4
MAX_TEXT = 256 * 1024                 # a crafted message must not hang a client (section 7)
_SHORTCODE = re.compile(r":([a-z0-9_+\-]+):")
_BLOB = re.compile(r"^blob:([0-9a-f]{16,128})$")


def is_markdown(content_type: str | None) -> bool:
    """Whether a message's Content-Type says Markdown (section 2)."""
    return (content_type or "").split(";")[0].strip().lower() == "text/markdown"


@lru_cache(maxsize=1)
def emoji_table() -> dict[str, str]:
    """The shortcode table: gemoji 4.1.0's aliases (section 5.2)."""
    data = json.loads(resources.files("unseenet").joinpath("emoji.json").read_text("utf-8"))
    return data["emoji"]


def emoji(name: str) -> str | None:
    return emoji_table().get(name)


@lru_cache(maxsize=2)
def _parser(chat: bool) -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("strikethrough")
    md.disable("html_block").disable("html_inline")
    if chat:                          # chat stays chat (section 3.3)
        md.disable(["heading", "lheading", "list", "blockquote", "hr"])
    md.validateLink = lambda url: True    # we decide below, and show refused ones as text
    return md


def parse(text: str, kind: str = "post") -> list[dict]:
    """The blocks of a Markdown text, for a post or a chat line (section 3)."""
    text = (text or "")[:MAX_TEXT]
    tokens = _parser(kind == KIND_CHAT).parse(text)
    blocks, _ = _blocks(tokens, 0, len(tokens), 0)
    return blocks


def plain(text: str) -> list[dict]:
    """Plain text as the same tree: paragraphs, nothing else (section 2)."""
    out = []
    for para in re.split(r"\n\s*\n", (text or "").strip("\n")):
        inl: list[dict] = []
        for i, line in enumerate(para.split("\n")):
            if i:
                inl.append({"t": "br"})
            inl.append({"t": "text", "v": line})
        out.append({"t": "p", "c": inl})
    return out


def body(text: str, content_type: str | None, kind: str = "post") -> list[dict]:
    """A message's text as a tree, by its Content-Type."""
    return parse(text, kind) if is_markdown(content_type) else plain(text)


MAX_TYPE = 128                        # a text type field (about_type, rules_type)


def manifest_text(text: str, text_type: str | None) -> list[dict]:
    """A profile's ``about`` or a group's ``rules`` as a tree (UN-RFC 0022 4.1, 0014 2.1).

    Markdown has the post subset without images: a manifest cannot reference
    blobs, so an image is shown as its alt text, as one that cannot be had.
    """
    if not is_markdown(text_type):
        return plain(text)
    return _without_images(parse(text))


def text_type_for(markdown: bool, text: str) -> str | None:
    """The type field to store with ``about`` or ``rules``: only Markdown is written,
    since plain text is the default (and an empty text needs no type)."""
    return MARKDOWN_TYPE if markdown and (text or "").strip() else None


def _without_images(nodes):
    out = []
    for n in nodes:
        if isinstance(n, list):                    # a list item's blocks
            out.append(_without_images(n))
        elif n.get("t") == "image":
            out.append({"t": "text", "v": f"[image: {n.get('alt') or 'no description'}]"})
        else:
            n = dict(n)
            for key in ("c", "items"):
                if isinstance(n.get(key), list):
                    n[key] = _without_images(n[key])
            out.append(n)
    return out


# --- tokens to tree ---------------------------------------------------------------

def _blocks(tokens, i: int, end: int, depth: int) -> tuple[list[dict], int]:
    out: list[dict] = []
    while i < end:
        tok = tokens[i]
        t = tok.type
        if t == "paragraph_open":
            out.append({"t": "p", "c": _inline(tokens[i + 1].children or [])})
            i += 3
        elif t == "heading_open":
            n = min(int(tok.tag[1]), MAX_HEADING)
            out.append({"t": "h", "n": n, "c": _inline(tokens[i + 1].children or [])})
            i += 3
        elif t in ("fence", "code_block"):
            lang = (tok.info or "").strip().split(" ")[0][:32] if t == "fence" else ""
            out.append({"t": "code", "lang": lang, "v": tok.content.rstrip("\n")})
            i += 1
        elif t == "hr":
            out.append({"t": "hr"})
            i += 1
        elif t == "blockquote_open":
            close = _close(tokens, i)
            inner, _ = _blocks(tokens, i + 1, close, depth)
            out.append({"t": "quote", "c": inner})
            i = close + 1
        elif t in ("bullet_list_open", "ordered_list_open"):
            close = _close(tokens, i)
            items, j = [], i + 1
            while j < close:
                if tokens[j].type == "list_item_open":
                    item_close = _close(tokens, j)
                    inner, _ = _blocks(tokens, j + 1, item_close, depth + 1)
                    items.append(inner)
                    j = item_close + 1
                else:
                    j += 1
            if depth >= MAX_LIST_DEPTH:      # too deep: flatten into paragraphs
                for inner in items:
                    out.extend(inner)
            else:
                start = int(tok.attrGet("start") or 1) if t == "ordered_list_open" else 1
                out.append({"t": "ol" if t == "ordered_list_open" else "ul", "start": start,
                            "items": items})
            i = close + 1
        elif t == "inline":                  # a tight list item's text
            out.append({"t": "p", "c": _inline(tok.children or [])})
            i += 1
        else:
            i += 1
    return out, i


def _close(tokens, i: int) -> int:
    """The index of the token closing tokens[i] (same level)."""
    level, j = 0, i
    while j < len(tokens):
        level += tokens[j].nesting
        if level == 0:
            return j
        j += 1
    return len(tokens) - 1


_INLINE_OPEN = {"em_open": "em", "strong_open": "strong", "s_open": "del"}


def _inline(children) -> list[dict]:
    out: list[dict] = []
    stack: list[list[dict]] = [out]
    marks: list[dict] = []
    for tok in children:
        t, cur = tok.type, stack[-1]
        if t == "text":
            cur.extend(_with_emoji(tok.content))
        elif t in ("softbreak", "hardbreak"):
            cur.append({"t": "br"})
        elif t == "code_inline":
            cur.append({"t": "code", "v": tok.content})
        elif t in _INLINE_OPEN:
            node = {"t": _INLINE_OPEN[t], "c": []}
            cur.append(node); stack.append(node["c"]); marks.append(node)
        elif t in ("em_close", "strong_close", "s_close", "link_close"):
            if len(stack) > 1:
                stack.pop(); marks.pop()
        elif t == "link_open":
            href = tok.attrGet("href") or ""
            if _scheme(href) in LINK_SCHEMES:
                node = {"t": "link", "href": href, "c": []}
                cur.append(node); stack.append(node["c"]); marks.append(node)
            else:                                  # shown as text (section 3.4)
                node = {"t": "span", "c": [], "refused": href}
                cur.append(node); stack.append(node["c"]); marks.append(node)
        elif t == "image":
            src = tok.attrGet("src") or ""
            alt = "".join(c.content for c in (tok.children or []) if c.type in ("text", "code_inline"))
            m = _BLOB.match(src)
            cur.append({"t": "image", "blob": m.group(1), "alt": alt} if m
                       else {"t": "text", "v": f"[image: {alt or 'no description'}]"})
        else:
            if tok.content:
                cur.append({"t": "text", "v": tok.content})
    return _unwrap(out)


def _unwrap(nodes: list[dict]) -> list[dict]:
    """Refused links become their text followed by the address, as text."""
    out: list[dict] = []
    for n in nodes:
        if n.get("t") == "span":
            out.extend(_unwrap(n["c"]))
            if n.get("refused"):
                out.append({"t": "text", "v": f" ({n['refused']})"})
        else:
            if "c" in n:
                n["c"] = _unwrap(n["c"])
            out.append(n)
    return out


def _scheme(href: str) -> str:
    m = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):", href.strip())
    return m.group(1).lower() if m else ""


def _with_emoji(text: str) -> list[dict]:
    """Text, with known :shortcodes: as emoji nodes (section 5.2)."""
    out: list[dict] = []
    pos = 0
    for m in _SHORTCODE.finditer(text):
        glyph = emoji(m.group(1))
        if glyph is None:
            continue
        if m.start() > pos:
            out.append({"t": "text", "v": text[pos:m.start()]})
        out.append({"t": "emoji", "v": glyph, "name": m.group(1)})
        pos = m.end()
    if pos < len(text):
        out.append({"t": "text", "v": text[pos:]})
    return out


def to_text(nodes: list[dict]) -> str:
    """The plain text of inline nodes (for subjects, previews and alt text)."""
    parts = []
    for n in nodes:
        t = n.get("t")
        if t in ("text", "code", "emoji"):
            parts.append(n["v"])
        elif t == "br":
            parts.append(" ")
        elif t == "image":
            parts.append(f"[image: {n['alt']}]")
        elif "c" in n:
            parts.append(to_text(n["c"]))
    return "".join(parts)
