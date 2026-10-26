"""A folder of Markdown (and HTML) as the pages of a site (UN-RFC 0035), #538.

    plan(folder, policy) -> SitePlan        # no network: what would be published

Each ``.md`` file is a page; ``.html`` / ``.htm`` pages are turned into the same
Markdown (the content comes along, the design does not). The relative path, made
lowercase and safe, is the page's path (``Guide/First Steps.md`` -> ``guide/first-steps``);
``index.md`` is the front page. The title comes from front matter ``title``, else the
first ``#`` heading, else the file name.

On the way, everything UN-RFC 0031 does not allow is turned into what it does or
left out, and each change goes into the report with its file and line: raw HTML,
links to pages that are not there, pictures too large or of a type the site does not
take. Pictures are read, typed from their content and cleaned of metadata
(``media.prepare``); a page carries at most 4 (UN-RFC 0027). Limits - pages, page
size, files - are checked before anything is sent.

Ignored: dotfiles, ``_``-prefixed files and folders, and what an optional
``.siteignore`` names (one pattern per line, ``#`` comments, ``*`` and ``?``, a
trailing ``/`` for folders).

Used by ``Session.publish_site`` (client/session/kept.py) and the CLI's
``site publish``. Not here: sending (the session), showing the report (the clients).
"""

from __future__ import annotations

import fnmatch
import html
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from ..core import blobs as bl
from ..core import pages as pg

PICTURE_LIMIT = 1024 * 1024           # a picture is made smaller than this when it can be
PAGE_FILES = bl.MAX_PER_ARTICLE


@dataclass
class Note:
    file: str
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.text}" if self.line else f"{self.file}: {self.text}"


@dataclass
class PlannedPage:
    path: str                      # the page's path in the site
    title: str
    text: str                      # Markdown, as UN-RFC 0031 allows
    source: str                    # the file it came from, relative to the folder
    files: list = field(default_factory=list)    # media.Prepared, in blob1.. order


@dataclass
class SitePlan:
    pages: list[PlannedPage] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)   # what stops publishing

    @property
    def ok(self) -> bool:
        return not self.problems

    def page(self, path: str) -> PlannedPage | None:
        return next((p for p in self.pages if p.path == path), None)


# --- paths ------------------------------------------------------------------------
# letters that do not come apart into a base letter and a mark
_LETTERS = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "đ": "d", "ð": "d",
                          "þ": "th", "ł": "l", "ı": "i"})

def slug(part: str) -> str:
    """One path segment as UN-RFC 0035 section 4.1 allows: a-z 0-9 - _ ."""
    s = part.lower().translate(_LETTERS)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9_.-]+", "-", s).strip("-.")
    return (s or "page")[:64]


def page_path(rel: str) -> str:
    """``Guide/First Steps.md`` -> ``guide/first-steps``."""
    p = PurePosixPath(rel)
    parts = [slug(x) for x in p.parent.parts] + [slug(p.stem)]
    return "/".join(parts)


def _ignored(rel: str, patterns: list[str], is_dir: bool) -> bool:
    parts = PurePosixPath(rel).parts
    if any(x.startswith((".", "_")) for x in parts):
        return True
    for pat in patterns:
        dir_only = pat.endswith("/")
        pat = pat.rstrip("/")
        if dir_only and not is_dir:
            if any(fnmatch.fnmatch(x, pat) for x in parts[:-1]):
                return True
            continue
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(parts[-1], pat):
            return True
    return False


def _patterns(folder: Path) -> list[str]:
    f = folder / ".siteignore"
    if not f.is_file():
        return []
    return [ln.strip() for ln in f.read_text(errors="replace").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


# --- front matter and titles ------------------------------------------------------
_FRONT = re.compile(r"\A(---|\+\+\+)\s*\n(.*?)\n\1\s*\n", re.S)
_TITLE_LINE = re.compile(r"""^\s*title\s*[:=]\s*["']?(.*?)["']?\s*$""", re.M)


def _front_matter(text: str) -> tuple[str, str, int]:
    """(title, the text without front matter, lines removed)."""
    m = _FRONT.match(text)
    if not m:
        return "", text, 0
    t = _TITLE_LINE.search(m.group(2))
    return (t.group(1).strip() if t else ""), text[m.end():], m.group(0).count("\n")


def _first_heading(text: str) -> str:
    m = re.search(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M)
    return m.group(1).strip() if m else ""


# --- HTML in Markdown, and HTML pages -------------------------------------------------
_INLINE = {"b": "**", "strong": "**", "i": "*", "em": "*", "code": "`", "s": "~~", "del": "~~"}
_DROP = {"script", "style", "noscript", "iframe", "form", "nav", "header", "footer",
         "aside", "button", "select", "textarea", "svg", "template", "object", "embed"}


class _ToMarkdown(HTMLParser):
    """The content of HTML as UN-RFC 0031 Markdown: headings, paragraphs, emphasis,
    lists, tables, links, pictures, quotes, code. The rest is left out and noted."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.dropped: set[str] = set()
        self.skip = 0
        self.lists: list[str] = []
        self.href: list[str | None] = []
        self.pre = 0
        self.title = ""
        self.in_title = False
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.table: list[list[str]] = []
        self.head_rows = 0

    def _w(self, s: str) -> None:
        if self.cell is not None:
            self.cell.append(s)
        else:
            self.out.append(s)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in _DROP:
            self.skip += 1
            self.dropped.add(tag)
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._w("\n\n" + "#" * min(int(tag[1]), 3) + " ")
        elif tag in ("p", "div", "section", "article", "main"):
            self._w("\n\n")
        elif tag == "br":
            self._w("  \n")
        elif tag in _INLINE:
            self._w(_INLINE[tag])
        elif tag == "a":
            self.href.append(a.get("href"))
            self._w("[")
        elif tag == "img":
            self._w(f"![{a.get('alt', '')}]({a.get('src', '')})")
        elif tag in ("ul", "ol"):
            self.lists.append(tag)
            self._w("\n")
        elif tag == "li":
            self._w("\n" + "  " * (len(self.lists) - 1) + ("1. " if self.lists and self.lists[-1] == "ol" else "- "))
        elif tag == "blockquote":
            self._w("\n\n> ")
        elif tag == "pre":
            self.pre += 1
            self._w("\n\n```\n")
        elif tag == "hr":
            self._w("\n\n---\n\n")
        elif tag == "table":
            self.table, self.head_rows = [], 0
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
            if tag == "th" and self.row is not None and not self.table:
                self.head_rows = 1
        elif tag not in ("html", "head", "body", "span", "thead", "tbody", "tfoot", "meta",
                         "link", "small", "sup", "sub", "u", "mark", "abbr", "time", "figure",
                         "figcaption", "picture", "source", "dl", "dt", "dd", "caption"):
            self.dropped.add(tag)

    def handle_endtag(self, tag):
        if tag in _DROP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = False
        elif tag in _INLINE:
            self._w(_INLINE[tag])
        elif tag == "a":
            href = self.href.pop() if self.href else None
            self._w(f"]({href})" if href else "]")
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self._w("\n")
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self._w("\n```\n\n")
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()).replace("|", "\\|"))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table:
            cols = max(len(r) for r in self.table)
            rows = [r + [""] * (cols - len(r)) for r in self.table]
            lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * cols]
            lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            self.out.append("\n\n" + "\n".join(lines) + "\n\n")
            self.table = []

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title += data
            return
        self._w(data if self.pre else re.sub(r"\s+", " ", data))

    def markdown(self) -> str:
        text = "".join(self.out)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def html_to_markdown(source: str) -> tuple[str, str, set[str]]:
    """(Markdown, the page's <title>, the tags left out)."""
    p = _ToMarkdown()
    p.feed(source)
    p.close()
    return p.markdown(), " ".join(p.title.split()), p.dropped


_RAW = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")


def _raw_html(text: str, rel: str, offset: int, notes: list[Note]) -> str:
    """Raw HTML inside Markdown (UN-RFC 0031 has none): simple tags become Markdown,
    the rest goes; outside code."""
    out, fence = [], False
    for n, line in enumerate(text.split("\n"), 1 + offset):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        if fence or not _RAW.search(line):
            out.append(line)
            continue
        parts = re.split(r"(`[^`]*`)", line)               # leave inline code alone
        for i, part in enumerate(parts):
            if i % 2 == 0 and _RAW.search(part):
                md, _, dropped = html_to_markdown(part)
                parts[i] = md.strip("\n")
                what = ", ".join(sorted(dropped)) or "markup"
                notes.append(Note(rel, n, f"HTML turned into Markdown ({what} left out)"
                                  if dropped else "HTML turned into Markdown"))
        out.append("".join(parts))
    return "\n".join(out)


# --- links and pictures ---------------------------------------------------------------
_LINK = re.compile(r"(!?)\[((?:[^\[\]]|\[[^\]]*\])*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _rewrite(text: str, rel: str, offset: int, here: str, by_source: dict[str, str],
             folder: Path, policy: dict, files: list, seen_pictures: dict,
             notes: list[Note]) -> str:
    """Links to pages of the folder become site paths relative to ``here``'s folder;
    pictures in the folder become files of the page (``blob<n>:``)."""
    from . import media
    src_dir = PurePosixPath(rel).parent
    line_of = _line_index(text, offset)

    def repl(m):
        image, label, dest = m.group(1), m.group(2), m.group(3)
        line = line_of(m.start())
        if _SCHEME.match(dest) or dest.startswith("#"):
            if image:
                notes.append(Note(rel, line, f"picture {dest} is not in the folder: shown as its text"))
                return label
            return m.group(0)
        target, _, frag = dest.partition("#")
        target = unquote(target.split("?", 1)[0])           # First%20Steps.md
        resolved = _normal(src_dir / target)
        if image:
            return _picture(resolved, label, rel, line, folder, policy, files, seen_pictures,
                            notes, media)
        if resolved is None:
            notes.append(Note(rel, line, f"link {dest} leaves the folder: kept as text"))
            return label
        page = _page_for(resolved, by_source)
        if page is None:
            notes.append(Note(rel, line, f"link {dest}: no such page in the folder"))
            return label
        link = _relative(here, page)
        return f"[{label}]({link}{'#' + frag if frag else ''})"
    return _LINK.sub(repl, text)


def _line_index(text: str, offset: int):
    starts = [0] + [i + 1 for i, c in enumerate(text) if c == "\n"]

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts)
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid
        return lo + 1 + offset
    return line_of


def _normal(p: PurePosixPath) -> str | None:
    parts: list[str] = []
    for x in p.parts:
        if x in ("", "."):
            continue
        if x == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(x)
    return "/".join(parts)


def _page_for(resolved: str, by_source: dict[str, str]) -> str | None:
    if resolved in by_source:
        return by_source[resolved]
    for ext in (".md", ".html", ".htm"):
        if resolved + ext in by_source:
            return by_source[resolved + ext]
    for name in ("index.md", "index.html", "index.htm"):
        key = (resolved.rstrip("/") + "/" + name).lstrip("/")
        if key in by_source:
            return by_source[key]
    return None


def _relative(here: str, target: str) -> str:
    """``target`` as a link from the page ``here`` (UN-RFC 0035 section 8): from the
    site's root, which every client reads the same - ``/guide/start``."""
    return "/" + target


def _picture(resolved, label, rel, line, folder, policy, files, seen, notes, media):
    if resolved is None or not (folder / resolved).is_file():
        notes.append(Note(rel, line, f"picture {resolved or '?'} is not in the folder: shown as its text"))
        return label
    if resolved in seen:
        return f"![{label}]({seen[resolved]})"
    if len(files) >= PAGE_FILES:
        notes.append(Note(rel, line, f"picture {resolved} left out: a page carries at most {PAGE_FILES}"))
        return label
    att = policy.get("attachments") if isinstance(policy.get("attachments"), dict) else None
    if att is None:
        notes.append(Note(rel, line, f"picture {resolved} left out: the site takes no files"))
        return label
    try:
        prep = media.prepare(PurePosixPath(resolved).name, (folder / resolved).read_bytes())
    except (OSError, ValueError) as exc:
        notes.append(Note(rel, line, f"picture {resolved} left out: {exc}"))
        return label
    if not bl.type_allowed(prep.media_type, att.get("types")):
        notes.append(Note(rel, line, f"picture {resolved} left out: the site does not take {prep.media_type}"))
        return label
    limit = min(int(att.get("max_size", 0)), PICTURE_LIMIT) or PICTURE_LIMIT
    if len(prep.octets) > limit:
        smaller = _smaller(prep, limit, media)
        if smaller is None:
            notes.append(Note(rel, line, f"picture {resolved} left out: larger than "
                                         f"{limit // 1024} KiB even made smaller"))
            return label
        notes.append(Note(rel, line, f"picture {resolved} made smaller "
                                     f"({len(prep.octets) // 1024} -> {len(smaller.octets) // 1024} KiB)"))
        prep = smaller
    files.append(prep)
    ref = f"{bl.blob_id(prep.octets)}"
    seen[resolved] = ref
    if prep.note:
        notes.append(Note(rel, line, f"picture {resolved}: {prep.note}"))
    return f"![{label}]({ref})"


def _smaller(prep, limit, media):
    """The picture scaled down as WebP until it fits ``limit``, or None."""
    import io
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(prep.octets))
        im.load()
    except Exception:
        return None
    width = im.width
    for _ in range(8):
        width = int(width * 0.8)
        if width < 64:
            return None
        small = im.copy()
        small.thumbnail((width, width * 4))
        buf = io.BytesIO()
        small.save(buf, "WEBP", quality=80)
        if buf.tell() <= limit:
            name = PurePosixPath(prep.name).stem + ".webp"
            return media.prepare(name, buf.getvalue())
    return None


# --- the plan -------------------------------------------------------------------------
def sources(folder: Path) -> list[str]:
    """The page files of a folder, relative and sorted, without the ignored ones."""
    patterns = _patterns(folder)
    out = []
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if p.is_dir() or _ignored(rel, patterns, False):
            continue
        if p.suffix.lower() in (".md", ".html", ".htm"):
            out.append(rel)
    return out


def plan(folder, policy: dict | None = None) -> SitePlan:
    """What publishing ``folder`` to a site with this manifest ``policy`` would do (its
    ``max_pages``, ``home`` and ``attachments``) - no network."""
    folder = Path(folder)
    policy = dict(policy or {})
    out = SitePlan()
    if not folder.is_dir():
        out.problems.append(f"{folder} is not a folder")
        return out
    found = sources(folder)
    home = policy.get("home", pg.HOME_DEFAULT)
    by_source: dict[str, str] = {}
    taken: dict[str, str] = {}
    for rel in found:
        path = page_path(rel)
        if path.endswith("/index") and path != "index":
            pass                                       # a folder's own page: guide/index
        if path == "index":
            path = home
        if not pg.valid_path(path):
            out.notes.append(Note(rel, 0, f"left out: {path!r} is not a page path (at most 8 levels)"))
            continue
        if path in taken:
            out.notes.append(Note(rel, 0, f"left out: the same page path as {taken[path]} ({path})"))
            continue
        taken[path] = rel
        by_source[rel] = path
    for rel, path in by_source.items():
        raw = (folder / rel).read_text(encoding="utf-8", errors="replace")
        offset = 0
        if rel.lower().endswith((".html", ".htm")):
            text, title, dropped = html_to_markdown(raw)
            if dropped:
                out.notes.append(Note(rel, 0, "HTML page: the content came along, not the design "
                                              f"({', '.join(sorted(dropped))} left out)"))
        else:
            title, text, offset = _front_matter(raw)
            text = _raw_html(text, rel, offset, out.notes)
        title = (title or _first_heading(text) or PurePosixPath(rel).stem.replace("-", " ")
                 .replace("_", " ").strip().capitalize() or path)[:pg.MAX_TITLE]
        files: list = []
        text = _rewrite(text, rel, offset, path, by_source, folder, policy, files, {}, out.notes)
        if len(text.encode()) > pg.MAX_BODY:
            out.problems.append(f"{rel}: {len(text.encode()) // 1024} KiB, a page is at most "
                                f"{pg.MAX_BODY // 1024} KiB - split it")
        if sum(len(f.octets) for f in files) > bl.MAX_TOTAL:
            out.problems.append(f"{rel}: its pictures are more than {bl.MAX_TOTAL // (1024 * 1024)} MiB")
        out.pages.append(PlannedPage(path, title.strip(), text, rel, files))
    limit = policy.get("max_pages", pg.MAX_PAGES_DEFAULT)
    if len(out.pages) > limit:
        out.problems.append(f"{len(out.pages)} pages, the site takes at most {limit}")
    if not out.pages:
        out.problems.append("no Markdown or HTML pages in the folder")
    return out
