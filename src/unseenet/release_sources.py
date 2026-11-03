"""Where releases are fetched from, set in the network (#902).

Release files (the portable zips, the images, the server packages' wheels and the
checksums) and the package index servers install from are on GitHub and PyPI. If either
takes the project down, is blocked, or is used against it, nothing could be updated -
not even to a version that knows somewhere else. So the project key signs a **list of
release sources** and posts it in ``unseenet.releases``::

    Unseenet release sources

    {"files": ["http://abc...xyz.onion/releases/{repo}/{tag}/{name}",
               "https://github.com/unseenet/{repo}/releases/download/{tag}/{name}"],
     "index": ["https://pypi.org/simple/"], "updated": "2026-11-02T20:00:00Z", "v": 1}

    Unseenet release signature
    key: ed25519:...
    signature: ...

- ``files``: where a release file is, as templates with ``{repo}`` (unseenet-portable,
  unseenet-gateway ...), ``{tag}`` (``v0.8.0``, ``dev``) and ``{name}``; tried in order.
- ``index``: package indexes for pip (PyPI's simple API, or a mirror of it); the first is
  the index, the others extra ones.
- ``updated``: the newest valid list wins; an older one never replaces it.
- ``moved_to`` (optional): the Group ID of a list council that keeps the sources from
  now on (UN-RFC 0020 section 6.8). From the first such list on, the publisher's later
  lists are not used.

The list is signed like a release: by as many of the publisher's keys as its key list's
threshold for ``stable`` (UN-RFC 0062 sections 3, 4 and 6.3), since whoever says where to
fetch decides who sees the fetching.

Each address is ``https://``, or ``http://`` to an onion address (Tor encrypts and
authenticates those). The list grants nothing over *what* is installed: every file must
still match the checksums the project key signed, so a false or stale list can only send
a server or client looking in the wrong place - and the built-in sources stay the last
resort. Clients keep the newest list they saw, servers too (in their updater's state),
so a list posted while the network works is still there when GitHub is not.

Belongs here: the list, its post, its checks. Not here: using it (``update.py`` for
clients, ``service_update.py`` for servers). Posted by ``tools/project/release_sources.py``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

HEAD = "Unseenet release sources"
DOMAIN = b"Unseenet release sources\n"     # what is signed: this, then the JSON
MAX_ENTRIES = 16
GITHUB = "https://github.com/unseenet/{repo}/releases/download/{tag}/{name}"
PYPI = "https://pypi.org/simple/"
GITHUB_FILE = re.compile(r"^https://github\.com/unseenet/(?P<repo>[A-Za-z0-9_.-]+)/releases/"
                         r"download/(?P<tag>[A-Za-z0-9_.+-]+)/(?P<name>[A-Za-z0-9_.+-]+)$")


class SourcesError(ValueError):
    pass


@dataclass(frozen=True)
class Sources:
    files: tuple[str, ...] = (GITHUB,)
    index: tuple[str, ...] = (PYPI,)
    updated: str = ""                     # "" - the built-in list, older than any posted
    moved_to: str | None = None           # a list council keeps the sources from now on

    def to_dict(self) -> dict:
        out = {"v": 1, "files": list(self.files), "index": list(self.index),
               "updated": self.updated}
        if self.moved_to:
            out["moved_to"] = self.moved_to
        return out

    def file_urls(self, repo: str, tag: str, name: str) -> list[str]:
        """Where ``name`` of release ``tag`` in ``repo`` is, in order; GitHub last if the
        list does not name it (the built-in source, never dropped)."""
        out = [t.format(repo=repo, tag=tag, name=name) for t in self.files]
        github = GITHUB.format(repo=repo, tag=tag, name=name)
        return list(dict.fromkeys(out + [github]))


BUILT_IN = Sources()


def _address(url: str, template: bool) -> str:
    test = url.replace("{repo}", "r").replace("{tag}", "t").replace("{name}", "n") if template else url
    u = urlsplit(test)
    onion = u.scheme == "http" and (u.hostname or "").endswith(".onion")
    if not (u.scheme == "https" or onion) or not u.hostname or u.username or u.password:
        raise SourcesError(f"not an https:// or onion address: {url}")
    if template and "{name}" not in url:
        raise SourcesError(f"a file address without {{name}}: {url}")
    if re.search(r"\{(?!repo\}|tag\}|name\})", url):
        raise SourcesError(f"only {{repo}}, {{tag}} and {{name}}: {url}")
    return url


def from_dict(data: dict) -> Sources:
    if not isinstance(data, dict) or data.get("v") != 1:
        raise SourcesError("not a list of release sources (v 1)")
    files, index = data.get("files"), data.get("index")
    if not (isinstance(files, list) and isinstance(index, list) and files and index
            and len(files) <= MAX_ENTRIES and len(index) <= MAX_ENTRIES
            and all(isinstance(x, str) for x in files + index)):
        raise SourcesError("files and index: lists of addresses")
    updated = data.get("updated")
    try:
        datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourcesError(f"updated: not a time: {updated!r}") from exc
    moved_to = data.get("moved_to")
    if moved_to is not None:
        from .core.groups import split_group_id
        try:
            split_group_id(str(moved_to))
        except Exception as exc:  # noqa: BLE001
            raise SourcesError(f"moved_to: not a Group ID: {moved_to!r}") from exc
        moved_to = str(moved_to)
    return Sources(tuple(_address(f, True) for f in files),
                   tuple(_address(i, False).rstrip("/") + "/" for i in index), str(updated),
                   moved_to)


def _canonical(sources: Sources) -> bytes:
    return json.dumps(sources.to_dict(), sort_keys=True, separators=(",", ":")).encode()


def make_post(sources: Sources, identity) -> tuple[str, str]:
    """(subject, body) of the post, signed by ``identity`` - one of the publisher's keys;
    ``add_signature`` adds the next ones until the threshold is reached."""
    from . import update
    from_dict(sources.to_dict())                      # only a valid list is signed
    data = _canonical(sources)
    sig = update.signature_text(DOMAIN + data, identity)
    return HEAD, f"{HEAD}\n\n{data.decode()}\n\n{sig}"


def _split(body: str) -> tuple[bytes, str] | None:
    text = body.replace("\r\n", "\n")
    if not text.startswith(HEAD + "\n"):
        return None
    parts = text[len(HEAD):].strip("\n").split("\n\n", 1)
    if len(parts) != 2:
        return None
    return parts[0].strip().encode(), parts[1]


def add_signature(body: str, identity) -> str:
    """The post with this key's signature added (once): signers sign one after another."""
    from . import update
    parts = _split(body)
    if parts is None:
        raise SourcesError("not a post of release sources")
    data, sig = parts
    return f"{HEAD}\n\n{data.decode()}\n\n{update.add_signature(sig, DOMAIN + data, identity)}"


def parse_post(body: str, keys=None) -> Sources | None:
    """The list in a post, if enough of the publisher's keys signed it (``keys``: its key
    list, UN-RFC 0062 section 3; by default the project's pinned one); None otherwise."""
    from . import update
    parts = _split(body)
    if parts is None:
        return None
    data, sig = parts
    try:
        update.check_signature(DOMAIN + data, sig, "stable", keys)
        sources = from_dict(json.loads(data))
    except (update.UpdateError, ValueError):
        return None
    return sources if _canonical(sources) == data else None


def _when(sources: Sources) -> datetime:
    if not sources.updated:
        return datetime.min.replace(tzinfo=timezone.utc)
    t = datetime.fromisoformat(sources.updated.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def newest(bodies: list[str], known: Sources | dict | None = None, keys=None) -> Sources:
    """The newest valid list among the posts and the one kept from before - except that
    the first list naming ``moved_to`` stays: after it, the publisher's lists are not
    used (UN-RFC 0062 section 6.3), and the council's are (``moved_to``)."""
    best = BUILT_IN
    if isinstance(known, dict):
        try:
            known = from_dict(known)
        except SourcesError:
            known = None
    candidates = [c for c in [known, *(parse_post(b, keys) for b in bodies)] if c is not None]
    moved = [c for c in candidates if c.moved_to]
    if moved:
        return min(moved, key=_when)
    for candidate in candidates:
        if _when(candidate) > _when(best):
            best = candidate
    return best


async def read_group(c, group: str, subject_prefixes: tuple[str, ...], scan: int = 400,
                     limit: int = 20) -> dict[str, list[str]]:
    """The newest bodies in ``group`` whose subject starts with each prefix (newest first),
    found with HDR Subject over the last ``scan`` articles."""
    from contextlib import suppress

    from .core.article import Article
    _, low, high = await c.group(group)
    out: dict[str, list[str]] = {p: [] for p in subject_prefixes}
    if high < low:
        return out
    wanted: dict[str, list[str]] = {p: [] for p in subject_prefixes}
    for line in await c.multiline(f"HDR Subject {max(low, high - scan + 1)}-{high}", 225):
        number, _, subject = line.partition(" ")
        for p in subject_prefixes:
            if subject.startswith(p):
                wanted[p].append(number)
    for p, numbers in wanted.items():
        for number in reversed(numbers[-limit:]):
            raw = await c.article(number)
            if raw:
                with suppress(ValueError):
                    out[p].append(Article.from_bytes(raw).body)
    return out
