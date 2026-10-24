"""Attachments as blobs (UN-RFC 0027): IDs, the Blobs and Attachment-n headers,
the manifest field ``attachments``, the postage extra, and a store for the octets."""

from __future__ import annotations

import math
import os
import re
from pathlib import Path

from .article import Article, ArticleError
from .encoding import DS, H, b32, b64, b64decode

PREFIX = "blob1:"
MAX_BLOB = 4 * 1024 * 1024            # section 3.2
MIN_NODE_BLOB = 1024 * 1024           # a blob node accepts at least this
MAX_PER_ARTICLE = 4
MAX_TOTAL = 8 * 1024 * 1024
ENC_OVERHEAD = 40                     # nonce and tag of an encrypted blob (section 3.3)
STAGE_MIN_COUNT, STAGE_MIN_BYTES = 4, 8 * 1024 * 1024   # per connection, at least (6.2)
STAGE_SECONDS = 3600
FREE_TOTAL = 65536                    # no postage extra up to this (section 4.5)
MAX_NAME, MAX_ALT = 128, 512          # octets before b64 (section 4.2)
DAILY_PER_KEY = 32 * 1024 * 1024      # section 8.1, RECOMMENDED
DAILY_PER_GROUP = 256 * 1024 * 1024
MAX_KEPT_PER_GROUP = 8 * 1024 * 1024  # blobs of kept articles in one group (UN-RFC 0017 2.2)
# The choices clients offer for a group's files (#496), as manifest ``attachments``
# (section 5.1). ``None``: the group takes no files.
PICTURES = {"max_size": MAX_BLOB, "types": ["image/*"]}
PICTURES_AND_PDF = {"max_size": MAX_BLOB, "types": ["image/*", "application/pdf"]}
FILE_CHOICES = {"none": None, "pictures": PICTURES, "pictures+pdf": PICTURES_AND_PDF}


def file_choice(attachments) -> str:
    """Which of ``FILE_CHOICES`` a manifest's ``attachments`` is, or ``custom`` for
    other limits (kept as they are when a client edits the group)."""
    if not isinstance(attachments, dict):
        return "none"
    for name, att in FILE_CHOICES.items():
        if att is not None and attachments.get("max_size") == att["max_size"] \
                and sorted(attachments.get("types") or []) == sorted(att["types"]):
            return name
    return "custom"


_ID_RE = re.compile(r"^blob1:[a-z2-7]{52}$")
_ATTACHMENT_RE = re.compile(r"^Attachment-([1-9][0-9]*)$", re.IGNORECASE)


def blob_id(octets: bytes) -> str:
    """section 3.1: blob1: b32( H( DS("UNSEENET-BLOB-1") || octets ) )"""
    return PREFIX + b32(H(DS("UNSEENET-BLOB-1") + octets))


def valid_id(text: str) -> bool:
    return bool(_ID_RE.match(text))


def parse_blobs(art: Article) -> list[tuple[str, int]]:
    """The ``Blobs`` header as [(blob ID, octets)], [] without one (sections 3.2, 4.1)."""
    value = art.get("Blobs")
    if value is None:
        return []
    out: list[tuple[str, int]] = []
    for item in value.split():
        bid, eq, size = item.partition("=")
        if not eq or not valid_id(bid) or not size.isdigit():
            raise ArticleError("syntax", "Blobs lists <blob-id>=<octets>")
        n = int(size)
        if not 0 < n <= MAX_BLOB:
            raise ArticleError("syntax", f"a blob is 1 to {MAX_BLOB} octets")
        out.append((bid, n))
    if not 1 <= len(out) <= MAX_PER_ARTICLE or len({b for b, _ in out}) != len(out):
        raise ArticleError("syntax", f"Blobs lists 1 to {MAX_PER_ARTICLE} different blobs")
    if sum(n for _, n in out) > MAX_TOTAL:
        raise ArticleError("syntax", f"an article's blobs are at most {MAX_TOTAL} octets")
    return out


def parse_attachments(headers) -> list[dict]:
    """``Attachment-<n>`` headers (section 4.2), numbered 1.. without gaps, as dicts
    with ``blob``, ``type``, ``size`` and the other parameters; [] without any.
    ``headers``: (name, value) pairs, outer or inner."""
    found: dict[int, str] = {}
    for name, value in headers:
        m = _ATTACHMENT_RE.match(name)
        if m:
            n = int(m.group(1))
            if n in found:
                raise ArticleError("syntax", f"Attachment-{n} twice")
            found[n] = value
    if not found:
        return []
    if sorted(found) != list(range(1, len(found) + 1)) or len(found) > MAX_PER_ARTICLE:
        raise ArticleError("syntax", "Attachment-<n> are numbered from 1 without gaps")
    out = []
    for n in range(1, len(found) + 1):
        parts = [p.strip() for p in found[n].split(";")]
        item: dict = {"blob": parts[0]}
        for p in parts[1:]:
            key, eq, val = p.partition("=")
            if eq:
                item.setdefault(key.strip().lower(), val.strip())
        if not valid_id(item["blob"]) or "type" not in item or not item.get("size", "").isdigit():
            raise ArticleError("syntax", f"Attachment-{n} needs a blob ID, type and size")
        item["size"] = int(item["size"])
        for field, limit in (("name", MAX_NAME), ("alt", MAX_ALT)):
            if field in item:
                try:
                    if len(b64decode(item[field])) > limit:
                        raise ValueError
                except ValueError:
                    raise ArticleError("syntax", f"Attachment-{n} {field} is b64 of at most "
                                       f"{limit} octets") from None
        out.append(item)
    return out


def check_attachments_field(data: dict) -> None:
    """The manifest field ``attachments`` (section 5.1); ValueError if invalid."""
    if "attachments" not in data:
        return
    att = data["attachments"]
    if not isinstance(att, dict):
        raise ValueError("attachments is an object")
    size = att.get("max_size")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_BLOB:
        raise ValueError(f"attachments.max_size is 1 to {MAX_BLOB} octets")
    types = att.get("types")
    if types is not None and (not isinstance(types, list)
                              or not all(isinstance(t, str) and t for t in types)):
        raise ValueError("attachments.types is a list of media types")


def type_allowed(media_type: str, types) -> bool:
    if types is None:
        return True
    media_type = media_type.lower()
    for t in types:
        t = t.lower()
        if t == media_type or (t.endswith("/*") and media_type.startswith(t[:-1])):
            return True
    return False


def encrypted(art: Article) -> bool:
    """A closed group's or an inbox's article: the files are encrypted (section 3.3)."""
    return "Encrypted" in art


def check_article(art: Article, manifest_data: dict | None) -> list[tuple[str, int]]:
    """Section 5.2 with 4.3 and 4.4, what every node checks whether or not it carries
    blobs. Returns the article's blobs."""
    blobs = parse_blobs(art)
    outer = parse_attachments(art.headers)
    if art.control and (blobs or outer):
        raise ArticleError("syntax", "control articles carry no blobs")
    if outer and not blobs:
        raise ArticleError("syntax", "Attachment-<n> without Blobs")
    if not blobs:
        return []
    att = (manifest_data or {}).get("attachments")
    if not isinstance(att, dict):
        raise ArticleError("permission", "this group allows no attachments")
    enc = encrypted(art)
    limit = att["max_size"] + (ENC_OVERHEAD if enc else 0)
    if any(n > limit for _, n in blobs):
        raise ArticleError("permission", f"a blob is larger than this group allows ({limit})")
    if enc:
        if outer:
            raise ArticleError("syntax", "an encrypted article's Attachment-<n> are inside")
        return blobs
    if any("key" in a for a in outer):
        raise ArticleError("syntax", "key only in encrypted articles")
    sizes = dict(blobs)
    if {a["blob"] for a in outer} != set(sizes) or any(a["size"] != sizes[a["blob"]] for a in outer):
        raise ArticleError("permission", "Attachment-<n> do not match Blobs")
    if any(not type_allowed(a["type"], att.get("types")) for a in outer):
        raise ArticleError("permission", "a file type this group does not allow")
    return blobs


def _files(files) -> list[tuple]:
    files = [tuple(f) + (None,) * (5 - len(f)) for f in files]
    if len(files) > MAX_PER_ARTICLE:
        raise ValueError(f"at most {MAX_PER_ARTICLE} files on a post")
    if sum(len(f[2]) for f in files) > MAX_TOTAL:
        raise ValueError(f"at most {MAX_TOTAL // (1024 * 1024)} MiB of files on a post")
    return files


def _attachment_value(bid: str, name, media_type: str, data: bytes, alt, dim,
                      key: bytes | None = None) -> str:
    value = (f"{bid}; type={media_type}; size={len(data)}; "
             f"name={b64((name or 'file').encode()[:MAX_NAME])}")
    if alt and alt.strip():
        value += f"; alt={b64(_cut(alt.strip(), MAX_ALT))}"
    if dim:
        value += f"; dim={int(dim[0])}x{int(dim[1])}"
    if key is not None:
        value += f"; key={b64(key)}"
    return value


def attachment_headers(files) -> list[tuple[str, str]]:
    """The ``Blobs`` and ``Attachment-<n>`` headers (sections 4.1-4.3) for a plain
    article's files, given as ``(name, media type, octets)``, optionally followed by
    the alternative text and the picture's ``(width, height)``; the name is sent as
    base64 of its first 128 octets, the text as base64 of its first 512."""
    files = _files(files)
    if not files:
        return []
    headers = [("Blobs", " ".join(f"{blob_id(f[2])}={len(f[2])}" for f in files))]
    for i, (name, media_type, data, alt, dim) in enumerate(files, 1):
        headers.append((f"Attachment-{i}",
                        _attachment_value(blob_id(data), name, media_type, data, alt, dim)))
    return headers


# --- encrypted blobs (section 3.3), for closed groups and inboxes ------------

ENC_AD = DS("UNSEENET-BLOB-ENC-1")


def encrypt_file(octets: bytes) -> tuple[bytes, bytes]:
    """``(key, blob)``: the file encrypted with a fresh random key for this file only
    (section 3.3) - never a key derived from the file."""
    from . import crypto
    key = os.urandom(32)
    return key, crypto.aead_encrypt(key, octets, ENC_AD)


def decrypt_file(key: bytes, blob: bytes) -> bytes:
    """The file in an encrypted blob; ``ValueError`` when the key does not open it."""
    from . import crypto
    try:
        return crypto.aead_decrypt(key, blob, ENC_AD)
    except crypto.CryptoError as exc:
        raise ValueError("the file does not open with its key") from exc


def encrypted_attachment_headers(files):
    """For an encrypted article's files (sections 3.3, 4.3): ``(outer, inner, blobs)``
    - the outer ``Blobs`` header nodes read, the inner ``Attachment-<n>`` headers with
    each file's ``key``, and the ``(blob ID, ciphertext)`` to upload. Files as for
    ``attachment_headers``."""
    files = _files(files)
    if not files:
        return [], [], []
    inner, blobs = [], []
    for i, (name, media_type, data, alt, dim) in enumerate(files, 1):
        key, blob = encrypt_file(data)
        bid = blob_id(blob)
        blobs.append((bid, blob))
        inner.append((f"Attachment-{i}",
                      _attachment_value(bid, name, media_type, data, alt, dim, key)))
    outer = [("Blobs", " ".join(f"{bid}={len(blob)}" for bid, blob in blobs))]
    return outer, inner, blobs


def inner_attachments(art: Article, inner_headers, types=None) -> tuple[list[dict], dict]:
    """The attachments of an encrypted article as a member shows them, and their file
    keys by blob ID - checked as section 4.4 says after decryption: the inner headers
    name exactly the outer ``Blobs``, each 40 octets larger than its file, every one
    with a key, and of a type the group allows (5.2). ``([], {})`` otherwise."""
    try:
        blobs = dict(parse_blobs(art))
        found = parse_attachments(inner_headers)
    except ArticleError:
        return [], {}
    if not blobs or {a["blob"] for a in found} != set(blobs):
        return [], {}
    keys = {}
    for a in found:
        if blobs[a["blob"]] != a["size"] + ENC_OVERHEAD or not a.get("key") \
                or not type_allowed(a["type"], types):
            return [], {}
        try:
            key = b64decode(a["key"])
        except ValueError:
            return [], {}
        if len(key) != 32:
            return [], {}
        keys[a["blob"]] = key
    return shown_attachments(inner_headers), keys


def _cut(text: str, limit: int) -> bytes:
    """``text`` as UTF-8 of at most ``limit`` octets, not cut inside a character."""
    return text.encode()[:limit].decode("utf-8", "ignore").encode()


def shown_attachments(headers) -> list[dict]:
    """The ``Attachment-<n>`` headers as a client shows them: ``blob``, ``type``,
    ``size``, and ``name`` and ``alt`` as text (empty when not given), ``dim`` as
    ``[width, height]`` or None. [] when there are none or they are not valid."""
    try:
        found = parse_attachments(headers)
    except ArticleError:
        return []
    out = []
    for a in found:
        def text(field):
            try:
                return b64decode(a[field]).decode("utf-8", "replace") if a.get(field) else ""
            except ValueError:
                return ""
        dim = None
        w, x, h = (a.get("dim") or "").partition("x")
        if x and w.isdigit() and h.isdigit():
            dim = [int(w), int(h)]
        out.append({"blob": a["blob"], "type": a["type"].lower(), "size": a["size"],
                    "name": text("name"), "alt": text("alt"), "dim": dim})
    return out


def extra_bits_for(total: int) -> int:
    """Section 4.5 for ``total`` octets of blobs: one bit per doubling above 64 KiB."""
    return 0 if total <= FREE_TOTAL else math.ceil(math.log2(total / FREE_TOTAL))


def extra_bits(art: Article) -> int:
    """Section 4.5: one more bit of postage per doubling above 64 KiB."""
    try:
        total = sum(n for _, n in parse_blobs(art))
    except ArticleError:
        return 0
    return extra_bits_for(total)


class BlobStore:
    """Blobs as files next to the node's database, by ID; in memory without a path."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else None
        self._mem: dict[str, bytes] = {}
        if self.path is not None:
            self.path.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _file(self, bid: str) -> Path:
        name = bid[len(PREFIX):]
        return self.path / name[:2] / name

    def has(self, bid: str) -> bool:
        return bid in self._mem if self.path is None else self._file(bid).exists()

    def get(self, bid: str) -> bytes | None:
        if self.path is None:
            return self._mem.get(bid)
        try:
            return self._file(bid).read_bytes()
        except FileNotFoundError:
            return None

    def put(self, bid: str, octets: bytes) -> None:
        if blob_id(octets) != bid:
            raise ValueError("the octets do not match the blob ID")
        if self.path is None:
            self._mem[bid] = octets
            return
        f = self._file(bid)
        f.parent.mkdir(exist_ok=True, mode=0o700)
        tmp = f.with_suffix(".tmp")
        tmp.write_bytes(octets)
        os.replace(tmp, f)

    def delete(self, bid: str) -> None:
        if self.path is None:
            self._mem.pop(bid, None)
        else:
            self._file(bid).unlink(missing_ok=True)
