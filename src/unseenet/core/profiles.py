"""Profiles, pictures and identicons for identities (UN-RFC 0022)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import crypto
from .article import Article
from .encoding import DS, H, b64, b64decode
from .groups import Manifest, canonical_json, make_group_id, manifest_article, split_group_id
from .markup import MAX_TYPE, text_type_for

PROFILE_NAME = "profile"                 # profile@<fp> (section 5.1)
AVATAR_NAME = "avatar"                   # avatar@<fp> (section 8.2)
PROFILE_RETENTION = 7                    # section 5.3

MAX_PROFILE = 8192                       # octets of canonical JSON (section 4.4)
MAX_ABOUT = 2048                         # characters (section 4)
MAX_LINKS = 16
MAX_LANGS = 8
MAX_FEEDS = 16                            # section 4.5
MAX_VALUE, MAX_LABEL = 256, 64           # section 4.2
LINK_KINDS = ("web", "onion", "email", "mastodon", "bluesky", "matrix", "xmpp", "signal",
              "pgp", "github", "gitlab", "facebook", "instagram", "tiktok", "x", "youtube",
              "linkedin")                # section 4.3
_X_KIND = re.compile(r"^x-[a-z0-9-]{1,32}$")
_LANG = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")

PICTURE_TYPES = ("image/png", "image/jpeg", "image/webp")   # section 8.1
MIN_PX, MAX_PX = 32, 128
MAX_PICTURE = 8192                       # octets of the image file
MAX_ALT = 128
MAX_PRIVATE_AVATAR = 11264               # octets of the `avatar` field in a private profile


# Shown before someone publishes their first profile, the same in every client
# (section 9.1; was in the TUI and copied into unseenet-gui, unseenet#320).
PROFILE_WARNING = (
    "Anybody who sees this identity's posts can read its profile.\n\n"
    "A link ties this identity - everything it has posted and will post - to that "
    "account.\n\n"
    "A published profile cannot be fully taken back: others may already have kept a "
    "copy.\n\n"
    "If you only want certain people to know, keep a separate identity for that, or "
    "leave the profile out.")


# Shown before someone publishes their first picture, the same in every client
# (section 8.5).
PICTURE_WARNING = (
    "Anybody who sees this identity's posts can see its picture.\n\n"
    "A photo of yourself, or a picture you also use elsewhere, can be found with a "
    "reverse image search and ties this identity to you or to your other accounts.\n\n"
    "A published picture cannot be fully taken back: others may already have kept a "
    "copy.\n\n"
    "A drawing, or no picture at all - your identicon is shown then - keeps you "
    "harder to find.")


class ProfileError(ValueError):
    pass


def profile_id(pk: bytes) -> str:
    return make_group_id(PROFILE_NAME, pk)


def avatar_id(pk: bytes) -> str:
    return make_group_id(AVATAR_NAME, pk)


# --- the profile object (section 4) -------------------------------------------

def link_kind_known(kind: str) -> bool:
    return kind in LINK_KINDS


def check_profile(obj, *, private: bool = False) -> dict:
    """Validate a profile object; returns it. Raises ProfileError.

    ``private``: a private profile (section 6), which may carry ``avatar`` (8.3)."""
    if not isinstance(obj, dict) or obj.get("v") != 1:
        raise ProfileError("a profile is an object with v 1")
    about = obj.get("about", "")
    if not isinstance(about, str) or len(about) > MAX_ABOUT:
        raise ProfileError(f"about is text of at most {MAX_ABOUT} characters")
    if "about_type" in obj and (not isinstance(obj["about_type"], str)
                                or len(obj["about_type"]) > MAX_TYPE):
        raise ProfileError(f"about_type is a Content-Type of at most {MAX_TYPE} characters")
    links = obj.get("links", [])
    if not isinstance(links, list) or len(links) > MAX_LINKS:
        raise ProfileError(f"at most {MAX_LINKS} links")
    for link in links:
        if not isinstance(link, dict):
            raise ProfileError("a link is an object")
        kind, value = link.get("kind"), link.get("value")
        if not isinstance(kind, str) or not (link_kind_known(kind) or _X_KIND.match(kind)):
            raise ProfileError(f"unknown link kind {kind!r} (use x-...)")
        if not isinstance(value, str) or not value or len(value) > MAX_VALUE:
            raise ProfileError(f"a link's value is 1 to {MAX_VALUE} characters")
        label = link.get("label", "")
        if not isinstance(label, str) or len(label) > MAX_LABEL:
            raise ProfileError(f"a label is at most {MAX_LABEL} characters")
    langs = obj.get("lang", [])
    if (not isinstance(langs, list) or len(langs) > MAX_LANGS
            or any(not isinstance(t, str) or not _LANG.match(t) for t in langs)):
        raise ProfileError(f"lang is a list of at most {MAX_LANGS} BCP 47 tags")
    if "bot" in obj and not isinstance(obj["bot"], bool):
        raise ProfileError("bot is true or false")
    feeds = obj.get("feeds", [])
    if not isinstance(feeds, list) or len(feeds) > MAX_FEEDS or len(set(feeds)) != len(feeds):
        raise ProfileError(f"feeds is a list of at most {MAX_FEEDS} Group IDs, none twice")
    for gid in feeds:
        try:
            split_group_id(gid)
        except (ValueError, AttributeError, TypeError):      # not text, or not name@fp
            raise ProfileError(f"{gid!r} in feeds is not a Group ID") from None
    rest = dict(obj)
    if "avatar" in rest:
        if not private:
            raise ProfileError("a public profile carries its picture in avatar@ (section 8.3)")
        if len(canonical_json(rest["avatar"]).encode()) > MAX_PRIVATE_AVATAR:
            raise ProfileError("the picture in a private profile is too large")
        check_picture(rest.pop("avatar"))
    if len(canonical_json(rest).encode()) > MAX_PROFILE:
        raise ProfileError(f"a profile is at most {MAX_PROFILE} octets")
    return obj


def make_profile(about: str = "", links: list[dict] | None = None,
                 lang: list[str] | None = None, bot: bool = False,
                 markdown: bool = False, feeds: list[str] | None = None) -> dict:
    """A profile object. ``markdown``: ``about`` is Markdown without images (4.1)."""
    obj: dict = {"v": 1}
    if about.strip():
        obj["about"] = about.strip("\n")
        about_type = text_type_for(markdown, about)
        if about_type:
            obj["about_type"] = about_type
    if links:
        obj["links"] = [{k: v for k, v in link.items() if v} for link in links]
    if lang:
        obj["lang"] = list(lang)
    if bot:
        obj["bot"] = True
    if feeds:
        obj["feeds"] = list(feeds)
    return check_profile(obj)


def is_empty(obj: dict) -> bool:
    """No about and no links: shown as no profile (but the bot mark still counts)."""
    return not obj.get("about") and not obj.get("links")


def clean_text(text: str) -> str:
    """Section 4.1: control characters other than LF become a visible substitute."""
    return "".join(ch if ch == "\n" or not (ord(ch) < 32 or 127 <= ord(ch) < 160)
                   else "\ufffd" for ch in text)


@dataclass
class Profile:
    key: bytes
    about: str = ""
    about_type: str | None = None          # Markdown or plain (section 4.1)
    links: list[dict] | None = None
    lang: list[str] | None = None
    bot: bool = False
    serial: int = 0
    raw: dict | None = None

    @classmethod
    def from_object(cls, key: bytes, obj: dict, serial: int = 0) -> "Profile":
        about_type = obj.get("about_type")
        return cls(key=key, about=clean_text(obj.get("about", "")),
                   about_type=about_type if isinstance(about_type, str) else None,
                   links=[dict(link) for link in obj.get("links", [])],
                   lang=list(obj.get("lang", [])), bot=obj.get("bot") is True,
                   serial=serial, raw=obj)


def profile_from_manifest(m: Manifest) -> Profile | None:
    """The public profile in a profile group's manifest (section 5.2), or None."""
    if m.name != PROFILE_NAME or "profile" not in m.raw:
        return None
    try:
        obj = check_profile(m.raw["profile"])
    except ProfileError:
        return None
    return Profile.from_object(m.owner, obj, m.serial)


def profile_manifest(owner: crypto.Identity, profile: dict | None, *, serial: int = 1,
                     pow_bits: int = 18) -> Article:
    """A manifest for the owner's profile group; ``profile`` None removes it (5.3)."""
    data = {"v": 1, "name": PROFILE_NAME, "type": "channel", "owner": owner.key_text,
            "serial": serial, "min_pow": 0, "retention_days": PROFILE_RETENTION,
            "view": "data"}
    if profile is not None:
        data["profile"] = check_profile(profile)
    return manifest_article(owner, profile_id(owner.public_key), data, pow_bits)


# --- pictures (section 8) -----------------------------------------------------

_MAGIC = {"image/png": (b"\x89PNG\r\n\x1a\n",), "image/jpeg": (b"\xff\xd8\xff",),
          "image/webp": (b"RIFF",)}


def sniff_type(data: bytes) -> str | None:
    """The type of an image from its first octets (section 8.1, UN-RFC 0027 9.2)."""
    for ctype, magics in _MAGIC.items():
        if any(data.startswith(m) for m in magics):
            if ctype == "image/webp" and data[8:12] != b"WEBP":
                continue
            return ctype
    return None


def check_picture(obj) -> bytes:
    """Validate a picture object's fields and return the image octets.

    Only the structure and the type of the content are checked here; a client
    decodes the image itself only in a restricted process (UN-RFC 0027, 9.2)."""
    if not isinstance(obj, dict) or obj.get("v") != 1:
        raise ProfileError("a picture is an object with v 1")
    ctype, px = obj.get("type"), obj.get("px")
    if ctype not in PICTURE_TYPES:
        raise ProfileError("a picture is PNG, JPEG or WebP")
    if type(px) is not int or not MIN_PX <= px <= MAX_PX:
        raise ProfileError(f"px is {MIN_PX} to {MAX_PX}")
    alt = obj.get("alt", "")
    if not isinstance(alt, str) or len(alt) > MAX_ALT:
        raise ProfileError(f"alt is at most {MAX_ALT} characters")
    try:
        raw = b64decode(obj.get("data"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProfileError("data is not b64") from exc
    if not raw or len(raw) > MAX_PICTURE:
        raise ProfileError(f"a picture is at most {MAX_PICTURE} octets")
    if sniff_type(raw) != ctype:
        raise ProfileError("the picture's content does not match its type")
    return raw


def make_picture(image: bytes, ctype: str, px: int, alt: str = "") -> dict:
    """A picture object from an image the client has already re-encoded (8.1)."""
    obj = {"v": 1, "type": ctype, "px": px, "data": b64(image)}
    if alt:
        obj["alt"] = alt
    check_picture(obj)
    return obj


def picture_from_manifest(m: Manifest) -> dict | None:
    if m.name != AVATAR_NAME or "avatar" not in m.raw:
        return None
    try:
        check_picture(m.raw["avatar"])
    except ProfileError:
        return None
    return m.raw["avatar"]


def avatar_manifest(owner: crypto.Identity, picture: dict | None, *, serial: int = 1,
                    pow_bits: int = 18) -> Article:
    """A manifest for the owner's avatar group (section 8.2)."""
    data = {"v": 1, "name": AVATAR_NAME, "type": "channel", "owner": owner.key_text,
            "serial": serial, "min_pow": 0, "retention_days": PROFILE_RETENTION,
            "view": "data"}
    if picture is not None:
        check_picture(picture)
        data["avatar"] = picture
    return manifest_article(owner, avatar_id(owner.public_key), data, pow_bits)


# --- identicons (section 8.4) -------------------------------------------------

@dataclass(frozen=True)
class Identicon:
    hue: int                              # degrees; saturation 55 %, lightness 50 %
    cells: tuple[tuple[bool, ...], ...]   # 5 rows of 5, mirrored about the middle

    def rgb(self, lightness: float = 0.5) -> tuple[int, int, int]:
        import colorsys
        r, g, b = colorsys.hls_to_rgb(self.hue / 360, lightness, 0.55)
        return round(r * 255), round(g * 255), round(b * 255)

    def hex(self, lightness: float = 0.5) -> str:
        return "#%02x%02x%02x" % self.rgb(lightness)

    def lines(self, on: str = "██", off: str = "  ") -> list[str]:
        return ["".join(on if c else off for c in row) for row in self.cells]


def identicon(pk: bytes) -> Identicon:
    """The identicon of a key: the same in every client (section 8.4)."""
    seed = H(DS("UNSEENET-IDENTICON-1") + pk)
    hue = (256 * seed[0] + seed[1]) % 360
    filled = [bool((seed[2 + i // 8] >> (i % 8)) & 1) for i in range(15)]
    rows = []
    for r in range(5):
        left = [filled[c * 5 + r] for c in range(3)]
        rows.append(tuple(left + [left[1], left[0]]))
    return Identicon(hue, tuple(rows))
