"""Groups, manifests, closed-group encryption and posting rules (UN-RFC 0004)."""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import crypto
from .article import Article, ArticleError, format_date, new_article, parse_date
from .encoding import DS, H, b32, b64, b64decode

GROUP_TYPES = ("open", "moderated", "channel", "closed", "inbox", "state")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+_-]*(\.[a-z0-9][a-z0-9+_-]*)*$")
_FP_RE = re.compile(r"^[a-z2-7]{16}$")
ENC_SCHEME = "xchacha20poly1305"
INBOX_SCHEME = "sealedbox"
INBOX_SCHEME2 = "sealedbox2"      # two envelopes: the sender can read it too (UN-RFC 0009 2.3)
INBOX_SCHEMES = (INBOX_SCHEME, INBOX_SCHEME2)
ENVELOPE = 80                     # a sealed box of a 32-octet key
INBOX_NAME = "inbox"            # personal inbox: inbox@<fp> (UN-RFC 0009, 2.2)


# --- group IDs (section 1) -------------------------------------------------

# --- #group references in posts (#172) --------------------------------------

# '#' and a group name, optionally '@' and the start of the owner's fingerprint:
# #dk.snak.marsvin or #dk.snak@abcd. Not inside a word, a URL fragment or an
# address; '# heading' (with a space) is markdown, not a reference. The name must
# have a letter, so '#170' stays an issue number, and it must end where a name
# can: '#dk.snak.' is dk.snak, '#dk.supernørder' is nothing (names are a-z).
GROUP_REF_RE = re.compile(
    r"(?<![\w@#/&.+-])#(?=[a-z0-9+_.-]*[a-z])"
    r"([a-z0-9][a-z0-9+_-]*(?:\.[a-z0-9][a-z0-9+_-]*)*)"
    r"(?:@([a-z2-7]{4,16}))?"
    r"(?![\w+@-]|\.\w)")


@dataclass(frozen=True)
class GroupRef:
    """A group named in a text: '#name', or '#name@fp' with a fingerprint prefix."""
    name: str
    fp: str = ""

    @property
    def text(self) -> str:
        return f"#{self.name}" + (f"@{self.fp}" if self.fp else "")

    def matches(self, group_id: str) -> bool:
        try:
            name, fp = split_group_id(group_id)
        except ValueError:
            return False
        return name == self.name and fp.startswith(self.fp)


def group_refs(text: str) -> list[GroupRef]:
    """The groups a text names with #, each once, in the order they appear (#172)."""
    out: list[GroupRef] = []
    for m in GROUP_REF_RE.finditer(text or ""):
        if len(m.group(1)) > 128:
            continue
        ref = GroupRef(m.group(1), m.group(2) or "")
        if ref not in out:
            out.append(ref)
    return out


def make_group_id(name: str, owner_pk: bytes) -> str:
    if not _NAME_RE.match(name) or len(name) > 128:
        raise ValueError(f"invalid group name {name!r}")
    return f"{name}@{crypto.fingerprint(owner_pk)}"


def split_group_id(group_id: str) -> tuple[str, str]:
    """``(name, fingerprint)`` of a Group ID; ``ValueError`` if it is not one
    (UN-RFC 0004 section 2)."""
    name, at, fp = group_id.rpartition("@")
    if not at or not _NAME_RE.match(name) or len(name) > 128 or not _FP_RE.match(fp):
        raise ValueError(f"invalid group ID {group_id!r}")
    return name, fp


def short_group_id(group_id: str) -> str:
    """A group's name with a short fingerprint, ``name@abcd``, for showing - never
    for finding a group, where the full ID is needed."""
    name, fp = split_group_id(group_id)
    return f"{name}@{fp[:4]}"


# --- canonical JSON ---------------------------------------------------------

def canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_canonical_json(body: str) -> dict:
    text = body.rstrip("\n")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArticleError("syntax", "body is not JSON") from exc
    if not isinstance(obj, dict) or canonical_json(obj) != text:
        raise ArticleError("syntax", "body is not canonical JSON")
    return obj


# --- chats and posts (UN-RFC 0028) ---------------------------------------

KIND_CHAT, KIND_POST = "chat", "post"
MESSAGE_KINDS = (KIND_CHAT, KIND_POST)     # what ``kinds`` may name (UN-RFC 0028, 4.1)
KIND_REACTION = "reaction"                 # UN-RFC 0048: never in ``kinds``


MAX_SUPERSEDES = 32       # earlier versions an edit may name (UN-RFC 0042 section 2)


def parse_supersedes(art: Article, *, control_ok: bool = False) -> list[str]:
    """The earlier versions an edit names, newest first (UN-RFC 0042 section 2);
    [] for an article that is not an edit. Raises ArticleError('syntax') if the
    header is malformed, names more than 32, the article itself or one twice."""
    value = art.get("Supersedes")
    if value is None:
        return []
    ids = value.split()
    if not ids or any(not (i.startswith("<") and i.endswith(">") and len(i) > 2) for i in ids):
        raise ArticleError("syntax", "Supersedes must list Message-IDs")
    if len(ids) > MAX_SUPERSEDES:
        raise ArticleError("syntax", f"Supersedes names more than {MAX_SUPERSEDES} versions")
    if len(set(ids)) != len(ids) or art.message_id in ids:
        raise ArticleError("syntax", "Supersedes names a version twice, or the edit itself")
    if art.control and not control_ok:     # pins may name pins (UN-RFC 0033 section 3.1)
        raise ArticleError("syntax", "a control article cannot be an edit")
    return ids


def message_kind(art: Article) -> str:
    """The kind of a message (UN-RFC 0028 section 3.1): of a plain article, or of the
    inner article of a closed group or an inbox. Without the header, a post."""
    value = art.get("Message-Kind", "").strip().lower()
    if value == KIND_REACTION and art.control is None:     # UN-RFC 0048 section 3.1
        return KIND_REACTION
    return KIND_CHAT if value == KIND_CHAT else KIND_POST


def _kinds(data: dict) -> tuple[str, ...]:
    """A manifest's ``kinds`` (UN-RFC 0028 section 4.1); raises ValueError if invalid."""
    if "kinds" not in data:
        return MESSAGE_KINDS
    kinds = data["kinds"]
    if (not isinstance(kinds, list) or not kinds or len(set(kinds)) != len(kinds)
            or any(k not in MESSAGE_KINDS for k in kinds)):
        raise ValueError('kinds must be a non-empty list of "chat" and/or "post"')
    return tuple(kinds)


# --- comments in channels (UN-RFC 0030) ----------------------------------

COMMENTS_NONE, COMMENTS_OPEN = "none", "open"


def _comments(data: dict) -> tuple[str, int | None]:
    """A manifest's ``comments`` and ``comment_days`` (UN-RFC 0030 section 3);
    raises ValueError if invalid or given for a group that is not a channel."""
    has = "comments" in data or "comment_days" in data
    if has and data.get("type") != "channel":
        raise ValueError("comments and comment_days are for channels only")
    comments = data.get("comments", COMMENTS_NONE)
    if comments not in (COMMENTS_NONE, COMMENTS_OPEN):
        raise ValueError('comments must be "none" or "open"')
    days = data.get("comment_days")
    if days is not None and (type(days) is not int or days < 1):
        raise ValueError("comment_days must be a positive integer")
    return comments, days


# --- key-bound groups (UN-RFC 0029) --------------------------------------

KEY_BOUND_NAMES = ("inbox", "names", "profile", "avatar", "ripe", "feed", "site",  # UN-RFC 0029, 2
                   "state")
STATE_NAME = "state"              # state@<fp>: the owner's state, encrypted (UN-RFC 0044)
STATE_MAX = 22 * 1024             # the state field: 16 KiB of plaintext, encrypted, in base64
# personal groups (UN-RFC 0029 section 2.1): channels with this view, started by choice
PERSONAL_GROUPS = {"feed": "feed", "site": "pages"}
# UN-RFC 0040 section 9: the largest manifest article of each key-bound group, in
# octets (feed@, attest@ and site@ for when they become key-bound groups).
KEY_BOUND_MANIFEST_MAX = {"inbox": 16 * 1024, "feed": 8 * 1024, "profile": 10 * 1024, "state": 24 * 1024,
                          "avatar": 12 * 1024, "ripe": 24 * 1024, "names": 64 * 1024, "attest": 64 * 1024,
                          "site": 64 * 1024}
MAX_LIFETIME = timedelta(days=730)       # expires at most this long after Date (section 3)
RENEW_WHEN_LEFT = timedelta(days=545)    # renew once less than this remains (section 4)
RENEW_WINDOW = timedelta(days=30)        # at a random moment within this (section 4)
# Section 4: a new identity's key-bound groups live this long until it is in use,
# renewed when fewer than FIRST_RENEW_WHEN_LEFT remain (unseenet #270).
FIRST_LIFETIME = timedelta(days=60)
FIRST_RENEW_WHEN_LEFT = timedelta(days=30)
REMOVE_AFTER = timedelta(days=30)        # nodes remove expired groups within this (section 5)


def is_key_bound(group_id: str) -> bool:
    """A group whose Group ID follows from its owner's key alone (UN-RFC 0029, 2)."""
    try:
        name, _ = split_group_id(group_id)
    except ValueError:
        return False
    return name in KEY_BOUND_NAMES


def format_expires(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_expires(value) -> datetime:
    """An RFC 3339 UTC date, as in ``expires`` (UN-RFC 0029 section 3)."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("expires must be an RFC 3339 UTC date")
    dt = datetime.fromisoformat(value[:-1] + "+00:00")
    if dt.tzinfo is None:
        raise ValueError("expires must be an RFC 3339 UTC date")
    return dt


def stored_expires(data: dict) -> datetime | None:
    """``expires`` of a stored manifest's JSON, or None if absent or unreadable."""
    try:
        return parse_expires(data.get("expires"))
    except (ValueError, TypeError):
        return None


# --- manifests (section 3) --------------------------------------------------

@dataclass
class Manifest:
    group_id: str
    name: str
    type: str
    owner: bytes
    serial: int
    moderators: list[bytes] = field(default_factory=list)
    posters: list[bytes] = field(default_factory=list)
    min_pow: int = 0
    retention_days: int = 90
    title: str = ""
    description: str = ""
    local: bool = False
    submissions: str | None = None
    rules: str = ""                      # UN-RFC 0014
    rules_type: str | None = None        # UN-RFC 0014 2.1: Markdown or plain
    view: str = "threads"                # UN-RFC 0008
    low_latency: bool = False            # UN-RFC 0008
    kinds: tuple[str, ...] = MESSAGE_KINDS   # UN-RFC 0028, 4.1
    banned: list[bytes] = field(default_factory=list)   # UN-RFC 0004, 5.1
    comments: str = COMMENTS_NONE        # UN-RFC 0030, channels only
    comment_days: int | None = None      # UN-RFC 0030
    expires: datetime | None = None      # UN-RFC 0029, key-bound groups only
    message_id: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_article(cls, art: Article, *, stored: bool = False) -> "Manifest":
        """Validate a manifest article (section 4, steps 1-3). ``stored``: one a node
        already carries, which may be from before UN-RFC 0029 and lack ``expires``."""
        if art.control != ["manifest"]:
            raise ArticleError("syntax", "not a manifest")
        data = parse_canonical_json(art.body)
        try:
            name, fp = split_group_id(art.group)
            owner = crypto.key_from_text(data["owner"])
            m = cls(
                group_id=art.group, name=data["name"], type=data["type"], owner=owner,
                serial=int(data["serial"]),
                moderators=[crypto.key_from_text(k) for k in data.get("moderators", [])],
                posters=[crypto.key_from_text(k) for k in data.get("posters", [])],
                min_pow=int(data.get("min_pow", 0)),
                retention_days=int(data.get("retention_days", 90)),
                title=data.get("title", ""), description=data.get("description", ""),
                local=data.get("local") is True, submissions=data.get("submissions"),
                rules=str(data.get("rules", "")), view=data.get("view", "threads"),
                rules_type=(data["rules_type"] if isinstance(data.get("rules_type"), str)
                            else None),
                low_latency=data.get("low_latency") is True,
                # an inbox takes both kinds, whatever it says (UN-RFC 0028, 4.1)
                kinds=MESSAGE_KINDS if data.get("type") == "inbox" else _kinds(data),
                banned=[_banned_key(b) for b in data.get("banned", [])],
                message_id=art.message_id, raw=data,
            )
            m.comments, m.comment_days = _comments(data)
            from .pins import max_pins
            max_pins(data)                                  # UN-RFC 0033 section 4.1
            from .reactions import check_field as check_reactions
            if data.get("type") != "inbox":                 # ignored there (0048, 4.3)
                check_reactions(data)                       # UN-RFC 0048 section 4.1
            from .blobs import check_attachments_field
            check_attachments_field(data)                   # UN-RFC 0027 section 5.1
            if data.get("view") == "pages":                 # UN-RFC 0035 section 3
                from .pages import check_manifest_fields
                check_manifest_fields(data)
            if "expires" in data:
                m.expires = parse_expires(data["expires"])
        except (KeyError, TypeError, ValueError, crypto.CryptoError) as exc:
            raise ArticleError("syntax", f"bad manifest: {exc}") from exc
        if data.get("v") != 1 or m.name != name or m.type not in GROUP_TYPES or m.serial < 1:
            raise ArticleError("syntax", "bad manifest fields")
        if crypto.fingerprint(owner) != fp or owner != art.author_key:
            raise ArticleError("permission", "manifest not signed by group owner")
        if m.view == "pages" and m.type != "channel":       # UN-RFC 0035 section 3
            raise ArticleError("syntax", "only a channel can be shown as pages")
        if is_key_bound(art.group) and name in PERSONAL_GROUPS and (
                m.type != "channel" or m.view != PERSONAL_GROUPS[name]):
            raise ArticleError("syntax", f"{name}@ is a channel with view "
                               f"{PERSONAL_GROUPS[name]} (UN-RFC 0029 section 2.1)")
        if (m.type == "state") != (is_key_bound(art.group) and name == STATE_NAME):
            raise ArticleError("syntax", "state@ is the one group of type state (UN-RFC 0044)")
        if m.type == "state":                               # UN-RFC 0044 section 3
            st = data.get("state")
            if not isinstance(st, str) or not 0 < len(st) <= STATE_MAX:
                raise ArticleError("syntax", "a state group's manifest carries its state")
        if is_key_bound(art.group):                         # UN-RFC 0029 section 3
            if m.expires is None and not stored:
                raise ArticleError("syntax", "a key-bound group's manifest needs expires")
            if m.expires is not None and m.expires > parse_date(art["Date"]) + MAX_LIFETIME:
                raise ArticleError("syntax", "expires is more than 730 days after Date")
        return m

    def expired(self, now: datetime | None = None) -> bool:
        """A key-bound group whose manifest has run out (UN-RFC 0029 section 5)."""
        return self.expires is not None and (now or datetime.now(timezone.utc)) >= self.expires

    def renewal_due(self, now: datetime | None = None) -> bool:
        """Fewer than 545 days left: time for the owner to renew (UN-RFC 0029, 4)."""
        return (self.expires is not None
                and self.expires - (now or datetime.now(timezone.utc)) < RENEW_WHEN_LEFT)

    def supersedes(self, other: "Manifest | None") -> bool:
        if other is None:
            return True
        if (self.serial, other.message_id) > (other.serial, self.message_id):
            return True
        return False

    def can_post_directly(self, pk: bytes) -> bool:
        if pk == self.owner or pk in self.moderators:
            return True
        if self.type == "open":
            return True
        if self.type == "channel":
            return pk in self.posters
        return False

    def is_starter(self, pk: bytes) -> bool:
        """May start a thread in a channel (UN-RFC 0030 section 2)."""
        return self.type == "channel" and (pk == self.owner or pk in self.moderators
                                           or pk in self.posters)


def make_manifest(owner: crypto.Identity, name: str, gtype: str, *, serial: int = 1,
                  title: str = "", description: str = "", moderators=(), posters=(),
                  min_pow: int = 0, retention_days: int = 90, sealed: str | None = None,
                  local: bool = False, submissions: str | None = None,
                  rules: str = "", view: str | None = None, low_latency: bool = False,
                  kinds: list[str] | None = None, comments: str | None = None,
                  comment_days: int | None = None, pow_bits: int = 18,
                  rules_type: str | None = None, lifetime: timedelta | None = None,
                  extra: dict | None = None) -> Article:
    """``extra``: further manifest fields - ``attachments`` (UN-RFC 0027), ``max_pins``
    (0033), ``max_pages``, ``home`` and ``index`` (0035), ``reactions`` (0048) - checked
    as nodes check them."""
    if gtype not in GROUP_TYPES:
        raise ValueError(gtype)
    group_id = make_group_id(name, owner.public_key)
    data = {"v": 1, "name": name, "type": gtype, "owner": owner.key_text, "serial": serial,
            "min_pow": min_pow, "retention_days": retention_days}
    if title:
        data["title"] = title
    if description:
        data["description"] = description
    if moderators:
        data["moderators"] = list(moderators)
    if posters:
        data["posters"] = list(posters)
    if sealed:
        data["sealed"] = sealed
    if local:
        data["local"] = True
    if submissions:
        data["submissions"] = submissions
    if rules:
        data["rules"] = rules
        if rules_type:
            data["rules_type"] = rules_type
    if view:
        data["view"] = view
    if low_latency:
        data["low_latency"] = True
    if kinds is not None and tuple(kinds) != MESSAGE_KINDS and gtype != "inbox":
        data["kinds"] = list(kinds)          # both is the default, so it is left out
    if comments and comments != COMMENTS_NONE:  # none is the default (UN-RFC 0030)
        data["comments"] = comments
    if comment_days is not None:
        data["comment_days"] = comment_days
    for key, value in (extra or {}).items():
        if key not in EXTRA_FIELDS:
            raise ValueError(f"{key} is not a manifest field this client sets")
        if value is not None:
            data[key] = value
    check_extra_fields(data)
    return manifest_article(owner, group_id, data, pow_bits, lifetime=lifetime)


# manifest fields of the 0.5.0 documents, set through ``extra`` and Session.update_group
EXTRA_FIELDS = ("attachments", "max_pins", "max_pages", "home", "index", "reactions")


def check_extra_fields(data: dict) -> None:
    """ValueError if ``attachments``, ``max_pins``, ``max_pages``, ``home``, ``index`` or
    ``reactions`` are not as UN-RFC 0027 section 5.1, 0033 section 4.1, 0035 section 3
    and 0048 section 4.1 say."""
    from .blobs import check_attachments_field
    from .pages import check_manifest_fields
    from .pins import max_pins
    from .reactions import check_field as check_reactions
    check_attachments_field(data)
    max_pins(data)
    if data.get("type") != "inbox":
        check_reactions(data)                              # UN-RFC 0048 section 4.1
    if data.get("view") == "pages":
        check_manifest_fields(data)
    elif "max_pages" in data or "home" in data or "index" in data:
        raise ValueError("max_pages, home and index are for sites (view pages)")


MAX_RULES = 8192
VIEWS = ("threads", "chat", "data", "feed", "pages")   # UN-RFC 0008 3.1, 0034 3.1, 0035 3


def manifest_article(owner: crypto.Identity, group_id: str, data: dict, pow_bits: int = 18,
                     now: datetime | None = None, lifetime: timedelta | None = None) -> Article:
    """Sign a manifest from its JSON fields (used for new and updated manifests).

    A key-bound group's manifest gets a fresh ``expires``, ``lifetime`` from now -
    by default the longest UN-RFC 0029 allows - so every new manifest of such a
    group is also its renewal."""
    if len(data.get("rules", "")) > MAX_RULES:
        raise ValueError(f"rules are limited to {MAX_RULES} characters")
    if "rules_type" in data and (not isinstance(data["rules_type"], str)
                                 or len(data["rules_type"]) > 128):
        raise ValueError("rules_type is a Content-Type of at most 128 characters")
    if data.get("view", "threads") not in VIEWS:
        raise ValueError("view must be one of " + ", ".join(VIEWS))
    _kinds(data)                                           # UN-RFC 0028, 4.1
    _comments(data)                                        # UN-RFC 0030, 3
    now = now or datetime.now(timezone.utc)
    if is_key_bound(group_id):
        life = min(lifetime or MAX_LIFETIME, MAX_LIFETIME)
        data["expires"] = format_expires(parse_date(format_date(now)) + life)
    art = new_article(group_id, None, canonical_json(data), now=now,
                      extra=[("Control", "manifest"), ("Content-Type", "application/json")])
    return art.finalize(owner, pow_bits)


# --- moderation (section 5) -------------------------------------------------

def approval_message(group_id: str, message_id: str) -> bytes:
    return group_id.encode() + b"\x00" + message_id.encode("ascii")


def approve(art: Article, moderator: crypto.Identity) -> Article:
    art.set("Approved-By", moderator.key_text)
    art.set("Approval", moderator.sign_text(crypto.PURPOSE_APPROVAL,
                                            approval_message(art.group, art.message_id)))
    return art


def has_valid_approval(art: Article, manifest: Manifest) -> bool:
    try:
        pk = crypto.key_from_text(art["Approved-By"])
        sig = crypto.sig_from_text(art["Approval"])
    except (KeyError, crypto.CryptoError):
        return False
    if pk != manifest.owner and pk not in manifest.moderators:
        return False
    return crypto.verify(pk, crypto.PURPOSE_APPROVAL,
                         approval_message(art.group, art.message_id), sig)


# --- closed groups (section 6) ----------------------------------------------

def envelope_tag(group_id: str, epoch: int, member_pk: bytes) -> str:
    data = (DS("UNSEENET-RECIPIENT-1") + group_id.encode() + b"\x00"
            + str(epoch).encode() + b"\x00" + member_pk)
    return b32(H(data))[:16]


def make_key_update(owner: crypto.Identity, group_id: str, epoch: int,
                    keys: crypto.GroupKeys, members: list[bytes], *,
                    grant_only: bool = False, closes_previous: bool = False,
                    pow_bits: int = 18) -> Article:
    """Control: key-update (new epoch) or key-grant (add members)."""
    members = list(dict.fromkeys([owner.public_key, *members]))
    data: dict = {"v": 1, "epoch": epoch,
                  "envelopes": {envelope_tag(group_id, epoch, pk): b64(crypto.seal_to(pk, keys.secret))
                                for pk in members}}
    kind = "key-grant" if grant_only else "key-update"
    if not grant_only:
        data["member_key"] = keys.member.key_text
        if closes_previous:                       # a member was removed (section 6.2)
            data["closes_previous"] = True
    art = new_article(group_id, None, canonical_json(data),
                      extra=[("Control", f"{kind} {epoch}"), ("Content-Type", "application/json")])
    return art.finalize(owner, pow_bits)


def parse_key_update(art: Article) -> tuple[int, bytes | None, dict]:
    ctl = art.control or []
    if len(ctl) != 2 or ctl[0] not in ("key-update", "key-grant") or not ctl[1].isdigit():
        raise ArticleError("syntax", "bad key control")
    data = parse_canonical_json(art.body)
    epoch = int(ctl[1])
    if data.get("v") != 1 or data.get("epoch") != epoch or not isinstance(data.get("envelopes"), dict):
        raise ArticleError("syntax", "bad key-update body")
    member_key = None
    if ctl[0] == "key-update":
        try:
            member_key = crypto.key_from_text(data["member_key"])
        except (KeyError, crypto.CryptoError) as exc:
            raise ArticleError("syntax", "bad member_key") from exc
    return epoch, member_key, data["envelopes"]


def open_envelope(art: Article, me: crypto.Identity) -> tuple[int, crypto.GroupKeys] | None:
    """Your keys from a key update: ``(epoch, GroupKeys)`` if it has an envelope for
    ``me``, else None (UN-RFC 0004 section 6)."""
    epoch, _, envelopes = parse_key_update(art)
    box = envelopes.get(envelope_tag(art.group, epoch, me.public_key))
    if box is None:
        return None
    return epoch, crypto.GroupKeys(me.open_sealed(b64decode(box)))


def _aad(group_id: str, epoch: int) -> bytes:
    return group_id.encode() + b"\x00" + str(epoch).encode()


def encrypted_article(group_id: str, epoch: int, keys: crypto.GroupKeys, author: crypto.Identity,
                      *, from_name: str, subject: str, body: str,
                      references: list[str] | None = None, kind: str = KIND_POST,
                      content_type: str | None = None, pow_bits: int = 18,
                      extra: list[tuple[str, str]] | None = None,
                      inner_extra: list[tuple[str, str]] | None = None) -> Article:
    """An article for a closed group; its kind (UN-RFC 0028) is inside the encryption.
    ``extra``: outer headers nodes must read, e.g. Supersedes (UN-RFC 0042, 2) or
    ``Blobs``; ``inner_extra``: headers only members read, e.g. ``Attachment-<n>``
    with the file keys (UN-RFC 0027 section 4.3). A reaction (UN-RFC 0048, 8) has
    kind ``reaction`` and its ``Reaction`` header in ``inner_extra``."""
    if kind not in MESSAGE_KINDS + (KIND_REACTION,):
        raise ValueError(f"unknown message kind: {kind}")
    inner = Article([("From", from_name), ("Subject", subject if kind == KIND_POST else ""),
                     ("Content-Type", content_type or "text/plain; charset=utf-8"),
                     ("Message-Kind", kind)] + list(inner_extra or []), body)
    blob = crypto.aead_encrypt(keys.enc_key, inner.to_bytes(), _aad(group_id, epoch))
    outer_body = "\n".join(textwrap.wrap(b64(blob), 76)) + "\n"
    art = new_article(group_id, None, outer_body, references=references,
                      extra=[("Encrypted", f"{ENC_SCHEME}; epoch={epoch}")] + (extra or []))
    return art.finalize(author, pow_bits, member=keys.member)


def encryption_epoch(art: Article) -> int:
    """The key epoch an encrypted article names in its ``Encrypted`` header."""
    m = re.match(rf"^{ENC_SCHEME};\s*epoch=(\d+)$", art.get("Encrypted", "").strip())
    if not m:
        raise ArticleError("syntax", "unsupported Encrypted header")
    return int(m.group(1))


def decrypt_article(art: Article, keys: crypto.GroupKeys) -> Article:
    """The inner article of a closed group's post, decrypted with the epoch's keys
    (UN-RFC 0004 section 6). Raises if it was not made with them."""
    epoch = encryption_epoch(art)
    blob = b64decode("".join(art.body.split()))
    return Article.from_bytes(crypto.aead_decrypt(keys.enc_key, blob, _aad(art.group, epoch)))


def verify_member_signature(art: Article, member_pk: bytes) -> bool:
    try:
        sig = crypto.sig_from_text(art["Member-Signature"])
    except (KeyError, crypto.CryptoError):
        return False
    return crypto.verify(member_pk, crypto.PURPOSE_MEMBER, art.canonical(), sig)


# --- inbox groups (UN-RFC 0009) ----------------------------------------------

def personal_inbox_id(pk: bytes) -> str:
    """The Group ID of the personal inbox of a public key: ``inbox@<fingerprint>``
    (UN-RFC 0009)."""
    return make_group_id(INBOX_NAME, pk)


def _sender_message(group_id: str, outer_key_text: str, inner_canonical: bytes) -> bytes:
    return (group_id.encode() + b"\x00" + outer_key_text.encode() + b"\x00" + inner_canonical)


def inbox_article(group_id: str, owner_pk: bytes, *, from_name: str, subject: str, body: str,
                  sender: crypto.Identity | None = None, reply_inbox: str | None = None,
                  references: list[str] | None = None, content_type: str | None = None,
                  kind: str = KIND_POST, pow_bits: int = 18,
                  extra: list[tuple[str, str]] | None = None,
                  two_envelopes: bool = False, copy_to: bytes | None = None,
                  outer_extra: list[tuple[str, str]] | None = None) -> Article:
    """An article sealed to the inbox owner, signed by a one-time key (UN-RFC 0009, 2.3).

    ``kind`` is a chat or a post (UN-RFC 0028); it travels inside the sealed box, as do
    ``extra`` inner headers (e.g. a mention notice's, UN-RFC 0032). With
    ``two_envelopes`` it is ``sealedbox2``: the second envelope opens it for
    ``copy_to`` (the sender's own key), or for nobody when that is None - so nobody can
    tell whether the sender kept a copy (UN-RFC 0044 section 6.1). ``outer_extra``:
    headers nodes must read, i.e. ``Blobs`` (UN-RFC 0027 section 4.3); the files'
    ``Attachment-<n>`` go in ``extra``, inside.
    """
    if crypto.fingerprint(owner_pk) != split_group_id(group_id)[1]:
        raise ValueError("owner key does not match the inbox's group ID")
    if kind not in MESSAGE_KINDS and kind != KIND_REACTION:   # UN-RFC 0048 4.3: also a reaction
        raise ValueError(f"unknown message kind: {kind}")
    one_time = crypto.Identity.generate()
    headers = [("From", from_name), ("Subject", "" if kind == KIND_CHAT else subject),
               ("Content-Type", content_type or "text/plain; charset=utf-8"),
               ("Message-Kind", kind)]
    if reply_inbox:
        headers.append(("Reply-Inbox", reply_inbox))
    headers.extend(extra or [])
    if sender is not None:
        headers.append(("Sender-Key", sender.key_text))
    inner = Article(headers, body)
    if sender is not None:
        msg = _sender_message(group_id, one_time.key_text, inner.canonical())
        inner.set("Sender-Signature", sender.sign_text(crypto.PURPOSE_INBOX_SENDER, msg))
    if two_envelopes:
        import os as _os
        import nacl.bindings as nb
        key, nonce = _os.urandom(32), _os.urandom(24)
        ct = nb.crypto_aead_xchacha20poly1305_ietf_encrypt(inner.to_bytes(), group_id.encode(),
                                                            nonce, key)
        second = (crypto.seal_to(copy_to, key) if copy_to is not None else
                  crypto.seal_to(crypto.Identity.generate().public_key, _os.urandom(32)))
        box, scheme = crypto.seal_to(owner_pk, key) + second + nonce + ct, INBOX_SCHEME2
    else:
        box, scheme = crypto.seal_to(owner_pk, inner.to_bytes()), INBOX_SCHEME
    text = b64(box)                     # fixed lines: textwrap breaks at the "-" of base64url,
    outer_body = "\n".join(text[i:i + 76] for i in range(0, len(text), 76)) + "\n"   # and the
    art = new_article(group_id, None, outer_body, references=references,           # size would vary
                      extra=[("Encrypted", scheme)] + list(outer_extra or []))
    return art.finalize(one_time, pow_bits)


def open_inbox_article(art: Article, owner: crypto.Identity) -> tuple[Article, bytes | None]:
    """Decrypt an inbox article. Returns (inner article, verified sender key or None).

    Raises ArticleError if it cannot be opened or a claimed sender does not verify.
    """
    scheme = art.get("Encrypted", "").strip()
    if scheme not in INBOX_SCHEMES:
        raise ArticleError("syntax", "not an inbox article")
    try:
        raw = b64decode("".join(art.body.split()))
        if scheme == INBOX_SCHEME:
            blob = crypto.open_sealed_with(owner, raw)
        else:                           # either envelope: the owner's, or the sender's copy
            import nacl.bindings as nb
            key = None
            for env in (raw[:ENVELOPE], raw[ENVELOPE:2 * ENVELOPE]):
                try:
                    key = crypto.open_sealed_with(owner, env)
                    break
                except crypto.CryptoError:
                    continue
            if key is None or len(key) != 32:
                raise crypto.CryptoError("no envelope for this key")
            nonce, ct = raw[2 * ENVELOPE:2 * ENVELOPE + 24], raw[2 * ENVELOPE + 24:]
            blob = nb.crypto_aead_xchacha20poly1305_ietf_decrypt(ct, art.group.encode(), nonce, key)
    except Exception as exc:  # noqa: BLE001 - CryptoError, a bad layout, a failed tag
        raise ArticleError("signature", "cannot decrypt inbox article") from exc
    inner = Article.from_bytes(blob)
    if "Sender-Key" not in inner:
        return inner, None
    try:
        sender = crypto.key_from_text(inner["Sender-Key"])
        sig = crypto.sig_from_text(inner["Sender-Signature"])
    except (KeyError, crypto.CryptoError) as exc:
        raise ArticleError("signature", "bad sender signature") from exc
    unsigned = Article([h for h in inner.headers if h[0].lower() != "sender-signature"], inner.body)
    msg = _sender_message(art.group, art["Author-Key"], unsigned.canonical())
    if not crypto.verify(sender, crypto.PURPOSE_INBOX_SENDER, msg, sig):
        raise ArticleError("signature", "sender signature does not verify")
    return inner, sender


# --- posting rules for ordinary articles (section 5) -------------------------

MAX_BAN_REASON = 200


def _banned_key(entry) -> bytes:
    """One entry of a manifest's ``banned`` list (UN-RFC 0004, 5.1)."""
    if not isinstance(entry, dict):
        raise ValueError("a banned entry must be an object")
    reason = entry.get("reason", "")
    if not isinstance(reason, str) or len(reason) > MAX_BAN_REASON:
        raise ValueError(f"a ban reason is at most {MAX_BAN_REASON} characters")
    return crypto.key_from_text(entry["key"])


ThreadRoot = Callable[[str], "Article | None"]


def check_permitted(art: Article, manifest: Manifest, epoch_keys: dict[int, bytes],
                    closed_before: int = 0, thread_root: ThreadRoot | None = None) -> None:
    """Raise ArticleError('permission') unless the article may be posted.

    ``thread_root`` looks up an article this node holds by Message-ID (None if it
    does not hold it yet); it is needed for comments in channels (UN-RFC 0030). An
    article that may become acceptable once its thread arrives raises
    ArticleError('later'), which a node answers as a temporary failure.
    """
    pk = art.author_key
    if manifest.type != "inbox" and pk in manifest.banned:
        raise ArticleError("permission", "banned from this group")
    if manifest.type == "inbox":
        # Anyone may write; nodes can only check the form (UN-RFC 0009, 2.4).
        if art.get("Encrypted", "").strip() not in INBOX_SCHEMES:
            raise ArticleError("permission", "inbox articles must be sealed to the owner")
        return
    if manifest.type == "closed":
        if "Encrypted" not in art:
            raise ArticleError("permission", "closed group requires encryption")
        epoch = encryption_epoch(art)
        current = max(epoch_keys) if epoch_keys else 0
        if epoch not in epoch_keys or epoch < current - 1:
            raise ArticleError("permission", "unknown or expired epoch")
        if epoch < closed_before:
            raise ArticleError("permission", "that epoch was closed when a member was removed")
        if not verify_member_signature(art, epoch_keys[epoch]):
            raise ArticleError("permission", "bad Member-Signature")
        return
    if "Encrypted" in art:
        raise ArticleError("permission", "encryption only allowed in closed groups")
    kind = message_kind(art)                               # UN-RFC 0028, section 5
    if kind == KIND_REACTION:                              # UN-RFC 0048 section 6.1
        _check_reaction(art, manifest, thread_root)
        return
    if art.control is None and kind not in manifest.kinds:
        raise ArticleError("permission", "this group takes " + " and ".join(
            {"chat": "chat lines", "post": "posts with a subject"}[k] for k in manifest.kinds)
            + f", not a {'chat line' if kind == KIND_CHAT else 'post with a subject'}")
    if manifest.can_post_directly(pk):
        return
    if manifest.type == "moderated" and has_valid_approval(art, manifest):
        return
    if manifest.type == "channel" and manifest.comments == COMMENTS_OPEN and art.control is None:
        _check_comment(art, manifest, thread_root)
        return
    raise ArticleError("permission", f"not allowed to post in {manifest.type} group")


def _check_reaction(art: Article, manifest: Manifest, thread_root: ThreadRoot | None) -> None:
    """UN-RFC 0048 section 6.1: well formed, an emoji the group takes, and an ordinary
    article of this group that the node holds. Not a comment: channels take it
    whatever ``comments`` says, moderated groups without the queue."""
    from .reactions import check_form, is_reaction, reaction_set, target
    e = check_form(art)
    if not reaction_set(manifest.raw).takes(e):
        raise ArticleError("permission", "this group does not take that reaction")
    tgt = thread_root(target(art)) if thread_root is not None else None
    if tgt is None:
        raise ArticleError("later", "the article reacted to is not on this node yet")
    if tgt.group != art.group or tgt.control is not None or is_reaction(tgt):
        raise ArticleError("permission", "a reaction is to an ordinary article in this group")
    if manifest.type == "channel" and manifest.comment_days is not None:   # section 4.4
        root_id = (art.get("References") or "").split()[0]
        root = tgt if root_id == tgt.message_id else thread_root(root_id)
        if root is not None and parse_date(art["Date"]) > (
                parse_date(root["Date"]) + timedelta(days=manifest.comment_days)):
            raise ArticleError("permission", "reactions on this thread have closed")


def _check_comment(art: Article, manifest: Manifest, thread_root: ThreadRoot | None) -> None:
    """UN-RFC 0030 section 4: a reply to a thread a starter began."""
    refs = art.get("References", "").split()
    if not refs:
        raise ArticleError("permission", "only the channel's posters start threads; "
                                         "you may comment on one")
    root = thread_root(refs[0]) if thread_root is not None else None
    if root is None:
        raise ArticleError("later", "the thread is not on this node yet")
    if root.group != art.group or root.control is not None or root.get("References", "").strip():
        raise ArticleError("permission", "not a comment on a thread in this channel")
    if manifest.comment_days is not None:
        limit = parse_date(root["Date"]) + timedelta(days=manifest.comment_days)
        if parse_date(art["Date"]) > limit:
            raise ArticleError("permission", "comments on this thread have closed")
