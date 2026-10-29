```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0030                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.4.0, unseenet 0.6.0
Updates: 0004, 0022, 0042

                 Unseenet: Comments in Channels
```

# Abstract

A channel lets only its owner, moderators and listed posters write.
This document lets a channel owner open it for **comments**: anybody
may then reply to a thread, while only the owner, moderators and
posters may start one. It suits announcements, news, weather and other
groups filled by a person or a bot, where readers should be able to
talk about each post without the posts drowning. It also gives
automated posters a way to say that they are automated.

# 1. Motivation

UN-RFC 0004 offers a channel, where readers cannot answer, or an open
group, where anybody can start threads. Neither fits a group such as
`unseenet.announce` or a daily weather report: readers have something
to say about each post, but a thread started by somebody else is not
what the group is for. Usenet had no such group; a blog with comments
or a news site is the familiar model.

The group type is fixed at creation (UN-RFC 0004 section 2), so the
choice is a field of the channel's manifest, which the owner can change.

The rule is enforced by nodes, not by clients, so that a comment shown
on one node is accepted on all of them and a modified client cannot
start threads in somebody else's channel.

# 2. Terms

- **Thread root:** an article in a group with no `References` header.
- **Starter:** the owner, a moderator or a poster of a channel under
  its current manifest (UN-RFC 0004 sections 3.1 and 5).
- **Comment:** an article in a channel whose `Author-Key` is not a
  starter, and which this document allows.

# 3. Manifest Fields

Two optional fields are added to the manifest of a channel (UN-RFC 0004
section 3.1):

| Field          | Type    | Req. | Meaning                                         |
|----------------|---------|------|-------------------------------------------------|
| `comments`     | string  | no   | `none` (the default) or `open`                  |
| `comment_days` | integer | no   | Days after a thread root's `Date` during which comments are accepted; absent means no limit |

`comments` belongs to channels only: a node MUST reject a manifest of
a group that is not a channel if it carries `comments`, and a channel
manifest whose `comments` has any other value. `comment_days` may also
be set in open, moderated and closed groups (section 3.3); a node MUST
reject it in an inbox or local group (UN-RFC 0009), and wherever it is
not a positive integer.

The owner MAY change both fields in any later manifest. A change
applies to articles that arrive after it, as for every other posting
rule; comments already accepted stay.

## 3.1 An Entry's Own Deadline

Whoever starts a thread MAY give its root a shorter time for comments
than the group's, when writing it, with the article header:

```
Comment-Days: <n>
```

where `<n>` is a whole number of days, `0` or more. `0` means that the
entry takes no comments at all. Like every header it is covered by the
signature (UN-RFC 0002), so nobody can change it later.

- A node MUST reject a thread root whose `Comment-Days` is not a whole
  number of `0` or more, or, when the current manifest has
  `comment_days`, is larger than it. An entry's deadline is never
  later than the group's.
- A node ignores `Comment-Days` on an article that is not a thread
  root, and in a channel whose `comments` is `none`.
- In a closed group `Comment-Days` is an outer header, outside the
  encryption (UN-RFC 0004 section 6), so that nodes can read it. It tells a node
  nothing about the content.
- The deadline that applies to a thread is the **shorter** of the
  root's `Comment-Days` and the `comment_days` of the current
  manifest, both counted from the root's `Date`. An owner who later
  shortens `comment_days` therefore shortens it for every entry too;
  one who lengthens it does not lengthen an entry's own.
- An edit of the root (UN-RFC 0042) MAY carry `Comment-Days`, counted
  from the `Date` of the root that comments name. It MAY shorten the
  time, never lengthen it: a node MUST reject an edit whose
  `Comment-Days` would make the deadline later than before. Opening
  comments again is done as in section 3.2.

## 3.2 Closing and Reopening One Entry

Comments on one entry can be closed before its deadline, and opened
again, with control articles (UN-RFC 0004 section 7):

- `Control: comments-close <message-id>`
- `Control: comments-open <message-id>`

where `<message-id>` is the thread root, the **target**. Such a
**marker** has `Newsgroups:` the target's group, an empty body or a
short note for readers (at most 256 characters, such as "Closed - the
discussion went off topic"), and is never encrypted, so that nodes can
read it. It is **valid** when it is in the same group as its target,
the target is a thread root, and its `Author-Key` is the target's
author, or the owner or a moderator under the current manifest.

Markers are replaced with `Supersedes` exactly as pins are (UN-RFC
0033 section 3.1), with "owner or moderator" read as "anyone who may
write a valid marker for this target", and cannot be cancelled. A
close is undone with an open.

Which marker decides is worked out twice, as UN-RFC 0033 section 4.2
picks the current marker:

1. among the target author's own valid markers, and
2. among the valid markers by the owner and moderators.

Comments on the target are **closed** when either current marker is a
close. So the author can close their own entry and open it again, but
cannot open what the owner or a moderator has closed. An open never
lengthens the time: after the deadline of section 3.1 comments stay
closed. In a closed group a marker's body MUST be empty, as for pins.

Neither an entry's own deadline nor a close touches **reactions**
(UN-RFC 0048): readers can still react to a closed entry. Reactions
close only with the group's `comment_days` (UN-RFC 0048 section 4.4).

## 3.3 Groups Other Than Channels

Sections 3.1 and 3.2 apply in open, moderated and closed groups too,
where a **comment** is any reply in a thread: an article whose
`References` names the thread root first. There the author of a
thread can give it a deadline when starting it, the owner can set
`comment_days` for every thread, and the author, the owner and
moderators can close and open a thread, as in a channel. Inboxes and
local groups (UN-RFC 0009) have none of this.

Closing a thread in a discussion group stops replies in that thread
only. Anyone who may post in the group can still start a new thread,
for instance to go on with the discussion.

# 4. Node Rules

This section replaces the channel rule of UN-RFC 0004 section 5. A node
MUST reject an ordinary (non-control) article in a channel unless one
of these holds under the current manifest:

1. `Author-Key` is a starter; or
2. `comments` is `open`, and the article is a comment: its `References`
   header is present and its **first** Message-ID names a thread root
   in the same group that the node holds, the article's `Date` is
   within the deadline of section 3.1 (none when neither
   `comment_days` nor the root's `Comment-Days` is present), and
   comments on that thread are not closed (section 3.2).

A thread root in a channel can only have been accepted from a starter,
so a node does not check who wrote it, and a root stays valid when its
author later stops being a poster.

The other rules apply to comments unchanged: the group's `banned` list
(UN-RFC 0004 section 5.1), its `min_pow` and the node's own minimum
(UN-RFC 0006), key standing (UN-RFC 0025) and `kinds` (UN-RFC 0028).
Moderators and the owner can cancel a comment like any other article.

## 4.1 Comments Before Their Thread

Articles may arrive out of order. A node that receives a comment whose
thread root it does not hold MUST NOT accept it, and MUST answer as for
a temporary failure (UN-RFC 0005), so that the peer offers it again
later or the node fetches it when catching up (UN-RFC 0017). It MUST
NOT answer as for a permanent rejection, which would lose the comment.

A node MAY keep such comments aside for a short time, at most one hour,
and accept them as soon as the root arrives.

## 4.2 Replies in Other Groups

In an open, moderated or closed group, a node MUST reject a reply
whose `Date` is past the thread's deadline (section 3.1), or whose
thread is closed (section 3.2), when it holds the thread root. A node
that does not hold the root, for instance because it has expired,
applies neither, and the group's other rules decide as before
(UN-RFC 0004 section 5). In a moderated group the check is made when
the reply arrives, before it goes to approval.

# 5. Clients

- A client SHOULD offer "comment" (reply) on thread roots and comments
  in a channel whose `comments` is `open`, and SHOULD NOT offer a new
  thread to a user who is not a starter.
- A client SHOULD show the threads view for such a channel, with posts
  by starters marked so readers can tell the channel's own posts from
  the comments.
- A client SHOULD tell the user when comments on a thread have closed,
  because of a deadline or a close (section 3), rather than letting the
  post fail, and SHOULD show a close's note.
- When a user starts a thread or writes an entry where replies are
  possible, a client SHOULD let them choose how long it takes
  comments, from none up to the group's `comment_days`, with the
  group's as the default, and MUST NOT offer longer. It writes
  `Comment-Days` only when the choice differs from the group's.
- A client SHOULD offer "Close comments" and "Open comments" on an
  entry or thread to its author, the owner and moderators, and SHOULD
  show when its comments close, once that is less than a day away. In
  the threads view a client MAY say "replies" instead of "comments".
- When creating any group but an inbox, a client SHOULD let the owner
  set `comment_days`, and later change it.
- When creating a channel, a client SHOULD ask whether readers may
  comment, and leave `comments` absent if not.

# 6. Automated Posters

Many channels are filled by programs: release notes, lists of known
nodes, weather, "on this day". Readers should be able to tell, for
instance to know that nobody reads their comment, or to hide such posts.

UN-RFC 0022 section 4 gains an optional profile field:

| Field | Type    | Req. | Meaning                                    |
|-------|---------|------|--------------------------------------------|
| `bot` | boolean | no   | `true`: this identity posts automatically   |

- A client SHOULD show a small mark next to the author of an article
  whose author's public profile has `bot` set to `true`, and MAY offer
  to hide such articles.
- `bot` is a statement by the key holder like everything else in a
  profile (UN-RFC 0022 section 3). It grants and limits nothing, and a
  client MUST NOT take a missing `bot` as proof that a person wrote an
  article.
- A bot SHOULD name a person to contact in its profile's `links`, such
  as its operator's identity or e-mail address.
- A bot SHOULD post with a key of its own that is a poster in the
  channel, never with the owner's key, so that a leaked bot key can be
  removed from the manifest without risk to the group (UN-RFC 0010
  section 7 gives the same advice for lists of known nodes).
- A bot that reposts material from elsewhere SHOULD credit the source
  and link to it, and its operator is responsible for the material's
  licence allowing it.

# 7. Changes to Other Documents

- **UN-RFC 0004** section 3.1: the channel manifest fields `comments`
  and `comment_days` (section 3). Section 5: the channel rule is
  replaced by section 4 of this document.
- **UN-RFC 0022** section 4: the profile field `bot` (section 6).
- **UN-RFC 0004** section 3.1: `comment_days` in open, moderated and
  closed groups too (section 3.3); section 5: replies past a deadline
  or in a closed thread are rejected (section 4.2).
- **UN-RFC 0004** section 7: the control articles `comments-close` and
  `comments-open` (section 3.2).
- **UN-RFC 0048** section 4.4: reactions close with `comment_days` in
  every group that sets it, not only in channels, and never because of
  an entry's own deadline or a close (section 3.2).
- **UN-RFC 0042** section 2: what an edit of a thread root may do to
  `Comment-Days` (section 3.1).
- **UN-RFC 0005** section 4: the rejection reason `441 later` answers a
  `POST` that may succeed later; after `IHAVE` the temporary failure is
  `436`, and after `TAKETHIS` a node answers `431`, which the feeding
  node treats as "try later" (section 5.2).
- **UN-RFC 0000** section 6: 0030 is added to the index.

# 8. Rationale

- **Why a field and not a fifth group type?** A channel with comments
  is still a channel: the same people start threads, and the owner may
  want to open or close comments later, which a type cannot do.
- **Why check only the first reference?** It names the thread, which is
  what the rule is about. Whether a comment answers the root or another
  comment does not matter to the node, and checking every reference
  would refuse comments whose intermediate articles a node has expired.
- **Why not check who wrote the root?** Every root in a channel was
  accepted from a starter. Checking again against the current manifest
  would orphan every comment on a poster's old posts the moment the
  owner removes that poster, which is usually a bot key being rotated.
- **Why `comment_days`?** Old threads attract spam and are rarely
  watched. The owner of a daily weather report may want comments for a
  week; the owner of release notes may want them for ever.
- **Why a deadline on the entry?** A feed owner often knows when
  writing that a post needs comments for an evening, not for the
  group's week: an event, a question, a "who is coming?". The header
  is signed with the entry, costs nodes nothing to store, and cannot
  be moved later.
- **Why never longer than the group?** The group's deadline is the
  owner's promise to readers and the nodes' limit on old threads. An
  entry may ask for less, never more.
- **Why markers and not a list in the manifest?** A busy feed closes
  many entries over the years; a list in the manifest would grow
  without end and be sent with every change. A marker per entry
  expires with the entry, as pins do.
- **Why in discussion groups too?** A thread that has run its course,
  or gone wrong, is the same problem in a discussion group as in a
  feed, and readers know closed threads from forums. Closing one
  thread does not silence anyone: a new thread is always possible.
- **Why may readers still react to a closed entry?** A close is for a
  discussion that has gone wrong. A reaction cannot start one, and
  "I liked this" should not be lost because others quarrelled. The
  group's `comment_days` still closes reactions on old threads, which
  is about spam, not about the entry.
- **Why two chains?** The author should be able to close their own
  entry, which is what other networks offer, but must not be able to
  overrule the owner or a moderator who closed it.
- **Why put the bot flag here?** It came up together with channels that
  bots fill, and it is one optional field. It belongs to UN-RFC 0022,
  which this document updates.

# 9. Security and Privacy Considerations

- **Spam in comments.** Opening a channel for comments opens it to the
  same spam as an open group, limited to existing threads. Postage,
  key standing and bans apply as there, and `comment_days` keeps old
  threads closed. An owner who is flooded can set `comments` to `none`.
- **Fake thread roots.** A comment cannot create a thread: a node only
  accepts it if it holds the root, and only starters can post roots. A
  malicious node can accept comments without a root, but its peers
  will not, so they go no further.
- **Held comments.** Keeping comments aside until their root arrives
  costs memory. The one-hour limit, and dropping held comments when
  short of space, keep this bounded; the sender offers them again.
- **Late closes.** Nodes pass markers on like other articles, so a
  node that has not yet received a close may accept a few more
  comments, and they stay. Closing stops new comments; it was never a
  way to remove what is there. Removing is cancelling, as before.
- **Closing to silence.** An author or owner can close comments when
  criticism comes. Readers still see that comments were closed, and
  when, and can answer in their own feeds or groups; nothing that
  was written disappears.
- **False bot flags.** A person can claim to be a bot and a bot can
  leave the flag out. The flag is a courtesy, not a guarantee, and
  section 6 says clients must not treat it as one.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
