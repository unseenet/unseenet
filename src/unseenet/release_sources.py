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

    def to_dict(self) -> dict:
        return {"v": 1, "files": list(self.files), "index": list(self.index),
                "updated": self.updated}

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
    return Sources(tuple(_address(f, True) for f in files),
                   tuple(_address(i, False).rstrip("/") + "/" for i in index), str(updated))


def _canonical(sources: Sources) -> bytes:
    return json.dumps(sources.to_dict(), sort_keys=True, separators=(",", ":")).encode()


def make_post(sources: Sources, identity) -> tuple[str, str]:
    """(subject, body) of the post, signed by ``identity`` (the project key)."""
    from . import update
    from_dict(sources.to_dict())                      # only a valid list is signed
    data = _canonical(sources)
    sig = update.signature_text(DOMAIN + data, identity)
    return HEAD, f"{HEAD}\n\n{data.decode()}\n\n{sig}"


def parse_post(body: str) -> Sources | None:
    """The list in a post, if the project key signed it; None for anything else."""
    from . import update
    text = body.replace("\r\n", "\n")
    if not text.startswith(HEAD + "\n"):
        return None
    parts = text[len(HEAD):].strip("\n").split("\n\n", 1)
    if len(parts) != 2:
        return None
    data, sig = parts[0].strip().encode(), parts[1]
    try:
        update.check_signature(DOMAIN + data, sig, "stable")    # the project key only
        sources = from_dict(json.loads(data))
    except (update.UpdateError, ValueError):
        return None
    return sources if _canonical(sources) == data else None


def _when(sources: Sources) -> datetime:
    if not sources.updated:
        return datetime.min.replace(tzinfo=timezone.utc)
    t = datetime.fromisoformat(sources.updated.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def newest(bodies: list[str], known: Sources | dict | None = None) -> Sources:
    """The newest valid list among the posts and the one kept from before."""
    best = BUILT_IN
    if isinstance(known, dict):
        try:
            known = from_dict(known)
        except SourcesError:
            known = None
    for candidate in [known, *map(parse_post, bodies)]:
        if candidate is not None and _when(candidate) > _when(best):
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
