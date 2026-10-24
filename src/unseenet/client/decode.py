"""Showing a picture from the network safely (UN-RFC 0027 section 9.2).

A file from the network is hostile input, and image decoders are among the most
attacked code there is. So a picture is never decoded in the client itself: it is
decoded in a separate process with as few rights as the platform allows - limits on
memory, CPU time and open files, no files written, no vault, nothing but the octets
on its standard input - which saves it again with its pixels only, in the same
format. What a front end shows is that clean copy, never what came from the network.

Before decoding, the type is found from the content and must be the one the post
declares, and a picture of more than 50 megapixels or 1000 frames is refused
("decompression bombs", small as files and huge in memory). SVG and PDF are not
decoded at all: a PDF is offered as a file to save, never opened.

``picture`` and ``picture_async`` are what clients call; ``python -m
unseenet.client.decode`` is the process itself (in a portable build, the program run
with ``--unseenet-decode-picture``, see ``run_if_asked``).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass

MAX_PIXELS = 50_000_000
MAX_FRAMES = 1000
MEMORY = 1536 * 1024 * 1024        # address space of the decoding process
CPU_SECONDS = 20
TIMEOUT = 30
SHOWN = {"image/png": "PNG", "image/jpeg": "JPEG", "image/gif": "GIF", "image/webp": "WEBP"}


class DecodeError(ValueError):
    """The file cannot be shown as a picture; the text is for people."""


@dataclass(frozen=True)
class Picture:
    """A picture saved again by the decoding process: safe to hand to a front end."""
    media_type: str
    octets: bytes
    width: int
    height: int
    frames: int = 1


def _check(octets: bytes, declared: str | None) -> str:
    from .media import sniff
    actual = sniff(octets)
    if actual not in SHOWN:
        raise DecodeError("this file is not a picture that can be shown here"
                          if actual != "application/pdf" else
                          "a PDF is not shown here - save it to read it")
    if declared and declared.split(";")[0].strip().lower() != actual:
        raise DecodeError(f"this file says it is {declared} but is {actual}: not shown")
    return actual


ARG = "--unseenet-decode-picture"


def _command() -> list[str]:
    if getattr(sys, "frozen", False):                # a portable build: the program is its own
        return [sys.executable, ARG]
    return [sys.executable, "-I", "-m", "unseenet.client.decode"]


def run_if_asked(argv: list[str] | None = None) -> None:
    """For a frozen build (the portable clients), whose program is not Python: its entry
    point calls this first, so the program can also be the decoding process."""
    if (sys.argv if argv is None else argv)[1:2] == [ARG]:
        main()
        sys.exit(0)


def _flags() -> dict:
    if sys.platform == "win32":                      # no console window from a windowed client
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _answer(code: int | None, out: bytes, err: bytes, media_type: str) -> Picture:
    if code != 0:
        text = err.decode("utf-8", "replace").strip().splitlines()
        raise DecodeError(text[-1] if text and code == 2 else "this picture could not be read")
    head, _, octets = out.partition(b"\n")
    try:
        info = json.loads(head)
        return Picture(media_type, octets, int(info["width"]), int(info["height"]),
                       int(info.get("frames", 1)))
    except (ValueError, KeyError, TypeError):
        raise DecodeError("this picture could not be read") from None


def picture(octets: bytes, declared: str | None = None) -> Picture:
    """``octets`` decoded and saved again in a separate, limited process. ``declared``
    is the type the post gives; it must match the content. ``DecodeError`` otherwise."""
    media_type = _check(octets, declared)
    try:
        done = subprocess.run(_command(), input=octets, capture_output=True, timeout=TIMEOUT,
                              env={}, **_flags())
    except subprocess.TimeoutExpired:
        raise DecodeError("this picture took too long to read") from None
    return _answer(done.returncode, done.stdout, done.stderr, media_type)


async def picture_async(octets: bytes, declared: str | None = None) -> Picture:
    """``picture`` without blocking the event loop."""
    media_type = _check(octets, declared)
    proc = await asyncio.create_subprocess_exec(
        *_command(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env={}, **_flags())
    try:
        out, err = await asyncio.wait_for(proc.communicate(octets), TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise DecodeError("this picture took too long to read") from None
    return _answer(proc.returncode, out, err, media_type)


# --- the decoding process --------------------------------------------------------

def _limit() -> None:
    """As few rights as this platform allows: memory, CPU time, open files, and no
    files written. Windows has no such limits; there the process still holds nothing
    but the octets it was given."""
    try:
        import resource
    except ImportError:
        return
    for name, value in (("RLIMIT_AS", MEMORY), ("RLIMIT_CPU", CPU_SECONDS),
                        ("RLIMIT_FSIZE", 0), ("RLIMIT_NOFILE", 64), ("RLIMIT_CORE", 0)):
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            pass


def _fail(text: str) -> None:
    sys.stderr.write(text + "\n")
    sys.exit(2)


def main() -> None:
    _limit()
    data = sys.stdin.buffer.read()
    import io

    from PIL import Image

    from .media import _bare, _frames, _turned, sniff
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    fmt = SHOWN.get(sniff(data))
    if fmt is None:
        _fail("this file is not a picture that can be shown here")
    try:
        img = Image.open(io.BytesIO(data), formats=[fmt])
    except Exception:  # noqa: BLE001 - Pillow raises many kinds
        _fail("this picture could not be read")
    if img.width * img.height > MAX_PIXELS:
        _fail("this picture is too large to show (over 50 megapixels)")
    frames = getattr(img, "n_frames", 1)
    if frames > MAX_FRAMES:
        _fail("this picture has too many frames to show (over 1000)")
    out = io.BytesIO()
    try:
        if frames > 1 and fmt in ("GIF", "WEBP"):
            clean = [_bare(f) for f in _frames(img)]
            clean[0].save(out, fmt, save_all=True, append_images=clean[1:],
                          loop=img.info.get("loop", 0), duration=img.info.get("duration", 100))
            size = clean[0].size
        else:
            img.load()
            shown = _bare(_turned(img))
            if fmt == "JPEG":
                shown.convert("RGB").save(out, "JPEG", quality=90)
            elif fmt == "WEBP":
                shown.save(out, "WEBP", quality=90)
            else:
                shown.save(out, fmt)
            size = shown.size
    except Exception:  # noqa: BLE001
        _fail("this picture could not be read")
    sys.stdout.buffer.write(json.dumps({"width": size[0], "height": size[1],
                                        "frames": frames}).encode() + b"\n" + out.getvalue())


if __name__ == "__main__":
    main()
