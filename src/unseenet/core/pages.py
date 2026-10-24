"""Pages and sites (UN-RFC 0035), the second kind of kept articles (UN-RFC 0017 2.1).

A site is a channel with ``view: pages``. A page article has a ``Page`` header with
its path; a new version names the versions it replaces in ``Supersedes``. Which
version of a path is current, which is the previous one, and which pages are in
force is worked out from the page articles held and the current manifest alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .article import Article, ArticleError
from .groups import parse_supersedes

MAX_PAGES_DEFAULT, MAX_PAGES_MAX = 32, 100      # section 3
HOME_DEFAULT = "index"
INDEX_DEFAULT = "no"          # may search engines index the site (section 9.3): no by default
INDEX_VALUES = ("yes", "no")
MAX_BODY = 65536                                # octets (section 4.2)
MAX_TITLE = 128
_SEGMENT = re.compile(r"^[a-z0-9_.-]{1,64}$")
TYPES = ("text/markdown", "text/plain")


def valid_path(path: str) -> bool:
    """Section 4.1: 1-8 segments of a-z 0-9 - _ . , none of them . or .."""
    parts = path.split("/")
    return (1 <= len(parts) <= 8
            and all(_SEGMENT.match(p) and p not in (".", "..") for p in parts))


def resolve_link(current: str, href: str) -> str | None:
    """A link in a page without a scheme (section 8): the path it leads to in the same
    site, relative to the directory of the ``current`` page as in a file system, or
    from the site's root with a leading ``/``. ``..`` never goes above the site; a
    ``#fragment`` is dropped (a client may open the top of the page). None when it is
    not a valid path."""
    href = href.split("#", 1)[0].split("?", 1)[0].strip()
    if not href:
        return None
    parts = [] if href.startswith("/") else current.split("/")[:-1]
    for seg in href.strip("/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    path = "/".join(parts)
    return path if valid_path(path) else None


def check_manifest_fields(data: dict) -> None:
    """``max_pages``, ``home`` and ``index`` (section 3); ValueError if invalid."""
    n = data.get("max_pages", MAX_PAGES_DEFAULT)
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_PAGES_MAX:
        raise ValueError(f"max_pages must be an integer from 1 to {MAX_PAGES_MAX}")
    home = data.get("home", HOME_DEFAULT)
    if not isinstance(home, str) or not valid_path(home):
        raise ValueError("home must be a page path")
    if data.get("index", INDEX_DEFAULT) not in INDEX_VALUES:
        raise ValueError("index must be yes or no")


@dataclass(frozen=True)
class Version:
    message_id: str
    path: str
    author_key: str
    date: int
    removed: bool
    supersedes: tuple[str, ...] = ()

    @property
    def newest_first(self) -> tuple[int, str]:
        """Latest Date first, on a tie the lower Message-ID (UN-RFC 0042 5.2)."""
        return (-self.date, self.message_id)


def parse_page(art: Article) -> tuple[str, bool, list[str]]:
    """A page article's (path, removal, Supersedes), checked as section 4.2 and
    4.3 step 3 say; ArticleError otherwise."""
    if art.control:
        raise ArticleError("syntax", "a page is not a control article")
    path = (art.get("Page") or "").strip()
    if not valid_path(path):
        raise ArticleError("syntax", "Page is a path of 1-8 segments of a-z 0-9 - _ .")
    if len(art.get("Subject") or "") > MAX_TITLE:
        raise ArticleError("syntax", f"a page's title is at most {MAX_TITLE} characters")
    if art.get("References"):
        raise ArticleError("syntax", "a page is not a reply")
    ctype = (art.get("Content-Type") or "text/plain").split(";")[0].strip().lower()
    if ctype not in TYPES:
        raise ArticleError("syntax", "a page is Markdown or plain text")
    if len(art.body.encode()) > MAX_BODY:
        raise ArticleError("size", f"a page is at most {MAX_BODY} octets")
    removed = (art.get("Page-Removed") or "").strip().lower() == "yes"
    if removed and (art.body.strip() or art.get("Blobs")):
        raise ArticleError("syntax", "a removal has no body and no Blobs")
    return path, removed, parse_supersedes(art)


def current_versions(versions, allowed) -> dict[str, tuple[Version, Version | None]]:
    """Section 5.1: for each path, (current version, previous version or None),
    among the versions that count - their author is in ``allowed`` (owner,
    moderators and posters now); withdrawn ones are left out by the caller."""
    by_path: dict[str, list[Version]] = {}
    for v in versions:
        if v.author_key in allowed:
            by_path.setdefault(v.path, []).append(v)
    out = {}
    for path, vs in by_path.items():
        named = {s for v in vs for s in v.supersedes}
        heads = [v for v in vs if v.message_id not in named] or vs
        cur = min(heads, key=lambda v: v.newest_first)
        earlier = [v for v in vs if v.message_id in cur.supersedes]
        prev = min(earlier, key=lambda v: v.newest_first) if earlier else None
        out[path] = (cur, prev)
    return out


def in_force(currents: dict, *, max_pages: int, home: str) -> list[str]:
    """Section 5.2: the paths of the pages in force, the home page first."""
    pages = [(p, cur) for p, (cur, _) in currents.items() if not cur.removed]
    pages.sort(key=lambda pc: pc[1].newest_first)
    paths = [p for p, _ in pages]
    chosen = ([home] if home in paths else []) + [p for p in paths if p != home]
    return chosen[:max_pages]
