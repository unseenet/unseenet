"""Session: your own rules for your feed and groups (#615) - what they are, what is seen,
the threads you watch or ignore, and the feed and groups as the rules have them.

**Each user decides.** The rules are the user's own text in their state (UN-RFC 0044
section 4.5); nothing here applies rules the user did not write or choose, and without
rules the feed is newest first and threads are as they are. The language and the
scoring are in ``client/scoring.py``, shared by every client.

Belongs here: reading and writing the rules, seen marks per group, watched and ignored
threads, the facts a rule looks at (``post_facts``, ``scoring_context``), and the
timeline and a group's threads scored (``scored_timeline``, ``scored_threads``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import *  # noqa: F403  - the shared names: SessionError, Message, ...
from .. import scoring as sc
from ...core import state as st


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RulesMixin:
    # --- the rules themselves ---
    def feed_rules(self) -> str:
        """Your rules as you wrote them ("" when you have none)."""
        return self.data.get("feed_rules", "")

    def check_feed_rules(self, text: str) -> sc.RuleSet:
        """The rules parsed, with a Problem for each line that would not be used; changes
        nothing."""
        return sc.parse(text)

    def set_feed_rules(self, text: str) -> sc.RuleSet:
        """Keep ``text`` as your rules (they follow your identity, UN-RFC 0044 4.5) and
        return them parsed; "" removes them, so everything is as before. Lines that
        cannot be used are kept as written and skipped. SessionError when longer than
        2048 bytes."""
        text = text.replace("\r\n", "\n")
        if len(text.encode()) > st.MAX_RULES:
            raise SessionError(f"your rules are more than {st.MAX_RULES} bytes")
        if text.strip():
            self.data["feed_rules"] = text
        else:
            self.data.pop("feed_rules", None)
        self.save()
        return self.rule_set()

    def rules_on(self) -> bool:
        """Whether your rules are used (they can be turned off without losing them)."""
        return not self.data.get("feed_rules_off")

    def set_rules_on(self, on: bool) -> None:
        """Use your rules, or turn them off in one action - the text stays, to turn them
        on again (UN-RFC 0051 section 3)."""
        if on:
            self.data.pop("feed_rules_off", None)
        else:
            self.data["feed_rules_off"] = True
        self.save()

    def rule_set(self) -> sc.RuleSet:
        """Your rules, parsed (kept until they change); none while they are turned off."""
        if not self.rules_on():
            return sc.RuleSet()
        text = self.feed_rules()
        cached = getattr(self, "_rule_cache", None)
        if cached is None or cached[0] != text:
            self._rule_cache = (text, sc.parse(text))
        return self._rule_cache[1]

    # --- seen: shown on screen, not opened (section 4.5) ---
    def seen_to(self, group_id: str) -> str:
        """The date up to which everything in a group has been seen ("" when nothing)."""
        return self.data.get("seen_to", {}).get(group_id, "")

    def mark_seen(self, group_id: str, until: datetime, save: bool = True) -> None:
        """Everything in a group dated up to ``until`` has been seen; never moves back."""
        marks = self.data.setdefault("seen_to", {})
        iso = _iso(until)
        if iso > marks.get(group_id, ""):
            marks[group_id] = iso
            if save:
                self.save()

    def is_seen(self, msg: Message) -> bool:
        """Whether a post has been seen (or read, which is more)."""
        to = self.seen_to(msg.group)
        return bool(msg.date and to and _iso(msg.date) <= to) or self.is_read(msg)

    # --- watched and ignored threads ---
    def thread_mark(self, msgid: str) -> str:
        """"watched", "ignored" or "" for the thread that starts with ``msgid``."""
        return self.data.get("threads", {}).get(msgid, "")

    def set_thread_mark(self, msgid: str, mark: str) -> None:
        """Watch a thread, ignore it, or neither ("") - kept in your state, so every
        device knows. At most 256 (the newest kept)."""
        if mark not in ("watched", "ignored", ""):
            raise SessionError("a thread is watched, ignored or neither")
        marks = self.data.setdefault("threads", {})
        marks.pop(msgid, None)
        if mark:
            marks[msgid] = mark
            while len(marks) > st.MAX_THREADS:
                marks.pop(next(iter(marks)))
        self.save()

    # --- what a rule looks at ---
    def _my_keys(self) -> set[str]:
        return {self.identity(n).key_text for n in self.data.get("identities", {})}

    def scoring_context(self) -> sc.Context:
        """What the rules know of you: who you follow, your contacts, who you ignore, how
        often you reacted to each author (from what has been fetched), your threads."""
        mine = self._my_keys()
        following = {p.get("key") for p in self.data.get("following", {}).get("people", {}).values()}
        reacted: dict[str, int] = {}
        for gid in list(self.data.get("subscribed", [])):
            authors = {m.message_id: m.author_key for m in self.cache.get(gid, {}).values()}
            for target, counts in self.all_reactions(gid).items():
                if mine & set(counts.by_key) and authors.get(target):
                    reacted[authors[target]] = reacted.get(authors[target], 0) + 1
        marks = self.data.get("threads", {})
        return sc.Context(
            following=frozenset(k for k in following if k),
            contacts=frozenset(self.data.get("contacts", {})),
            ignored=frozenset(self.data.get("ignored", {})),
            my_reactions=reacted,
            watched_threads=frozenset(m for m, v in marks.items() if v == "watched"),
            ignored_threads=frozenset(m for m, v in marks.items() if v == "ignored"))

    def post_facts(self, msg: Message, reactions: dict | None = None) -> sc.Post:
        """What the rules know of one post, from what has been fetched."""
        gid = msg.group
        cache = self.cache.get(gid, {}).values()
        counts = (reactions if reactions is not None else self.all_reactions(gid)).get(msg.message_id)
        mine = self._my_keys()
        root = msg.references[0] if msg.references else msg.message_id
        replies = [m for m in cache if msg.message_id in m.references]
        seen_to = self.seen_to(gid)
        return sc.Post(
            id=msg.message_id, group=gid.split("@")[0], thread=root,
            author=msg.author_key or "", author_name=self.label_of(msg.author_key) if msg.author_key else "",
            subject=msg.subject or "", text=msg.body if msg.readable else "",
            when=msg.date.timestamp() if msg.date else 0.0,
            bot=self.is_bot(msg.author_key), pictures=any(
                str(a.get("type", "")).startswith("image/") for a in msg.attachments if isinstance(a, dict)),
            seen=self.is_seen(msg), read=self.is_read(msg),
            reactions=counts.total() if counts else 0, replies=len(replies),
            new_replies=sum(1 for m in replies if m.date and (not seen_to or _iso(m.date) > seen_to)),
            reacted_by=frozenset(counts.by_key) if counts else frozenset(),
            i_reacted=bool(counts and mine & set(counts.by_key)),
            i_posted_in_thread=any(m.author_key in mine for m in cache
                                   if m.message_id == root or root in m.references),
            tags=frozenset(msg.tags) | frozenset(t for t in (self.manifest_data(gid).get("tags") or [])
                                                 if isinstance(t, str)),        # UN-RFC 0052
            labels=self._labeller_labels(msg))                                    # UN-RFC 0053

    def _labeller_labels(self, msg: Message) -> frozenset:
        """The labels of the labellers that count for this post (warnings and topics),
        not the author's or the group's own tags - for ``labelled`` (#658)."""
        got = self.post_labels(msg)
        if not got:
            return frozenset()
        out = {w["warning"] for w in got["warnings"] if any(b not in ("author", "group") for b in w["by"])}
        return frozenset(out | set(got["topics"]))

    # --- the feed and groups as your rules have them ---
    def scored_timeline(self, limit: int = 100, rules: bool = True) -> list[tuple[Message, sc.Result]]:
        """The timeline (UN-RFC 0034 section 7) as your rules have it: the entries shown,
        in their order, each with its score and why. Without rules, the timeline as it
        always is - newest first, nothing left out."""
        msgs = self.timeline(limit)
        rules = self.rule_set() if rules else None      # rules=False: Show all (0051 3)
        if not rules:
            return [(m, sc.Result()) for m in msgs]
        ctx, by_id, reactions = self.scoring_context(), {m.message_id: m for m in msgs}, {}
        facts = []
        for m in msgs:
            if m.group not in reactions:
                reactions[m.group] = self.all_reactions(m.group)
            facts.append(self.post_facts(m, reactions[m.group]))
        return [(by_id[p.id], r) for p, r in sc.feed(rules, facts, ctx)]

    def scored_threads(self, group_id: str, rules: bool = True) -> list[tuple[Message, int, sc.Result]]:
        """A threaded group's rows ``(message, depth, result)`` as your rules have them:
        threads in the order of a ``sort by``, threads whose every post is hidden left
        out; inside a thread the rows keep their order, and each result says whether to
        fold, dim, highlight or mark read. Without rules, the rows as ``threads`` gives
        them."""
        rows = self.threads(group_id)
        rules = self.rule_set() if rules else None      # rules=False: Show all (0051 3)
        if not rules:
            return [(m, d, sc.Result()) for m, d in rows]
        groups: list[list[tuple[Message, int]]] = []
        for m, d in rows:
            if d == 0 or not groups:
                groups.append([])
            groups[-1].append((m, d))
        ctx, reactions = self.scoring_context(), self.all_reactions(group_id)
        depth = {m.message_id: d for g in groups for m, d in g}
        by_id = {m.message_id: m for g in groups for m, _ in g}
        facts = [[self.post_facts(m, reactions) for m, _ in g] for g in groups]
        out = []
        for _, posts in sc.threads(rules, facts, ctx, group_id.split("@")[0]):
            out += [(by_id[p.id], depth[p.id], r) for p, r in posts]
        return out
