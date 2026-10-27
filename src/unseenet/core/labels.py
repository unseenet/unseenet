"""Content labels (UN-RFC 0053): words labellers attach to posts others wrote.

A label only describes - it never sanctions. **Warnings** (the fixed set shared with
tags, UN-RFC 0052 section 4) are blurred or hidden as the reader chose; **topics** only
feed the reader's own rules (UN-RFC 0051). Nodes never act on labels (section 7).

Belongs here: a labeller's ``labels@`` channel and its manifest fields (section 3), the
form of label articles and reading them (section 4), a manifest's ``labellers`` (5),
and the book of what the labellers one reads say about posts. Not here: which
labellers count for a reader (client/session/labels.py), what a client draws.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from . import crypto
from .article import Article, parse_date
from .tags import WARNINGS, is_tag

GROUP_NAME = "labels"                  # labels@<fp>, a key-bound channel (UN-RFC 0029)
MANIFEST_MAX = 4 * 1024
MAX_ENTRIES = 1000                     # posts in one label article (section 4)
MAX_LABELS = 8                         # labels of one post in one article
NOTE_MAX = 200
POLICY_MAX = 2000
CONTACT_MAX = 512
MANIFEST_FIELDS = ("policy", "contact", "automatic", "topics")
MAX_NAMED = 16                         # ``labellers`` of a hierarchy or a group (section 5)


# The age guide's suggestions (UN-RFC 0053 section 6.1): what to do with each warning for
# who reads on this device. A client applies one as ordinary choices; the age group
# itself is never stored, sent or shown to anyone.
AGE_PROFILES = {
    "under-13": {"profanity": "hide", "sexual": "hide", "nudity": "hide", "violence": "hide",
                 "gore": "hide", "spoiler": "blur"},
    "13-17": {"profanity": "blur", "sexual": "hide", "nudity": "hide", "violence": "blur",
              "gore": "hide", "spoiler": "blur"},
    "adult": {"profanity": "blur", "sexual": "blur", "nudity": "blur", "violence": "blur",
              "gore": "blur", "spoiler": "blur"},
}
AGE_PROFILE_LABELS = {"under-13": "Under 13", "13-17": "13 to 17", "adult": "An adult"}


class LabelError(ValueError):
    """A label article, or a field, that is not as UN-RFC 0053 says."""


def labels_group(public_key: bytes) -> str:
    """``labels@<fingerprint>``: a key's label channel."""
    return f"{GROUP_NAME}@{crypto.fingerprint(public_key)}"


def is_labels_group(group_id: str) -> bool:
    return isinstance(group_id, str) and group_id.startswith(GROUP_NAME + "@")


def labeller_of(group_id: str) -> str:
    """The fingerprint after ``labels@``."""
    return group_id.partition("@")[2]


def is_warning(label: str) -> bool:
    return label in WARNINGS


def check_manifest_fields(data: dict) -> None:
    """ValueError if a ``labels@`` manifest's own fields are not as section 3 says;
    ``topics`` is for ``labels@`` only (the others are checked for ``reports@`` there)."""
    if data.get("name") != GROUP_NAME:
        if "topics" in data:
            raise ValueError("topics is for labels@ groups (UN-RFC 0053 section 3)")
        return
    p, c = data.get("policy"), data.get("contact")
    if p is not None and (not isinstance(p, str) or len(p) > POLICY_MAX):
        raise ValueError(f"policy: text, at most {POLICY_MAX} characters")
    if c is not None and (not isinstance(c, str) or len(c) > CONTACT_MAX):
        raise ValueError(f"contact: text, at most {CONTACT_MAX} characters")
    for b in ("automatic", "topics"):
        if b in data and data[b] is not True:
            raise ValueError(f"{b} is true or left out")


def check_named(data: dict, name: str = "labellers") -> None:
    """ValueError if a manifest's or a list's ``labellers`` is not 1 to 16 keys, each
    once (section 5); never in an inbox."""
    if name not in data:
        return
    if data.get("type") == "inbox":
        raise ValueError("an inbox names no labellers")
    keys = data[name]
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_NAMED:
        raise ValueError(f"{name}: 1 to {MAX_NAMED} keys")
    for k in keys:
        crypto.key_from_text(k)
    if len(set(keys)) != len(keys):
        raise ValueError("a labeller is listed twice")


def named(data: dict, name: str = "labellers") -> list[str]:
    """The labellers a manifest or a list names; [] if none or not valid."""
    try:
        check_named(data, name)
    except (ValueError, crypto.CryptoError):
        return []
    return list(data.get(name, []))


@dataclass(frozen=True)
class PostLabels:
    id: str
    group: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class LabelSet:
    """One label article: what a labeller says about some posts."""
    message_id: str
    labeller: str                      # its key
    date: datetime
    posts: tuple[PostLabels, ...]
    note: str = ""


def _labels(value) -> tuple[str, ...] | None:
    """Valid labels of an entry (each a tag word, each once, at most 8); [] is "none"."""
    if not isinstance(value, list) or len(value) > MAX_LABELS:
        return None
    if not all(isinstance(x, str) and is_tag(x) for x in value) or len(set(value)) != len(value):
        return None
    return tuple(value)


def label_body(posts, note: str = "") -> str:
    """The JSON of a label article: ``posts`` as (Message-ID, Group ID, [labels])."""
    posts = list(posts)
    if not 1 <= len(posts) <= MAX_ENTRIES:
        raise LabelError(f"1 to {MAX_ENTRIES} posts")
    out = []
    for mid, gid, labels in posts:
        if not isinstance(mid, str) or not mid.startswith("<") or not isinstance(gid, str) or "@" not in gid:
            raise LabelError(f"not a post: {mid} in {gid}")
        if gid.startswith("inbox@"):
            raise LabelError("a post in an inbox is never labelled")
        good = _labels(list(labels))
        if good is None:
            raise LabelError(f"labels of {mid}: up to {MAX_LABELS} tag words, each once")
        out.append({"id": mid, "group": gid, "labels": list(good)})
    from .groups import canonical_json       # here: groups imports this module
    data = {"v": 1, "posts": out}
    if note:
        if len(note) > NOTE_MAX:
            raise LabelError(f"note: at most {NOTE_MAX} characters")
        data["note"] = note
    return canonical_json(data)


def label_article(labeller: crypto.Identity, body: str, *, from_name: str = "Labeller",
                  pow_bits: int = 18, now: datetime | None = None) -> Article:
    """A signed label article in the labeller's ``labels@`` channel."""
    from .article import new_article
    n = len(json.loads(body).get("posts", []))
    art = new_article(labels_group(labeller.public_key), f"Labels: {n} post{'s' if n != 1 else ''}",
                      body, from_name=from_name, extra=[("Content-Type", "application/json")], now=now)
    return art.finalize(labeller, pow_bits)


def read_labels(message_id: str, group: str, author: str, date: datetime, body: str) -> LabelSet:
    """A label article from its parts. Entries not as section 4 says are left out;
    LabelError if the article as a whole is not one."""
    if not is_labels_group(group):
        raise LabelError("not in a labels@ channel")
    try:
        if crypto.fingerprint(crypto.key_from_text(author)) != labeller_of(group):
            raise LabelError("not posted by the channel's own key")
    except (crypto.CryptoError, TypeError, ValueError) as exc:
        raise LabelError("not posted by the channel's own key") from exc
    if date is None:
        raise LabelError("no Date")
    try:
        data = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise LabelError(f"not a label article: {exc}") from exc
    if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("posts"), list):
        raise LabelError("not a version 1 label article")
    if len(data["posts"]) > MAX_ENTRIES:
        raise LabelError(f"more than {MAX_ENTRIES} posts")
    posts = []
    for e in data["posts"]:
        if not isinstance(e, dict):
            continue
        mid, g, labels = e.get("id"), e.get("group"), _labels(e.get("labels"))
        if (labels is None or not isinstance(mid, str) or not mid.startswith("<")
                or not isinstance(g, str) or g.startswith("inbox@")):
            continue
        posts.append(PostLabels(mid, g, labels))
    note = data.get("note", "")
    return LabelSet(message_id, author, date, tuple(posts), note[:NOTE_MAX] if isinstance(note, str) else "")


def parse_labels(art: Article) -> LabelSet:
    """A label article, with the checks on the article itself."""
    if art.control:
        raise LabelError("a control article")
    if not (art.get("Content-Type") or "").startswith("application/json"):
        raise LabelError("a label article is application/json")
    try:
        author, date = crypto.key_to_text(art.author_key), parse_date(art["Date"])
    except (KeyError, ValueError, crypto.CryptoError) as exc:
        raise LabelError(f"not a label article: {exc}") from exc
    return read_labels(art.message_id, (art.get("Newsgroups") or "").strip(), author, date, art.body)


@dataclass
class Book:
    """What the labellers one reads say about posts. Of one labeller, its newest label
    article about a post is what counts (section 4); withdrawn articles are gone."""
    sets: dict[str, LabelSet] = field(default_factory=dict)
    _by_post: dict[str, dict[str, tuple[datetime, str, tuple[str, ...]]]] = field(default_factory=dict)

    def add(self, s: LabelSet) -> bool:
        if s.message_id in self.sets:
            return False
        self.sets[s.message_id] = s
        for p in s.posts:
            mine = self._by_post.setdefault(p.id, {})
            have = mine.get(s.labeller)
            if have is None or (s.date, s.message_id) > (have[0], have[1]):
                mine[s.labeller] = (s.date, s.message_id, p.labels)
        return True

    def labels(self, message_id: str, labellers=None) -> dict[str, tuple[str, ...]]:
        """{labeller key: its labels} for a post, of ``labellers`` (all, if None)."""
        return {k: v[2] for k, v in self._by_post.get(message_id, {}).items()
                if v[2] and (labellers is None or k in labellers)}
