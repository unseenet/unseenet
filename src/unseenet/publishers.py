"""The publishers a stick takes updates from (UN-RFC 0062 section 6, #822).

A publisher is whoever builds and signs releases: the project, or anybody else - the
network is the protocol, not the project's code. A stick keeps a list of publishers in
``data/publishers.json``, each as its releases channel's Group ID and its first key list
(pinned when it was added), and follows one of them at a time, since builds of
different publishers are different files. The project is there from the start; a user
may add another publisher from its releases channel, after seeing its key list and its
releases, follow it, or remove any - the project too.

The choice is the stick's, not the vault's: the updater runs without the vault, and
what is installed on the stick is what follows a publisher. Switching is an update like
any other and never touches ``data/`` beyond this file.

Belongs here: the file, the project's entry, and what a releases channel shows before
it is added (``preview``). Not here: reading the channel (``Session.publisher_preview``),
checking releases against the key list (``update``, ``release_keys``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import release_keys as rk
from .known_nodes import RELEASES_GROUP

FILE = "data/publishers.json"
PROJECT_NAME = "The Unseenet project"
MAX_PUBLISHERS = 16


class PublisherProblem(ValueError):
    pass


@dataclass(frozen=True)
class Publisher:
    group: str                    # its releases channel
    first: str | None             # the body of its pinned first key list (None: the project
    name: str = ""                # before its list is pinned - the project key alone)

    @property
    def is_project(self) -> bool:
        return self.group == RELEASES_GROUP

    def first_list(self) -> rk.KeyList:
        """Where its key list's chain starts (UN-RFC 0062 section 3)."""
        if self.first:
            return rk.parse(self.first)
        if self.is_project:
            return rk.first()
        raise PublisherProblem(f"{self.group} has no key list pinned")

    @property
    def fingerprint(self) -> str:
        """A short, readable fingerprint of the pinned first key list, to compare with
        what the publisher says elsewhere."""
        body = self.first or (rk.PROJECT_FIRST or "")
        if not body:
            return "project key"
        h = hashlib.sha256(rk.list_hash(body).encode()).hexdigest()
        return "-".join(h[i:i + 4] for i in range(0, 16, 4))

    def to_dict(self) -> dict:
        return {"group": self.group, "first": self.first, "name": self.name}


PROJECT = Publisher(RELEASES_GROUP, None, PROJECT_NAME)


@dataclass
class Publishers:
    """The stick's publishers and which one it follows."""
    follow: str = RELEASES_GROUP
    known: list[Publisher] = field(default_factory=lambda: [PROJECT])

    def get(self, group: str) -> Publisher | None:
        return next((p for p in self.known if p.group == group), None)

    @property
    def followed(self) -> Publisher | None:
        """The publisher the stick follows; None when it follows none (all removed)."""
        return self.get(self.follow)

    def to_dict(self) -> dict:
        return {"v": 1, "follow": self.follow,
                "publishers": [p.to_dict() for p in self.known]}


def load(media: Path | None) -> Publishers:
    """The stick's publishers, or the project alone when there is no file (or no stick)."""
    if media is None:
        return Publishers()
    try:
        d = json.loads((Path(media) / FILE).read_text())
    except (OSError, ValueError):
        return Publishers()
    if not isinstance(d, dict) or d.get("v") != 1 or not isinstance(d.get("publishers"), list):
        return Publishers()
    known = []
    for x in d["publishers"][:MAX_PUBLISHERS]:
        try:
            p = Publisher(str(x["group"]), x.get("first"), str(x.get("name", ""))[:64])
            if p.first is not None:
                rk.parse(p.first)
            if p.group == RELEASES_GROUP and p.first is None:
                p = PROJECT
        except (KeyError, TypeError, ValueError):
            continue
        if not any(k.group == p.group for k in known):
            known.append(p)
    return Publishers(str(d.get("follow") or ""), known)


def save(media: Path, pubs: Publishers) -> None:
    path = Path(media) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(pubs.to_dict(), indent=1))
    tmp.replace(path)


def followed(media: Path | None) -> Publisher | None:
    return load(media).followed


@dataclass(frozen=True)
class Preview:
    """What a releases channel shows before a user adds it: its first key list (the one
    to pin), the key list counted from it now, and its newest releases."""
    group: str
    first: str
    keys: rk.KeyList
    fork: bool
    releases: dict                  # channel -> newest version, signed by enough keys

    @property
    def publisher(self) -> Publisher:
        return Publisher(self.group, self.first)

    @property
    def fingerprint(self) -> str:
        return self.publisher.fingerprint


def preview(group: str, items) -> Preview:
    """From the posts of a releases channel - (author key, subject, body) each, their
    signatures checked by whoever read them - the publisher it shows. Its first key list
    is the ``release-keys 1`` that one of its own keys posted; there must be exactly one."""
    from . import update
    firsts = set()
    votes = []
    for author, subject, body in items:
        if not (subject or "").startswith(rk.SUBJECT + " "):
            continue
        votes.append((author, body))
        try:
            kl = rk.parse(body)
        except rk.KeyListProblem:
            continue
        if kl.seq == 1 and author in kl.keys:
            firsts.add(kl.body)
    if not firsts:
        raise PublisherProblem("this channel holds no first key list (release-keys 1) posted "
                               "by one of its keys: it is not a publisher's releases channel")
    if len(firsts) > 1:
        raise PublisherProblem("this channel holds two different first key lists: do not "
                               "trust it until its publisher says which is theirs")
    (first,) = firsts
    keys, fork = rk.count(rk.parse(first), votes)
    releases: dict = {}
    for _, _, body in items:
        post = update.parse_release_post(body)
        if not post:
            continue
        channel, sums, sig = post
        try:
            update.check_signature(sums, sig, channel, keys)
        except update.UpdateError:
            continue
        for version in update.versions_in(update.parse_sums(sums)).values():
            have = releases.get(channel)
            if have is None or update.version_key(version) > update.version_key(have):
                releases[channel] = version
    return Preview(group, first, keys, fork, releases)


def add(media: Path, p: Preview, name: str = "", follow: bool = False) -> Publishers:
    """Pin a publisher's first key list as the preview showed it."""
    pubs = load(media)
    if pubs.get(p.group) is not None:
        raise PublisherProblem("that publisher is on the list already")
    if len(pubs.known) >= MAX_PUBLISHERS:
        raise PublisherProblem(f"at most {MAX_PUBLISHERS} publishers")
    pubs.known.append(Publisher(p.group, p.first, name.strip()[:64]))
    if follow or pubs.followed is None:
        pubs.follow = p.group
    save(media, pubs)
    return pubs


def follow(media: Path, group: str) -> Publishers:
    pubs = load(media)
    if pubs.get(group) is None:
        raise PublisherProblem("add that publisher first")
    pubs.follow = group
    save(media, pubs)
    return pubs


def remove(media: Path, group: str) -> Publishers:
    """Take a publisher off the list - the project too. The stick then follows the next
    one on the list, or none: it updates from nobody until a publisher is added."""
    pubs = load(media)
    if pubs.get(group) is None:
        raise PublisherProblem("that publisher is not on the list")
    pubs.known = [p for p in pubs.known if p.group != group]
    if pubs.follow == group:
        pubs.follow = pubs.known[0].group if pubs.known else ""
    save(media, pubs)
    return pubs
