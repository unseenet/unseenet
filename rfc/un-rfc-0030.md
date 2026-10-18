```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0030                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0004, 0022

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

A node MUST reject a manifest of a group that is not a channel if it
carries either field, and a channel manifest whose `comments` has any
other value, or whose `comment_days` is not a positive integer.

The owner MAY change both fields in any later manifest. A change
applies to articles that arrive after it, as for every other posting
rule; comments already accepted stay.

# 4. Node Rules

This section replaces the channel rule of UN-RFC 0004 section 5. A node
MUST reject an ordinary (non-control) article in a channel unless one
of these holds under the current manifest:

1. `Author-Key` is a starter; or
2. `comments` is `open`, and the article is a comment: its `References`
   header is present and its **first** Message-ID names a thread root
   in the same group that the node holds, and, if `comment_days` is
   present, the article's `Date` is no more than `comment_days` days
   after the thread root's `Date`.

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

# 5. Clients

- A client SHOULD offer "comment" (reply) on thread roots and comments
  in a channel whose `comments` is `open`, and SHOULD NOT offer a new
  thread to a user who is not a starter.
- A client SHOULD show the threads view for such a channel, with posts
  by starters marked so readers can tell the channel's own posts from
  the comments.
- A client SHOULD tell the user when comments on a thread have closed
  because of `comment_days`, rather than letting the post fail.
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
- **False bot flags.** A person can claim to be a bot and a bot can
  leave the flag out. The flag is a courtesy, not a guarantee, and
  section 6 says clients must not treat it as one.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
