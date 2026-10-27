```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0051                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0034, 0044

          Unseenet: Your Own Rules for Your Feed and Your Groups
```

# Abstract

Usenet readers let each reader decide what to see first and what not
to see at all, with scorefiles and killfiles in slrn, Gnus and tin. The
large platforms took that decision away and gave it to an algorithm
nobody can read. This document gives it back. A user may write rules,
in a small declarative language, that score the posts of their feed and
of their discussion groups, and so decide what is shown, in what order,
and what is folded, dimmed, highlighted or marked read. The rules are
the user's own: they run only in the user's client, they travel only
inside the user's encrypted state (UN-RFC 0044), and without them
nothing changes - the feed is newest first and threads are as they are.

# 1. Motivation

UN-RFC 0034 section 7 decided that the timeline is newest first and
that nothing reorders it: nobody else decides what you see. That stays
true. But "nobody else" should not mean "nobody": a person who follows
two hundred feeds may well want their friends first, a talkative bot
further down, and a subject they are tired of out of the way. Usenet
solved this forty years ago by letting the reader write the rules.

Rules written by the reader have properties no platform's ranking has:
they can be read, they can be changed in one line, they can be turned
off, they explain themselves, and they are the same on every device
because they go with the identity.

# 2. Terms

- **Rules**, a **rule set**: the text a user writes, in the language of
  section 4.
- **Score**: a whole number a rule set gives a post; 0 without rules.
- **Feed**: the timeline of UN-RFC 0034 section 7.
- **Threaded group**: a group shown as threads (UN-RFC 0008 section 5).
- **Seen**: shown on the screen, without being opened; between unread
  and read (UN-RFC 0044 section 4.5).
- **For you**: the list of replies to the user and posts that name the
  user, from all the groups they follow, with their mention notices
  (UN-RFC 0032).

The key words MUST, MUST NOT, SHOULD and MAY are as in RFC 2119.

# 3. Each User Decides

This section is the reason for the rest of the document.

1. Rules MUST run only in the user's client. A node, a group owner, a
   gateway or the project MUST NOT see the rules, run them, or learn
   their result. A client MUST NOT send the rules or the scores
   anywhere but into the user's own encrypted state (section 8).
2. Without rules a client MUST show the feed newest first and threaded
   groups as they are, exactly as it would without this document.
3. A client MUST NOT apply rules the user did not write or choose.
   A client MAY create and suggest a standard rule set - at first
   start, or in the feed's settings - but only as an offer: the rules
   are shown in full as plain text before they are taken, they can be
   edited, and declining leaves everything as without rules.
4. Turning the rules off MUST take one action, and MUST leave the user's
   text in place so it can be turned on again.
5. A rule set someone else shares (section 9) MUST NOT be used until the
   user chooses it.
6. A client MUST offer, for any post, why it is where it is: which lines
   gave which points and what followed (section 10).
7. Wherever the rules act - the feed, a threaded group, For you - a
   client MUST offer **Show all**: one action that shows that view as
   without rules, and one action back. It is a view state only: it is
   not saved in the state, not synced to other devices, and does not
   turn the rules off (item 4). It ends when the user leaves the view
   or closes the client, and the client shows plainly while it is on.
   A user can so look past their own rules for a moment without
   changing them.

# 4. The Language

## 4.1 Lines

A rule set is UTF-8 text, one rule per line. Blank lines are ignored.

`#` starts a comment, on a line of its own or after a rule, and the
comment runs to the end of the line; inside double quotes `#` is an
ordinary character. Comments let a user say why a rule is there, and
take a rule out for a while by putting `#` in front of it.

Keywords are case-insensitive, and so is matching (section 4.6): `IF`,
`If` and `if` are the same, and `"Politik"` finds "politik".

## 4.2 Version

The first line that is not blank or a comment MAY be `version N`. It
says which version of this language the rules are written for. Without
it, version 1 is meant. This document is version 1.

## 4.3 Scopes

A line `[name]` starts a scope; the rules after it apply only there:

| Scope | Applies to |
|-------|------------|
| (none, or `[all]`) | the feed and threaded groups |
| `[feed]` | the feed |
| `[groups]` | threaded groups |
| `[foryou]` | For you (section 5.5) |
| `[pattern]` | posts in groups whose name matches the wildmat, e.g. `[dk.*]` |

A pattern matches the group's name without its `@` fingerprint, with
`*` for any characters, in any case. Only `[foryou]` rules act on For
you; rules without a scope, `[all]`, `[feed]`, `[groups]` and patterns
never do. Chats (UN-RFC 0028) are never
scored; a client offers a plain mute for them instead.

## 4.4 Rules

```
+10 if author in following
-30 if seen
+2  per time I reacted to author  max 20
+5  per contact who reacted  max 25  if group is dk.*
show if score >= 0
fold if score < -20
sort by score, then date
```

A rule is one of:

- **Points**: `+N` or `-N`, then `per COUNT` and/or `if CONDITION`,
  and optionally `max M`. With `per`, the points are multiplied by the
  count; `max` caps the result at plus or minus M. A points rule needs
  `per` or `if` or both.
- **An action**: `show`, `hide`, `fold`, `dim`, `highlight`,
  `mark read` or `quiet`, then `if CONDITION`.
- **The order**: `sort by KEY [ascending] [, then KEY [ascending]] ...`.

## 4.5 Counts

| Count | What it counts |
|-------|----------------|
| `time I reacted to author` | your reactions to the author's posts, in what the client has |
| `contact who reacted` | your contacts among those who reacted to the post |
| `followed who reacted` | the people you follow among them |
| `reaction` | keys that reacted (a reaction from the author never counts, UN-RFC 0048 3.3) |
| `reply` | replies to the post |
| `new reply since seen` | replies dated after the group's seen mark |
| `day old`, `hour old` | the post's age, in whole days or hours |

A plural is the same count (`contacts who reacted`, `days old`).

## 4.6 Conditions

| Condition | True when |
|-----------|-----------|
| `author in following` / `contacts` / `ignored` | the author's key is in that list of yours |
| `author is "TEXT"` | the author's name or key is TEXT |
| `from a bot` | the author's profile says it posts automatically (UN-RFC 0030 6) |
| `I posted in thread` | you wrote the thread's first post or a reply in it |
| `I reacted` | you reacted to the post |
| `thread in watched` / `ignored` | you watch or ignore the thread (UN-RFC 0044 4.5) |
| `seen`, `read` | the post is seen, or read |
| `for you is reply` / `mention` | in For you: it answers one of your posts, or names you (UN-RFC 0032) |
| `new replies since seen` | it has replies dated after the seen mark |
| `subject matches "TEXT"`, `text matches "TEXT"` | the subject or the text contains TEXT |
| `has pictures` | it carries a picture (UN-RFC 0027) |
| `group is PATTERN` | the group's name matches the wildmat |
| `older than N UNIT`, `newer than N UNIT` | its age, UNIT minutes, hours, days or weeks |
| `score OP N`, `reactions OP N`, `replies OP N`, `new replies OP N` | the comparison holds |

`OP` is `>=`, `<=`, `>`, `<`, `=` or `!=`. Conditions combine with
`and`, `or`, `not` and parentheses; `not` binds tightest, then `and`,
then `or`.

`matches` looks for TEXT as part of the field, in any case. It is never
a regular expression, so no rule can make a client work for long.

## 4.7 Grammar

In ABNF (RFC 5234), on a line after its comment is removed and with
keywords in any case:

```
line       = version / scope / rule
version    = "version" 1*WSP 1*DIGIT
scope      = "[" 1*(VCHAR / WSP) "]"
rule       = points / action / order
points     = sign 1*DIGIT [per] [cap] [if-cond]     ; per or if-cond, or both
sign       = "+" / "-"
per        = "per" count
cap        = "max" 1*DIGIT
if-cond    = "if" cond
action     = ("show" / "hide" / "fold" / "dim" / "highlight" / "mark read"
              / "quiet") if-cond
order      = "sort by" key *(("," / "then") key)
key        = ("score" / "date" / "reactions" / "replies") ["ascending"]
cond       = and-cond *("or" and-cond)
and-cond   = not-cond *("and" not-cond)
not-cond   = "not" not-cond / atom
atom       = "(" cond ")" / test                     ; the tests of section 4.6
```

Words are separated by white space; `,`, `(`, `)` and the operators need
none.

# 5. Using the Rules

## 5.1 One Post

For one post, where it is shown (the feed or a threaded group), only
the rules of the scopes that apply are used, in the order written:

1. Each points rule whose condition holds adds its points. `score` in a
   points rule's condition is the score so far.
2. Then each action rule is tested, with `score` the final score. A post
   is hidden when `hide` holds, or when there are `show` rules and none
   of them holds.

A rule whose test cannot be made - a count the client does not have -
is skipped for that post; it never makes the post or the list fail.

## 5.2 The Feed

The feed is the posts shown, ordered by the last `sort by` that applies
to it; without one, newest first, as always. Ties keep the order they
had. `fold`, `dim`, `highlight` and `mark read` are for threaded groups
and MUST NOT be used in the `[feed]` scope, and `quiet` is only for
`[foryou]` (section 6).

## 5.3 Threaded Groups

A thread's order is the conversation, so replies are never reordered:

- A **thread's score** is the highest score among its posts. A `sort by`
  that applies to the group orders the threads by it (with `date` the
  newest post in the thread, `reactions` their sum and `replies` the
  number of replies); without one, threads stay in the order the client
  shows them.
- A thread is left out when every post in it is hidden.
- **Inside a thread** the posts keep their order and their places in
  the tree. Scores only change how they are shown: `fold` (shown
  closed, with its replies), `dim`, `highlight` and `mark read`. A
  hidden reply is not shown, and its replies are shown where they are.

## 5.4 Quick Actions

Clients SHOULD offer the actions Usenet readers mostly used, kept
either as marks in the state or as rules the user can see:

- watch thread and ignore thread (`threads` in UN-RFC 0044 4.5);
- hide this author in this group (a rule in the group's scope);
- fold this subthread (a view state, not kept).

## 5.5 For you

For you is not a feed: it lists what is addressed to the user, newest
first, and a client SHOULD say so under its heading ("replies to you
and posts that name you"). So:

- **Seen never removes an entry.** An entry is *unseen* until it has
  been on the screen in For you or is seen in its own group (that
  group's seen mark); *seen* entries are no longer counted and give no
  notification, but stay listed as unread until they are *read* -
  opened, here or in their group, since read is one state per post.
  An entry leaves For you only when its post expires. For you's own
  seen mark is kept like a group's, under `for-you:` (UN-RFC 0044
  section 4.5).
- **Only `[foryou]` rules act here** (section 4.3). A post hidden in its
  group by the user's rules still reaches For you when it answers or
  names them, unless a `[foryou]` rule says otherwise.
- **The rules decide what happens to an entry.** `hide`: not listed,
  not counted, no notification. `quiet`: listed, but not counted and no
  notification. `show`, `highlight`, `dim` and `sort by` as in the
  feed. `fold` and `mark read` MUST NOT be used here (section 6).
- Without `[foryou]` rules, For you is newest first and notifies as it
  does without this document.

```
[foryou]
quiet if from a bot
hide  if for you is mention and not author in contacts and older than 1 week
highlight if author in contacts
```

# 6. Lines That Cannot Be Used

A line that cannot be understood is skipped, and the client says which
line and what was not understood, with a suggestion when a word is
close to a known one (`line 1: 'autor' is not a condition - did you mean
'author'?`). The other lines are used as if it were not there. So
is an action used where it does not belong: `fold`, `dim`, `highlight`
or `mark read` in `[feed]`, `fold` or `mark read` in `[foryou]`, and
`quiet` anywhere but `[foryou]`.

A client MUST keep the user's text as written, the lines it cannot use
included, when it writes the rules back: a newer client's rules, or a
rule the user is still writing, survive an older client. When the
rules say a version newer than the client knows, the message says so.

# 7. Limits

- A rule set is at most 2048 bytes in UTF-8, and at most 64 rules;
  lines past either are not used.
- Points, counts' caps and numbers are at most 10000.
- No loops, no variables, no network access, no code.

# 8. Where the Rules Live

In the user's state, as `settings.feed_rules` (UN-RFC 0044 section 4.5),
so they follow the identity to every device and only its holder can
read them. Between devices the newer change wins.

# 9. Sharing Rule Sets

A rule set is plain text, so it can be posted in a group, sent in a
private post or put on a site like any text. A client MAY offer to use
a rule set it shows - "Use these rules" - but only when the user
chooses to, after showing it in full, and SHOULD offer to add it to the
user's own rules rather than replace them.

# 10. Why?

For any post, a client MUST be able to show why it is where it is: each
line that gave points, with the points, each action that followed, and
the score, for example:

```
line 1: +10 if author in following  → +10
line 2: -30 if seen  → -30
line 4: dim if score < 0
score -20
```

# 11. Security and Privacy Considerations

- The rules say a lot about a person: who they care about, what they
  avoid. They never leave the client except encrypted in the state.
- The signals are what the client already has. Reactions are posts in
  their group (UN-RFC 0048), so counting who reacted asks no node for
  anything new, and the seen state is never sent anywhere but the state.
- A shared rule set cannot do anything but score: it has no network
  access and no code, and `matches` is not a regular expression, so a
  hostile rule set can at worst hide posts - which section 3 and the
  "Why?" view make visible.
- Rules are not moderation. Hiding a post hides it for you; it does not
  report it (UN-RFC 0045) or remove it for anyone else.

# 12. Rationale

- **Why not Gnus's or slrn's syntax**: those are powerful and hard to
  read. Rules a person can read aloud are rules they will dare change.
- **Why no regular expressions**: a careless or hostile pattern can make
  a client work for seconds per post. Text that is part of a field
  covers what people actually ask for.
- **Why `max`**: without a cap, one busy person or one popular post
  outweighs everything else.
- **Why threads are not reordered inside**: a reply belongs after what
  it answers. Usenet scoring never reordered a conversation either.
- **Why the rules are text, not settings**: text can be commented,
  shared, copied between devices and read in a terminal.

# 13. Open Questions

- **A suggested rule set**: what should the clients offer at first start,
  if anything? A short, commented set (friends first, seen further down)
  is the candidate.
- **More signals**: a reaction with a given emoji, a post that names you
  outside For you (UN-RFC 0032), posts from a group's moderators.

# 14. Changes to Other Documents

- **UN-RFC 0044** section 4.5: `settings.feed_rules`, `seen` and
  `threads` in the state; `seen` also for For you, under `for-you:`.
- **UN-RFC 0034** section 7: the timeline is newest first unless the
  user's own rules say otherwise.
- **UN-RFC 0000** section 6: 0051 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
