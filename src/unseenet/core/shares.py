"""Sharing (UN-RFC 0060): a post passed on as a reference, never a copy.

Belongs here: what a share is and how it is written (section 4.1), what can be shared
(section 4.2), the manifest fields ``share_from`` and ``share_into`` (sections 4.4 and
7.2), and building share notices (section 8).

Not here: the node's rules that need what it holds (node/server/shares.py), fetching a
target (``XUN-FETCH``, node/server/fetch_commands.py; the client's side in
client/session/shares.py), the store's index of shares (core/store/shares.py).
"""

from __future__ import annotations

from .article import Article, ArticleError, new_article
from . import crypto

KIND_SHARE = "share"                  # Message-Kind of a plain share (section 4.1)
SHARE_OF = "Share-Of"
SHARE_GROUP = "Share-Group"
SHARING = "Sharing"                   # "no": please don't share (section 4.4)
MAX_INTO = 3                          # groups a key shares one target into (section 7.2)

# share notices (section 8)
NOTICE_TYPE = "text/x-unseenet-share"
SHARED_AS = "Shared-As"
SHARED_IN = "Shared-In"


def _is_msgid(value: str) -> bool:
    return value.startswith("<") and value.endswith(">") and len(value) > 2 and " " not in value


def is_share(art: Article) -> bool:
    """A plain share or a share with a comment: an ordinary article with ``Share-Of``."""
    return art.control is None and art.get(SHARE_OF) is not None


def is_plain(art: Article) -> bool:
    """A plain share: ``Message-Kind: share`` (section 4.1)."""
    return (art.control is None
            and (art.get("Message-Kind") or "").strip().lower() == KIND_SHARE)


def target(art: Article) -> tuple[str, str] | None:
    """``(Message-ID, Group ID)`` of the article a share refers to, or None."""
    mid, gid = (art.get(SHARE_OF) or "").strip(), (art.get(SHARE_GROUP) or "").strip()
    return (mid, gid) if mid and gid else None


def address(group_id: str, message_id: str) -> str:
    """The body of a plain share: the target's address (UN-RFC 0031 section 3.4.1)."""
    from .addresses import post_address
    return post_address(group_id, message_id)


def check_form(art: Article) -> None:
    """Section 4.1: raise ArticleError('syntax') unless a share is well formed. Only
    for an article with ``Share-Of`` or of kind share."""
    from .groups import split_group_id
    mid, gid = (art.get(SHARE_OF) or "").strip(), (art.get(SHARE_GROUP) or "").strip()
    if not _is_msgid(mid):
        raise ArticleError("syntax", "Share-Of must be one Message-ID")
    try:
        split_group_id(gid)
    except ValueError:
        raise ArticleError("syntax", "Share-Group must be a Group ID") from None
    if mid == (art.get("Message-ID") or "").strip():
        raise ArticleError("syntax", "a share cannot share itself")
    if is_plain(art):
        if (art.get("Subject") or "").strip():
            raise ArticleError("syntax", "a plain share has no subject")
        if art.body.strip() != address(gid, mid):
            raise ArticleError("syntax", "a plain share's body is its target's address")
        if art.get("Blobs") is not None or art.get("Link-Card") is not None:
            raise ArticleError("syntax", "a plain share has no files or link card")
        if (art.get("References") or "").strip():
            raise ArticleError("syntax", "a share is a thread root")
        return
    if not art.body.strip():
        raise ArticleError("syntax", "a share with a comment has text of its own")
    if (art.get("References") or "").strip():
        raise ArticleError("syntax", "a share is a thread root")


# --- what can be shared (sections 4.2 and 4.4) ----------------------------------

def why_not(tgt: Article, manifest_raw: dict | None = None) -> str | None:
    """Why ``tgt`` cannot be shared, in a few words for the user, or None if it can.
    ``manifest_raw``: its group's manifest, for ``share_from`` and the group type."""
    from . import reactions as rx
    m = manifest_raw or {}
    if "Encrypted" in tgt or m.get("type") in ("closed", "inbox"):
        return "closed things are not shared"
    if tgt.control is not None:
        return "not an ordinary post"
    if rx.is_reaction(tgt):
        return "a reaction is not shared"
    if is_plain(tgt):
        return "share the original instead"          # the client resolves it
    if (tgt.get(SHARING) or "").strip().lower() == "no" or m.get("share_from") is False:
        return "the author asked not to share this"
    return None


def share_into(manifest_raw: dict) -> bool:
    """Whether a group takes shares (section 7.2): ``share_into``, by default true
    except for chat groups."""
    if "share_into" in manifest_raw:
        return manifest_raw["share_into"] is True
    return manifest_raw.get("view") != "chat"


def takes_plain(manifest_raw: dict) -> bool:
    """Whether a group takes a plain share (section 7.2): not a discussion group."""
    return share_into(manifest_raw) and manifest_raw.get("view", "threads") != "threads"


def check_manifest_fields(data: dict) -> None:
    """ValueError unless ``share_from``/``share_into`` are booleans."""
    for f in ("share_from", "share_into"):
        if f in data and not isinstance(data[f], bool):
            raise ValueError(f"{f} is true or false")


def own_feed(author_key: bytes) -> str:
    """The sharer's own feed, ``feed@<fingerprint>`` (UN-RFC 0034 section 5.1)."""
    return "feed@" + crypto.fingerprint(author_key)


def check(art: Article, manifest_raw: dict) -> None:
    """What a node checks of a share with only its group's manifest (sections 4.1 and
    7.2): the form, ``share_into``, and no plain shares into discussion groups.
    ArticleError otherwise."""
    check_form(art)
    if art.group == own_feed(art.author_key):
        return                          # one's own feed always takes one's shares
    if not share_into(manifest_raw):
        raise ArticleError("permission", "this group takes no shares")
    if is_plain(art) and not takes_plain(manifest_raw):
        raise ArticleError("permission", "a share into a discussion group needs a comment")


# --- building shares (section 4.1) -----------------------------------------------

def headers(target_id: str, target_group: str) -> list[tuple[str, str]]:
    """The two headers every share carries."""
    return [(SHARE_OF, target_id), (SHARE_GROUP, target_group)]


def build_plain(group: str, target_id: str, target_group: str, *,
                from_name: str | None = None, supersedes: str | None = None) -> Article:
    """An unsigned plain share of ``target_id`` (in ``target_group``) for ``group``."""
    extra = [("Content-Type", "text/plain; charset=utf-8"), ("Message-Kind", KIND_SHARE),
             *headers(target_id, target_group)]
    if supersedes:
        extra.append(("Supersedes", supersedes))
    return new_article(group, "", address(target_group, target_id) + "\n",
                       from_name=from_name, extra=extra)


# --- share notices (section 8) ----------------------------------------------------

def notice_line(sharer: str, where: str, subject: str) -> str:
    """The one line of a notice: who shared, where, and what - never the comment."""
    what = f": {subject}" if subject else ""
    return f"{sharer} shared your post {where}{what}"


def notice_headers(target_id: str, target_group: str, share_id: str,
                   share_group: str) -> list[tuple[str, str]]:
    return [("Content-Type", f"{NOTICE_TYPE}; charset=utf-8"), *headers(target_id, target_group),
            (SHARED_AS, share_id), (SHARED_IN, share_group)]


def is_notice(art: Article) -> bool:
    """A share notice: its Content-Type (section 8)."""
    return (art.get("Content-Type") or "").split(";")[0].strip().lower() == NOTICE_TYPE


def notice_fields(art: Article) -> tuple[str, str, str, str] | None:
    """``(Share-Of, Share-Group, Shared-As, Shared-In)`` of a notice, or None if a
    header is missing or malformed."""
    vals = [(art.get(h) or "").strip() for h in (SHARE_OF, SHARE_GROUP, SHARED_AS, SHARED_IN)]
    if not all(vals) or not _is_msgid(vals[0]) or not _is_msgid(vals[2]):
        return None
    return vals[0], vals[1], vals[2], vals[3]
