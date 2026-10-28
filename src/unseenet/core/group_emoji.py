"""A group's own emoji (UN-RFC 0056): small pictures with a name, in the data group
``<name>.emoji@<fp>`` that follows from the group, signed by its owner.

Belongs here: the emoji group's ID and the reserved names (section 3.1), checking a set
(section 4) and making its manifest (section 3.2). Not here: reading and publishing it
(client.session.group_emoji), the node's rules (node.server.manifests), making the
pictures small (client.media).
"""

from __future__ import annotations

import re

from . import crypto
from .article import Article
from .encoding import b64decode
from .groups import Manifest, manifest_article, split_group_id

SEGMENT = "emoji"                     # the reserved last segment (section 3.1)
MAX_EMOJI = 16                        # section 4.3
PX = 32                               # section 4.2
MAX_OCTETS = 1024
MAX_ALT = 64
TYPES = ("image/png", "image/webp")
RETENTION = 7                         # section 3.2: old versions go soon
MANIFEST_MAX = 32768                  # every node takes it (UN-RFC 0002 section 1)
GROUP_TYPES = ("open", "moderated", "channel")     # section 3.3
_NAME = re.compile(r"^[a-z0-9_+-]{2,32}$")


WARNING = ("A group's emoji are public: anybody who finds the group can see them, and once "
           "published they cannot be fully taken back. Some nodes do not carry them, so some "
           "readers see :name: instead.")    # said before the first is published (6.3)


class EmojiError(ValueError):
    pass


def emoji_group_id(group_id: str) -> str:
    """``dk.snak.marsvin@abcd`` -> ``dk.snak.marsvin.emoji@abcd`` (section 3.1)."""
    name, fp = split_group_id(group_id)
    return f"{name}.{SEGMENT}@{fp}"


def is_emoji_name(name: str) -> bool:
    """Whether a group name is reserved for emoji groups: its last segment is ``emoji``
    and there is one before it."""
    return name.endswith("." + SEGMENT)


def main_group_of(emoji_gid: str) -> str | None:
    """The group an emoji group belongs to, or None if it is not named as one."""
    name, fp = split_group_id(emoji_gid)
    return f"{name[: -len(SEGMENT) - 1]}@{fp}" if is_emoji_name(name) else None


def _standard() -> set[str]:
    from .markup import emoji_table
    return set(emoji_table())


def check_name(name) -> str:
    """A name for a group emoji: shortcode syntax, 2 to 32 characters, and never a name of
    the standard table (section 4.1)."""
    if not isinstance(name, str) or not _NAME.match(name):
        raise EmojiError("a name is 2 to 32 of a-z, 0-9, _, + and -")
    if name in _standard():
        raise EmojiError(f":{name}: is a standard emoji: choose another name")
    return name


def check_picture(obj) -> bytes:
    """A group emoji's picture (section 4.2): v 1, PNG or WebP, 32 pixels, at most 1 KiB,
    content matching its type. Returns the image octets; decoding them is for a
    restricted process (UN-RFC 0027 section 9.2)."""
    from .profiles import sniff_type
    if not isinstance(obj, dict) or obj.get("v") != 1:
        raise EmojiError("a picture is an object with v 1")
    if obj.get("type") not in TYPES:
        raise EmojiError("a group emoji is PNG or WebP")
    if obj.get("px") != PX or type(obj.get("px")) is not int:
        raise EmojiError(f"a group emoji is {PX} by {PX} pixels")
    alt = obj.get("alt", "")
    if not isinstance(alt, str) or len(alt) > MAX_ALT:
        raise EmojiError(f"alt is at most {MAX_ALT} characters")
    try:
        raw = b64decode(obj.get("data"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise EmojiError("data is not b64") from exc
    if not raw or len(raw) > MAX_OCTETS:
        raise EmojiError(f"a group emoji is at most {MAX_OCTETS} octets")
    if sniff_type(raw) != obj["type"]:
        raise EmojiError("the picture's content does not match its type")
    return raw


def check_set(obj, *, strict: bool = True) -> dict:
    """A set (section 4): at most 16 names, each a valid picture. ``strict`` (a node, or
    publishing): any bad entry makes the set invalid. Otherwise (a reader) bad entries
    and standard names are left out (section 4.1) and the rest is returned."""
    if not isinstance(obj, dict):
        raise EmojiError("emoji is an object from names to pictures")
    if len(obj) > MAX_EMOJI:
        raise EmojiError(f"at most {MAX_EMOJI} emoji")
    out = {}
    for name, pic in obj.items():
        try:
            check_name(name)
            check_picture(pic)
        except EmojiError:
            if strict:
                raise
            continue
        out[name] = pic
    return out


def emoji_of(m: Manifest | None) -> dict:
    """The usable set in an emoji group's manifest, or {} (section 6.1)."""
    if m is None or not is_emoji_name(m.name) or m.view != "data" or "emoji" not in m.raw:
        return {}
    try:
        return check_set(m.raw["emoji"], strict=False)
    except EmojiError:
        return {}


def emoji_manifest(owner: crypto.Identity, group_id: str, emoji: dict, *, serial: int = 1,
                   pow_bits: int = 18) -> Article:
    """The manifest of ``group_id``'s emoji group (section 3.2), holding ``emoji``."""
    check_set(emoji)
    name, _ = split_group_id(group_id)
    data = {"v": 1, "name": f"{name}.{SEGMENT}", "type": "channel", "owner": owner.key_text,
            "serial": serial, "min_pow": 0, "retention_days": RETENTION, "view": "data",
            "emoji": emoji}
    art = manifest_article(owner, emoji_group_id(group_id), data, pow_bits)
    if len(art.to_bytes()) > MANIFEST_MAX:
        raise EmojiError("the set is too big for one manifest: fewer or smaller pictures")
    return art
