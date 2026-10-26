"""Your own rules for your feed and your groups (#615): scorefiles, as slrn, Gnus and tin
had them, in a small declarative language. Shared by every client, like groupfilter.py.

**Each user decides.** The rules are the user's own and run only in the client: no node,
group owner or the project sees them or what they do. Without rules nothing changes -
the feed is newest first and threads are as they are. A client may *offer* a suggested
rule set as plain text; it is never applied silently.

The language, version 1 (one rule a line; keywords in any case; ``#`` starts a comment,
also after a rule, except inside quotes)::

    version 1                       # optional; the version these rules are written for
    [feed]                          # a scope: [feed], [groups] or a group pattern, [dk.*]
    +10 if author in following      # points, if a condition holds
    +2  per time I reacted to author  max 20      # points per count, up to a cap
    -30 if seen
    show if score >= 0              # what is shown, folded, dimmed, highlighted
    sort by score, then date        # the order of the feed, and of threads in a group

Inside a thread replies are never reordered: a thread's score is the highest of its
posts', and only decides which threads come first, or whether one is hidden.

A line that cannot be understood is skipped with a warning (line number and what was
not understood, with a suggestion); the rest still work, and nothing ever breaks the
timeline. No loops, no network, no code: ``matches`` looks for a piece of text, never a
regular expression, so no rule can make a client hang.
"""
from __future__ import annotations

import difflib
import fnmatch
import re
import time
from dataclasses import dataclass, field
from typing import Callable

VERSION = 1
MAX_BYTES = 2048                 # the rules as kept in the state (UN-RFC 0044)
MAX_RULES = 64
MAX_POINTS = 10_000              # a rule's points and caps stay within this

# What every client shows in its editor when you have no rules, so you see what rules
# look like (UN-RFC 0051 section 3): a suggestion, yours only when you save it, never
# applied by itself. One text, so every client offers the same.
SUGGESTION = """# Your own rules - they run only here, and go with your identity.
# Lines starting with # are comments; a # in front of a rule takes it out.
# Without rules the feed is newest first and threads are as they are.

[feed]
+10 if author in following           # people I follow first
+2  per time I reacted to author  max 20
-30 if seen                          # what I have scrolled past, further down
+15 if new replies since seen
sort by score, then date

[groups]
+20 if I posted in thread
hide if thread in ignored
"""

LISTS = ("following", "contacts", "ignored")
THREAD_LISTS = ("watched", "ignored")
COUNTERS = {
    "time i reacted to author": "my_reactions_to_author",
    "contact who reacted": "contacts_reacted",
    "followed who reacted": "followed_reacted",
    "reaction": "reactions",
    "reply": "replies",
    "new reply since seen": "new_replies",
    "day old": "days_old",
    "hour old": "hours_old",
}
ACTIONS = ("show", "hide", "fold", "dim", "highlight", "mark read")
THREAD_ONLY = ("fold", "dim", "highlight", "mark read")
SORT_KEYS = ("score", "date", "reactions", "replies")
UNITS = {"minute": 60, "hour": 3600, "day": 86400, "week": 7 * 86400}
NUMBERS = ("score", "reactions", "replies", "new replies")
OPS = (">=", "<=", "!=", ">", "<", "=")
WORDS = sorted({"if", "per", "max", "and", "or", "not", "author", "in", "is", "from", "a",
                "bot", "i", "posted", "thread", "reacted", "seen", "read", "new", "replies",
                "since", "subject", "text", "matches", "has", "pictures", "group", "older",
                "newer", "than", "show", "hide", "fold", "dim", "highlight", "mark", "sort",
                "by", "then", "ascending", "version", *LISTS, *THREAD_LISTS, *SORT_KEYS,
                "minutes", "hours", "days", "weeks", "minute", "hour", "day", "week", "time",
                "to", "contact", "who", "followed", "reaction", "reply", "old"})


# ----------------------------------------------------------------------------------
# What a rule looks at
# ----------------------------------------------------------------------------------

@dataclass
class Post:
    """What the client knows of one post, for the rules (filled in by the Session)."""
    id: str
    group: str = ""                          # the group's name, e.g. dk.snak
    thread: str = ""                         # the thread's first post ("" for itself)
    author: str = ""                         # the author's key text
    author_name: str = ""
    subject: str = ""
    text: str = ""
    when: float = 0.0                        # posted, seconds since the epoch
    bot: bool = False
    pictures: bool = False
    seen: bool = False
    read: bool = False
    reactions: int = 0                       # self-reactions do not count (UN-RFC 0048)
    replies: int = 0
    new_replies: int = 0                     # since it was seen
    reacted_by: frozenset = frozenset()      # keys that reacted
    i_reacted: bool = False
    i_posted_in_thread: bool = False


@dataclass
class Context:
    """What the rules know of you: who you follow, your contacts, who you ignore, how
    often you reacted to each author, and the threads you watch or ignore."""
    following: frozenset = frozenset()
    contacts: frozenset = frozenset()
    ignored: frozenset = frozenset()
    my_reactions: dict = field(default_factory=dict)        # author key -> count
    watched_threads: frozenset = frozenset()
    ignored_threads: frozenset = frozenset()
    now: float = field(default_factory=time.time)


def _value(name: str, p: Post, c: Context) -> int:
    if name == "my_reactions_to_author":
        return int(c.my_reactions.get(p.author, 0))
    if name == "contacts_reacted":
        return len(p.reacted_by & c.contacts)
    if name == "followed_reacted":
        return len(p.reacted_by & c.following)
    if name == "days_old":
        return max(0, int((c.now - p.when) // 86400)) if p.when else 0
    if name == "hours_old":
        return max(0, int((c.now - p.when) // 3600)) if p.when else 0
    return int(getattr(p, name))


# ----------------------------------------------------------------------------------
# The rule set
# ----------------------------------------------------------------------------------

@dataclass
class Problem:
    """A line that was not used, and why."""
    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


@dataclass
class Rule:
    """One line: points (with a counter and cap), or an action, or the order."""
    line: int
    source: str                      # the line as written, without its comment
    scope: str | None                # None: everywhere; "feed", "groups" or a pattern
    points: int = 0
    counter: str | None = None
    cap: int | None = None
    cond: Callable | None = None     # (post, context, score) -> bool
    action: str | None = None        # show, hide, fold, dim, highlight, mark read
    sort: list[tuple[str, bool]] | None = None     # [(key, ascending)]


@dataclass
class RuleSet:
    """Parsed rules, with the problems of the lines that were skipped."""
    rules: list[Rule] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    version: int = VERSION

    def __bool__(self) -> bool:
        return bool(self.rules)


@dataclass
class Result:
    """What the rules make of a post: its score, whether it is shown, what is done with
    it, and why (each rule that counted, with its points)."""
    score: int = 0
    shown: bool = True
    actions: set = field(default_factory=set)
    why: list[tuple[int, int, str]] = field(default_factory=list)   # (line, points, rule)

    def explain(self) -> str:
        """The "Why?" text: which lines gave which points, and what follows."""
        lines = [f"line {ln}: {src}  → {pts:+d}" for ln, pts, src in self.why if pts]
        lines += [f"line {ln}: {src}" for ln, pts, src in self.why if not pts]
        lines.append(f"score {self.score}" + ("" if self.shown else ", hidden"))
        return "\n".join(lines)


# ----------------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------------

class _Error(Exception):
    pass


def _shown(counter: str) -> str:
    """A counter as written in the docs: "time I reacted to author"."""
    return counter.replace("time i ", "time I ")


def _strip_comment(line: str) -> str:
    out, quoted = [], False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        elif ch == "#" and not quoted:
            break
        out.append(ch)
    return "".join(out).strip()


_TOKEN = re.compile(r'"([^"]*)"|(>=|<=|!=|[<>=(),])|([+-]?\d+)|([^\s"<>=(),!]+)')


def _tokens(text: str) -> list[tuple[str, str]]:
    """("str"|"op"|"num"|"word", value); words in lower case, strings as written."""
    out, pos = [], 0
    for m in _TOKEN.finditer(text):
        if text[pos:m.start()].strip():
            raise _Error(f"cannot read {text[pos:m.start()].strip()!r}")
        pos = m.end()
        if m.group(1) is not None:
            out.append(("str", m.group(1)))
        elif m.group(2):
            out.append(("op", m.group(2)))
        elif m.group(3):
            out.append(("num", m.group(3)))
        else:
            out.append(("word", m.group(4).lower()))
    if text[pos:].strip():
        raise _Error(f"cannot read {text[pos:].strip()!r}")
    if text.count('"') % 2:
        raise _Error("a quote is not closed")
    return out


def _hint(word: str) -> str:
    if not word or word in WORDS:                  # a real word, in the wrong place
        return ""
    close = difflib.get_close_matches(word, WORDS, n=1, cutoff=0.75)
    return f" - did you mean {close[0]!r}?" if close else ""


class _Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def word(self, *ws) -> bool:
        """Take the words ``ws`` if they come next."""
        for k, w in enumerate(ws):
            if self.peek(k) != ("word", w):
                return False
        self.i += len(ws)
        return True

    def need(self, *ws):
        if not self.word(*ws):
            got = self.peek()[1]
            raise _Error(f"expected {' '.join(ws)!r}, not {got!r}" + (_hint(got) if got else "")
                         if got is not None else f"expected {' '.join(ws)!r} at the end")

    def number(self) -> int:
        kind, v = self.peek()
        if kind != "num":
            raise _Error(f"expected a number, not {v!r}" if v is not None else "expected a number")
        self.i += 1
        n = int(v)
        if abs(n) > MAX_POINTS:
            raise _Error(f"{n} is more than {MAX_POINTS}")
        return n

    def string(self) -> str:
        kind, v = self.peek()
        if kind != "str":
            raise _Error(f'expected text in quotes, e.g. "politik", not {v!r}')
        self.i += 1
        return v.casefold()

    def done(self) -> bool:
        return self.i >= len(self.t)

    # conditions: or > and > not > atom
    def cond(self):
        left = self.cond_and()
        while self.word("or"):
            right = self.cond_and()
            left = (lambda a, b: lambda p, c, s: a(p, c, s) or b(p, c, s))(left, right)
        return left

    def cond_and(self):
        left = self.cond_not()
        while self.word("and"):
            right = self.cond_not()
            left = (lambda a, b: lambda p, c, s: a(p, c, s) and b(p, c, s))(left, right)
        return left

    def cond_not(self):
        if self.word("not"):
            inner = self.cond_not()
            return lambda p, c, s: not inner(p, c, s)
        return self.atom()

    def atom(self):
        if self.peek() == ("op", "("):
            self.i += 1
            inner = self.cond()
            if self.peek() != ("op", ")"):
                raise _Error("a parenthesis is not closed")
            self.i += 1
            return inner
        if self.word("author", "in"):
            kind, which = self.peek()
            if which not in LISTS:
                raise _Error(f"author in {' | '.join(LISTS)}, not {which!r}" + (_hint(which) if which else ""))
            self.i += 1
            return lambda p, c, s: p.author in getattr(c, which)
        if self.word("author", "is"):
            who = self.string()
            return lambda p, c, s: who in (p.author_name.casefold(), p.author.casefold()) or (
                len(who) >= 8 and p.author.casefold().split(":")[-1].startswith(who.split(":")[-1]))
        if self.word("from", "a", "bot"):
            return lambda p, c, s: p.bot
        if self.word("i", "posted", "in", "thread"):
            return lambda p, c, s: p.i_posted_in_thread
        if self.word("i", "reacted"):
            return lambda p, c, s: p.i_reacted
        if self.word("thread", "in"):
            kind, which = self.peek()
            if which not in THREAD_LISTS:
                raise _Error(f"thread in {' | '.join(THREAD_LISTS)}, not {which!r}")
            self.i += 1
            attr = "watched_threads" if which == "watched" else "ignored_threads"
            return lambda p, c, s: (p.thread or p.id) in getattr(c, attr)
        if self.word("new", "replies", "since", "seen"):
            return lambda p, c, s: p.new_replies > 0
        if self.word("seen"):
            return lambda p, c, s: p.seen
        if self.word("read"):
            return lambda p, c, s: p.read
        if self.word("has", "pictures"):
            return lambda p, c, s: p.pictures
        for fld in ("subject", "text"):
            if self.word(fld, "matches"):
                needle = self.string()
                return (lambda f, n: lambda p, c, s: n in getattr(p, f).casefold())(fld, needle)
        if self.word("group", "is"):
            kind, pat = self.peek()
            if kind not in ("word", "str"):
                raise _Error("group is <name or pattern>, e.g. dk.*")
            self.i += 1
            pat = pat.casefold()
            return lambda p, c, s: fnmatch.fnmatchcase(p.group.casefold(), pat)
        for word, older in (("older", True), ("newer", False)):
            if self.word(word, "than"):
                n = self.number()
                kind, unit = self.peek()
                unit = (unit or "").rstrip("s")
                if unit not in UNITS:
                    raise _Error("older than <number> minutes | hours | days | weeks")
                self.i += 1
                limit = n * UNITS[unit]
                return (lambda lim, o: lambda p, c, s: bool(p.when) and (
                    (c.now - p.when > lim) if o else (c.now - p.when < lim)))(limit, older)
        for name in NUMBERS:
            if self.word(*name.split()):
                kind, op = self.peek()
                if kind != "op" or op not in OPS:
                    raise _Error(f"{name} >= | <= | > | < | = | != <number>")
                self.i += 1
                n = self.number()
                attr = "new_replies" if name == "new replies" else name
                return (lambda a, o, n: lambda p, c, s: _compare(
                    s if a == "score" else getattr(p, a), o, n))(attr, op, n)
        got = self.peek()[1]
        raise _Error(f"{got!r} is not a condition" + (_hint(got) if got else "") if got is not None
                     else "a condition is missing")


def _compare(a: int, op: str, b: int) -> bool:
    return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b, "=": a == b, "!=": a != b}[op]


def _rule(text: str, line: int, scope: str | None) -> Rule:
    p = _Parser(_tokens(text))
    r = Rule(line, text, scope)
    kind, v = p.peek()
    if kind == "num" and (v.startswith("+") or v.startswith("-")):          # points
        r.points = p.number()
        if p.word("per"):
            phrase = []
            while not p.done() and p.peek() not in (("word", "max"), ("word", "if")):
                phrase.append(p.peek()[1])
                p.i += 1
            name = " ".join(phrase)
            if name not in COUNTERS:                   # "contacts who reacted", "days old"
                name = " ".join(w[:-1] if w.endswith("s") and len(w) > 3 else w for w in phrase)
            if name not in COUNTERS:
                close = difflib.get_close_matches(name, list(COUNTERS), n=1, cutoff=0.6)
                raise _Error(f"per {name!r}: not something to count" +
                             (f" - did you mean {_shown(close[0])!r}?" if close else
                              " (" + ", ".join(_shown(c) for c in COUNTERS) + ")"))
            r.counter = COUNTERS[name]
        if p.word("max"):
            r.cap = abs(p.number())
        if p.word("if"):
            r.cond = p.cond()
        elif r.counter is None:
            raise _Error("points need 'if <condition>' or 'per <count>'")
    elif p.word("sort", "by"):
        keys = []
        while True:
            kind, k = p.peek()
            if k not in SORT_KEYS:
                raise _Error(f"sort by {' | '.join(SORT_KEYS)}, not {k!r}" + (_hint(k) if k else ""))
            p.i += 1
            keys.append((k, p.word("ascending")))
            if not (p.peek() == ("op", ",") or p.peek() == ("word", "then")):
                break
            p.i += 1
            p.word("then")
        r.sort = keys
    else:
        for action in ACTIONS:
            if p.word(*action.split()):
                r.action = action
                p.need("if")
                r.cond = p.cond()
                break
        else:
            raise _Error((f"{v!r} does not start a rule" + (_hint(v) if kind == "word" else "")
                          if v is not None else "empty") +
                         " (a rule starts with +points, -points, show, hide, fold, dim, "
                         "highlight, mark read or sort by)")
    if not p.done():
        raise _Error(f"{p.peek()[1]!r} after the end of the rule" + _hint(p.peek()[1] or ""))
    if r.action in THREAD_ONLY and scope == "feed":
        raise _Error(f"{r.action} is for threads in groups, not the feed")
    return r


def parse(text: str) -> RuleSet:
    """Parse a rule set. Lines that cannot be used are skipped, each with a Problem;
    never raises."""
    out = RuleSet()
    if len(text.encode()) > MAX_BYTES:
        out.problems.append(Problem(0, f"the rules are more than {MAX_BYTES} bytes; "
                                       "the lines after that are not used"))
        text = text.encode()[:MAX_BYTES].decode("utf-8", "ignore")
        text = text[:text.rfind("\n")] if "\n" in text else ""
    scope: str | None = None
    for n, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw)
        if not line:
            continue
        low = line.lower()
        if low.startswith("version"):
            m = re.fullmatch(r"version\s+(\d+)", low)
            if not m:
                out.problems.append(Problem(n, "version <number>"))
            else:
                out.version = int(m.group(1))
            continue
        if line.startswith("["):
            if not line.endswith("]") or not line[1:-1].strip():
                out.problems.append(Problem(n, "a scope is [feed], [groups] or [a group pattern]"))
                continue
            name = line[1:-1].strip().lower()
            scope = None if name == "all" else name
            continue
        if len(out.rules) >= MAX_RULES:
            out.problems.append(Problem(n, f"more than {MAX_RULES} rules; not used"))
            continue
        try:
            out.rules.append(_rule(line, n, scope))
        except _Error as exc:
            msg = str(exc)
            if out.version > VERSION:
                msg += f" (written for version {out.version}; this client knows {VERSION})"
            out.problems.append(Problem(n, msg))
    return out


# ----------------------------------------------------------------------------------
# Using them
# ----------------------------------------------------------------------------------

def _applies(scope: str | None, where: str, group: str) -> bool:
    if scope is None:
        return True
    if scope in ("feed", "groups"):
        return scope == where
    return fnmatch.fnmatchcase(group.casefold(), scope)


def score(rules: RuleSet, post: Post, ctx: Context, where: str = "feed") -> Result:
    """What the rules make of one post ``where`` it is shown ("feed" or "groups")."""
    res = Result()
    mine = [r for r in rules.rules if _applies(r.scope, where, post.group)]
    for r in mine:
        if r.action or r.sort:
            continue
        try:
            if r.cond is not None and not r.cond(post, ctx, res.score):
                continue
            pts = r.points * (_value(r.counter, post, ctx) if r.counter else 1)
        except (TypeError, ValueError, AttributeError):
            continue                                   # a rule that fails is skipped
        if r.cap is not None:
            pts = max(-r.cap, min(r.cap, pts))
        if pts:
            res.score += pts
            res.why.append((r.line, pts, r.source))
    shows = [r for r in mine if r.action == "show"]
    for r in mine:
        if not r.action:
            continue
        try:
            hit = r.cond(post, ctx, res.score)
        except (TypeError, ValueError, AttributeError):
            continue
        if r.action == "show":
            continue
        if hit:
            res.actions.add(r.action)
            res.why.append((r.line, 0, r.source))
    if shows and not any(_safe(r, post, ctx, res.score) for r in shows):
        res.shown = False
        res.why.append((shows[0].line, 0, shows[0].source))
    if "hide" in res.actions:
        res.shown = False
    return res


def _safe(r: Rule, post: Post, ctx: Context, s: int) -> bool:
    try:
        return bool(r.cond(post, ctx, s))
    except (TypeError, ValueError, AttributeError):
        return True


def _sort_keys(rules: RuleSet, where: str, group: str = "") -> list[tuple[str, bool]] | None:
    keys = None
    for r in rules.rules:
        if r.sort and _applies(r.scope, where, group):
            keys = r.sort                               # the last one that applies
    return keys


def _order(entries: list[tuple[Post, Result]], keys) -> list[tuple[Post, Result]]:
    def key(e):
        p, res = e
        vals = {"score": res.score, "date": p.when, "reactions": p.reactions, "replies": p.replies}
        return tuple(vals[k] if asc else -vals[k] for k, asc in keys)
    return sorted(entries, key=key)


def feed(rules: RuleSet, posts: list[Post], ctx: Context) -> list[tuple[Post, Result]]:
    """The feed as the rules have it: the posts shown, in their order. Without rules (or
    without a ``sort by``), newest first, as always."""
    scored = [(p, score(rules, p, ctx, "feed")) for p in posts]
    shown = [e for e in scored if e[1].shown]
    keys = _sort_keys(rules, "feed") or [("date", False)]
    return _order(shown, keys)


def threads(rules: RuleSet, threads: list[list[Post]], ctx: Context, group: str = ""):
    """A threaded group as the rules have it: [(thread score, [(post, result)])], the
    threads in the order of a ``sort by`` (else as given), those whose every post is
    hidden left out. Inside a thread the posts keep their order: scores only fold, dim,
    highlight or mark them read."""
    out = []
    for posts in threads:
        scored = [(p, score(rules, p, ctx, "groups")) for p in posts]
        if not scored or not any(r.shown for _, r in scored):
            continue
        out.append((max(r.score for _, r in scored), scored))
    keys = _sort_keys(rules, "groups", group)
    if keys:
        def key(t):
            best, posts = t
            vals = {"score": best, "date": max(p.when for p, _ in posts),
                    "reactions": sum(p.reactions for p, _ in posts), "replies": len(posts) - 1}
            return tuple(vals[k] if asc else -vals[k] for k, asc in keys)
        out.sort(key=key)
    return out
