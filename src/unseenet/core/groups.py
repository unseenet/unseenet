"""Groups, manifests, closed-group encryption and posting rules (UN-RFC 0004)."""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field

from . import crypto
from .article import Article, ArticleError, new_article
from .encoding import DS, H, b32, b64, b64decode

GROUP_TYPES = ("open", "moderated", "channel", "closed", "inbox")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+_-]*(\.[a-z0-9][a-z0-9+_-]*)*$")
_FP_RE = re.compile(r"^[a-z2-7]{16}$")
ENC_SCHEME = "xchacha20poly1305"
INBOX_SCHEME = "sealedbox"
INBOX_NAME = "inbox"            # personal inbox: inbox@<fp> (UN-RFC 0009, 2.2)


# --- group IDs (section 1) -------------------------------------------------

def make_group_id(name: str, owner_pk: bytes) -> str:
    if not _NAME_RE.match(name) or len(name) > 128:
        raise ValueError(f"invalid group name {name!r}")
    return f"{name}@{crypto.fingerprint(owner_pk)}"


def split_group_id(group_id: str) -> tuple[str, str]:
    name, at, fp = group_id.rpartition("@")
    if not at or not _NAME_RE.match(name) or len(name) > 128 or not _FP_RE.match(fp):
        raise ValueError(f"invalid group ID {group_id!r}")
    return name, fp


def short_group_id(group_id: str) -> str:
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
    view: str = "threads"                # UN-RFC 0008
    low_latency: bool = False            # UN-RFC 0008
    banned: list[bytes] = field(default_factory=list)   # UN-RFC 0004, 5.1
    message_id: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_article(cls, art: Article) -> "Manifest":
        """Validate a manifest article (section 4, steps 1-3)."""
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
                low_latency=data.get("low_latency") is True,
                banned=[_banned_key(b) for b in data.get("banned", [])],
                message_id=art.message_id, raw=data,
            )
        except (KeyError, TypeError, ValueError, crypto.CryptoError) as exc:
            raise ArticleError("syntax", f"bad manifest: {exc}") from exc
        if data.get("v") != 1 or m.name != name or m.type not in GROUP_TYPES or m.serial < 1:
            raise ArticleError("syntax", "bad manifest fields")
        if crypto.fingerprint(owner) != fp or owner != art.author_key:
            raise ArticleError("permission", "manifest not signed by group owner")
        return m

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


def make_manifest(owner: crypto.Identity, name: str, gtype: str, *, serial: int = 1,
                  title: str = "", description: str = "", moderators=(), posters=(),
                  min_pow: int = 0, retention_days: int = 90, sealed: str | None = None,
                  local: bool = False, submissions: str | None = None,
                  rules: str = "", view: str | None = None, low_latency: bool = False,
                  pow_bits: int = 18) -> Article:
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
    if view:
        data["view"] = view
    if low_latency:
        data["low_latency"] = True
    return manifest_article(owner, group_id, data, pow_bits)


MAX_RULES = 8192
VIEWS = ("threads", "chat", "data")      # UN-RFC 0008 section 3.1


def manifest_article(owner: crypto.Identity, group_id: str, data: dict, pow_bits: int = 18) -> Article:
    """Sign a manifest from its JSON fields (used for new and updated manifests)."""
    if len(data.get("rules", "")) > MAX_RULES:
        raise ValueError(f"rules are limited to {MAX_RULES} characters")
    if data.get("view", "threads") not in VIEWS:
        raise ValueError("view must be one of " + ", ".join(VIEWS))
    art = new_article(group_id, None, canonical_json(data),
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
    epoch, _, envelopes = parse_key_update(art)
    box = envelopes.get(envelope_tag(art.group, epoch, me.public_key))
    if box is None:
        return None
    return epoch, crypto.GroupKeys(me.open_sealed(b64decode(box)))


def _aad(group_id: str, epoch: int) -> bytes:
    return group_id.encode() + b"\x00" + str(epoch).encode()


def encrypted_article(group_id: str, epoch: int, keys: crypto.GroupKeys, author: crypto.Identity,
                      *, from_name: str, subject: str, body: str,
                      references: list[str] | None = None, pow_bits: int = 18) -> Article:
    inner = Article([("From", from_name), ("Subject", subject),
                     ("Content-Type", "text/plain; charset=utf-8")], body)
    blob = crypto.aead_encrypt(keys.enc_key, inner.to_bytes(), _aad(group_id, epoch))
    outer_body = "\n".join(textwrap.wrap(b64(blob), 76)) + "\n"
    art = new_article(group_id, None, outer_body, references=references,
                      extra=[("Encrypted", f"{ENC_SCHEME}; epoch={epoch}")])
    return art.finalize(author, pow_bits, member=keys.member)


def encryption_epoch(art: Article) -> int:
    m = re.match(rf"^{ENC_SCHEME};\s*epoch=(\d+)$", art.get("Encrypted", "").strip())
    if not m:
        raise ArticleError("syntax", "unsupported Encrypted header")
    return int(m.group(1))


def decrypt_article(art: Article, keys: crypto.GroupKeys) -> Article:
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

# UN-RFC 0028: a private message is a chat or a letter; without the header, a letter.
KIND_CHAT, KIND_LETTER = "chat", "letter"
MESSAGE_KINDS = (KIND_CHAT, KIND_LETTER)


def message_kind(inner: Article) -> str:
    """The kind of an inner inbox article (UN-RFC 0028 section 2)."""
    value = inner.get("Message-Kind", "").strip().lower()
    return KIND_CHAT if value == KIND_CHAT else KIND_LETTER


def personal_inbox_id(pk: bytes) -> str:
    return make_group_id(INBOX_NAME, pk)


def _sender_message(group_id: str, outer_key_text: str, inner_canonical: bytes) -> bytes:
    return (group_id.encode() + b"\x00" + outer_key_text.encode() + b"\x00" + inner_canonical)


def inbox_article(group_id: str, owner_pk: bytes, *, from_name: str, subject: str, body: str,
                  sender: crypto.Identity | None = None, reply_inbox: str | None = None,
                  references: list[str] | None = None, content_type: str | None = None,
                  kind: str = KIND_LETTER, pow_bits: int = 18) -> Article:
    """An article sealed to the inbox owner, signed by a one-time key (UN-RFC 0009, 2.3).

    ``kind`` is a chat or a letter (UN-RFC 0028); it travels inside the sealed box.
    """
    if crypto.fingerprint(owner_pk) != split_group_id(group_id)[1]:
        raise ValueError("owner key does not match the inbox's group ID")
    if kind not in MESSAGE_KINDS:
        raise ValueError(f"unknown message kind: {kind}")
    one_time = crypto.Identity.generate()
    headers = [("From", from_name), ("Subject", "" if kind == KIND_CHAT else subject),
               ("Content-Type", content_type or "text/plain; charset=utf-8"),
               ("Message-Kind", kind)]
    if reply_inbox:
        headers.append(("Reply-Inbox", reply_inbox))
    if sender is not None:
        headers.append(("Sender-Key", sender.key_text))
    inner = Article(headers, body)
    if sender is not None:
        msg = _sender_message(group_id, one_time.key_text, inner.canonical())
        inner.set("Sender-Signature", sender.sign_text(crypto.PURPOSE_INBOX_SENDER, msg))
    box = crypto.seal_to(owner_pk, inner.to_bytes())
    outer_body = "\n".join(textwrap.wrap(b64(box), 76)) + "\n"
    art = new_article(group_id, None, outer_body, references=references,
                      extra=[("Encrypted", INBOX_SCHEME)])
    return art.finalize(one_time, pow_bits)


def open_inbox_article(art: Article, owner: crypto.Identity) -> tuple[Article, bytes | None]:
    """Decrypt an inbox article. Returns (inner article, verified sender key or None).

    Raises ArticleError if it cannot be opened or a claimed sender does not verify.
    """
    if art.get("Encrypted", "").strip() != INBOX_SCHEME:
        raise ArticleError("syntax", "not an inbox article")
    try:
        blob = crypto.open_sealed_with(owner, b64decode("".join(art.body.split())))
    except (crypto.CryptoError, ValueError) as exc:
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


def check_permitted(art: Article, manifest: Manifest, epoch_keys: dict[int, bytes],
                    closed_before: int = 0) -> None:
    """Raise ArticleError('permission') unless the article may be posted."""
    pk = art.author_key
    if manifest.type != "inbox" and pk in manifest.banned:
        raise ArticleError("permission", "banned from this group")
    if manifest.type == "inbox":
        # Anyone may write; nodes can only check the form (UN-RFC 0009, 2.4).
        if art.get("Encrypted", "").strip() != INBOX_SCHEME:
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
    if manifest.can_post_directly(pk):
        return
    if manifest.type == "moderated" and has_valid_approval(art, manifest):
        return
    raise ArticleError("permission", f"not allowed to post in {manifest.type} group")
