"""Pictures where no process can be started (the client in a browser): decoded by
the platform's own way (``decode.elsewhere``) or not shown, never decoded in the
client itself, and never an error from the platform shown instead of a picture."""
import asyncio
import io

import pytest
from PIL import Image

from unseenet.client import decode


def png(w=4, h=3) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def browser(monkeypatch):
    monkeypatch.setattr(decode.sys, "platform", "emscripten")
    monkeypatch.setattr(decode, "elsewhere", None)

    def no_process(*a, **k):
        raise AssertionError("no process may be started here")
    monkeypatch.setattr(decode.asyncio, "create_subprocess_exec", no_process)
    monkeypatch.setattr(decode.subprocess, "run", no_process)


def test_without_a_way_a_picture_is_not_shown(browser):
    with pytest.raises(decode.DecodeError, match=decode.NO_PROCESS):
        asyncio.run(decode.picture_async(png()))
    with pytest.raises(decode.DecodeError, match=decode.NO_PROCESS):
        decode.picture(png())


def test_a_platform_without_processes_says_so(monkeypatch):
    async def not_here(*a, **k):
        raise NotImplementedError("subprocess_exec() is not available in browser environments")
    monkeypatch.setattr(decode, "elsewhere", None)
    monkeypatch.setattr(decode.asyncio, "create_subprocess_exec", not_here)
    with pytest.raises(decode.DecodeError) as err:
        asyncio.run(decode.picture_async(png()))
    assert str(err.value) == decode.NO_PROCESS


def test_the_platforms_way_is_used(browser, monkeypatch):
    seen = []

    async def way(octets, media_type):
        seen.append(media_type)
        return decode.Picture("image/png", b"clean", 4, 3)
    monkeypatch.setattr(decode, "elsewhere", way)
    got = asyncio.run(decode.picture_async(png(), "image/png"))
    assert got.octets == b"clean" and (got.width, got.height) == (4, 3)
    assert seen == ["image/png"]


def test_the_checks_come_first(browser, monkeypatch):
    async def way(octets, media_type):
        raise AssertionError("not asked for a file that is not what it says")
    monkeypatch.setattr(decode, "elsewhere", way)
    with pytest.raises(decode.DecodeError, match="says it is image/jpeg"):
        asyncio.run(decode.picture_async(png(), "image/jpeg"))
    with pytest.raises(decode.DecodeError, match="not a picture"):
        asyncio.run(decode.picture_async(b"<svg/>", None))


@pytest.mark.parametrize("answer, text", [
    (decode.Picture("image/png", b"x", 10_000, 10_000), "over 50 megapixels"),
    (decode.Picture("image/svg+xml", b"x", 4, 3), "could not be read"),
    (decode.Picture("image/png", b"x", 0, 3), "could not be read"),
    ("not a picture", "could not be read"),
])
def test_what_comes_back_is_held_to_the_rules(browser, monkeypatch, answer, text):
    async def way(octets, media_type):
        return answer
    monkeypatch.setattr(decode, "elsewhere", way)
    with pytest.raises(decode.DecodeError, match=text):
        asyncio.run(decode.picture_async(png()))


def test_a_failing_way_is_a_decode_error(browser, monkeypatch):
    async def way(octets, media_type):
        raise RuntimeError("JsException: EncodingError: The source image cannot be decoded.")
    monkeypatch.setattr(decode, "elsewhere", way)
    with pytest.raises(decode.DecodeError) as err:
        asyncio.run(decode.picture_async(png()))
    assert str(err.value) == "this picture could not be read"


def test_a_slow_way_is_given_up(browser, monkeypatch):
    async def way(octets, media_type):
        await asyncio.sleep(5)
    monkeypatch.setattr(decode, "elsewhere", way)
    monkeypatch.setattr(decode, "TIMEOUT", 0.05)
    with pytest.raises(decode.DecodeError, match="too long"):
        asyncio.run(decode.picture_async(png()))
