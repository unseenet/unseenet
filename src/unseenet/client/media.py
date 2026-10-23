"""Files for posts (UN-RFC 0027): what a file is, and taking out what it says about you.

A photo usually carries more than the picture: where it was taken (GPS), when, the
camera or phone and its serial number, sometimes the owner's name. In a network
built for not being seen, that must not leave with the picture. ``prepare`` saves a
picture again with nothing but its pixels (and turned the way it was shown), so
every client - the command line, the TUI, the GUI - sends the same clean file.

The type is found from the content, never from the file name, so a renamed file is
what it is. Pictures (JPEG, PNG, GIF, WebP) are cleaned; a PDF is sent as it is, with
a note that its own metadata (author, software) is not removed; other files too,
with a note. Cleaning needs Pillow, which comes with ``unseenet``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

IMAGE_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/gif": "GIF",
               "image/webp": "WEBP"}


@dataclass(frozen=True)
class Prepared:
    """A file ready to post: its name, media type, the octets to send, and ``note``,
    a sentence for the user when something was not cleaned (else empty)."""
    name: str
    media_type: str
    octets: bytes
    note: str = ""


def sniff(octets: bytes) -> str:
    """The media type of a file from its first octets; ``application/octet-stream``
    when it is none this client knows."""
    head = octets[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x00\x00\x00") and b"ftyp" in octets[:32]:
        return "video/mp4"
    try:
        octets[:4096].decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


def strip_image(octets: bytes, media_type: str) -> bytes:
    """The picture saved again with its pixels only: no EXIF (GPS, time, camera), no
    XMP or IPTC, no comments or text chunks, no colour profile. It is turned first
    the way its EXIF said to show it, so it looks the same. A JPEG keeps its own
    quality tables, so it loses as little as possible; an animated GIF or WebP keeps
    its frames. ``ValueError`` if it is not a picture Pillow can read."""
    from PIL import Image

    fmt = IMAGE_TYPES[media_type]
    try:
        img = Image.open(io.BytesIO(octets))
        img.load()
    except Exception as exc:  # noqa: BLE001 - Pillow raises many kinds
        raise ValueError(f"not a picture that can be read: {exc}") from exc
    out = io.BytesIO()
    loop, duration = img.info.get("loop", 0), img.info.get("duration", 100)
    transparency = img.info.get("transparency")
    lossless = bool(img.info.get("lossless"))
    frames = getattr(img, "n_frames", 1)
    if frames > 1 and fmt in ("GIF", "WEBP"):
        # one mode for every frame: mixed ones (a GIF's first in P, the rest in RGB)
        # would be merged wrongly when saved
        clean = [_bare(_turned(f)) for f in _frames(img)]
        kw = {"save_all": True, "append_images": clean[1:], "loop": loop, "duration": duration}
        if fmt == "GIF" and transparency is not None:
            kw["transparency"] = transparency
        clean[0].save(out, fmt, **kw)
        return out.getvalue()
    turned = _bare(_turned(img))
    img = _bare(img)
    if fmt == "JPEG":
        if turned is img:
            img.save(out, "JPEG", quality="keep", optimize=True)
        else:
            turned.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    elif fmt == "PNG":
        turned.save(out, "PNG", optimize=True)
    elif fmt == "GIF":
        kw = {"transparency": transparency} if transparency is not None else {}
        turned.save(out, "GIF", **kw)
    else:
        turned.save(out, "WEBP", lossless=lossless, quality=90)
    return out.getvalue()


def _turned(img):
    """The image turned the way its EXIF says to show it; as it is when that EXIF
    cannot be read (it is thrown away anyway)."""
    from PIL import ImageOps
    try:
        return ImageOps.exif_transpose(img)
    except Exception:  # noqa: BLE001 - damaged EXIF: Pillow raises many kinds
        return img


def _bare(img):
    """The image with no metadata left for a writer to copy from: Pillow takes
    a colour profile, EXIF or comments from ``info`` when it saves."""
    img.info = {}
    if hasattr(img, "applist"):
        img.applist = []               # a JPEG's APP segments (EXIF, XMP, IPTC)
    return img


def _frames(img):
    """Every frame as an image of its own, in RGBA. The iterator gives the same
    image back, moved on, so each frame is converted while it is the current one."""
    from PIL import ImageSequence
    return [f.convert("RGBA") for f in ImageSequence.Iterator(img)]


def prepare(name: str, octets: bytes) -> Prepared:
    """A file as it will be posted: its type from its content, a picture cleaned of
    metadata (``strip_image``), anything else as it is with a note. The name is the
    file's own name without any folders."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1] or "file"
    media_type = sniff(octets)
    if media_type in IMAGE_TYPES:
        return Prepared(name, media_type, strip_image(octets, media_type))
    if media_type == "application/pdf":
        return Prepared(name, media_type, octets,
                        "PDF files are sent as they are: their own metadata (author, "
                        "software, dates) is not removed.")
    return Prepared(name, media_type, octets,
                    f"{name} is sent as it is: only pictures are cleaned of metadata.")


def avatar(octets: bytes, *, max_octets: int = 8192, sizes=(128, 96, 64, 48, 32)) -> tuple[bytes, str, int]:
    """A profile picture (UN-RFC 0022 section 8.1) from any picture: the middle square,
    turned the way it was shown, at the largest of ``sizes`` (128 to 32 pixels) that
    fits in ``max_octets`` as WebP, else JPEG - with no metadata. Returns ``(octets,
    media type, px)``; ``ValueError`` if it is not a picture or cannot be made to fit."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(octets))
        img.load()
    except Exception as exc:  # noqa: BLE001 - Pillow raises many kinds
        raise ValueError(f"not a picture that can be read: {exc}") from exc
    img = _turned(img).convert("RGB")
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    square = img.crop((left, top, left + side, top + side))
    for px in sizes:
        small = _bare(square.resize((px, px), Image.LANCZOS))
        for fmt, ctype in (("WEBP", "image/webp"), ("JPEG", "image/jpeg")):
            for quality in (85, 70, 55, 40):
                out = io.BytesIO()
                small.save(out, fmt, quality=quality)
                if len(out.getvalue()) <= max_octets:
                    return out.getvalue(), ctype, px
    raise ValueError("the picture cannot be made small enough")
