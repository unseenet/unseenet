```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0034                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0000, 0008, 0029

                  Unseenet: Feeds and Following
```

# Abstract

Many people today know only one way of reading a network: a **feed**,
where somebody publishes a short note or a longer post, readers comment
underneath, and the newest is on top. This document adds that as a
third way of showing a group, beside threads and chat. It changes
nothing in how articles are written, stored or carried: a feed is a
thread tree shown differently. It then gives every identity an optional
**personal feed** that others can follow, and says how a client builds
a **timeline** from the feeds a reader follows, without any node
learning who follows whom.

# 1. Motivation

Unseenet has discussion (threads, UN-RFC 0002) and conversation (chat,
UN-RFC 0008, 0028). What is missing is the shape that Facebook,
Mastodon and X have made familiar: one person, or one group, publishes;
everybody else comments on what was published.

Most of what that needs is already there:

- A thread root with replies is a post with comments.
- UN-RFC 0030 lets a channel's owner open it for comments, so that only
  the owner, moderators and posters start threads and anybody may
  comment. That is exactly the rule of a personal feed or a news feed.
- An open group lets anybody start threads, which is the rule of a
  Facebook group.
- Chat lines (UN-RFC 0028) have no subject, which is what a short note
  is; posts have one, which is what a longer article with a headline is.

What is missing is a way for the owner to say "show this as a feed",
a known place where a person's feed lives, and a description of how a
client shows feeds and follows people. This document provides those
three, and nothing else.

Because a feed is only a view, a client that does not know this
document shows a feed as threads, and loses nothing but the layout.

# 2. Terms

**Feed**
:   A group whose manifest has `"view": "feed"` (section 3).

**Entry**
:   A thread root in a feed: an article without `References`.

**Comment**
:   Any other ordinary article in a feed. In a channel this is the
    comment of UN-RFC 0030; in other group types it is simply a reply.

**Personal feed**
:   The feed owned by an identity at a name that follows from its key
    (section 5).

**Following**
:   A reader's choice to read a feed in their timeline. It is kept by
    the reader's client and nowhere else (section 6).

**Timeline**
:   The entries of all feeds a reader follows, merged by the reader's
    client (section 7).

# 3. The Feed View

## 3.1 Manifest

The field `view` of UN-RFC 0008 section 3.1 gains the value `feed`:

| `view`    | Shown as                                         |
|-----------|--------------------------------------------------|
| `threads` | a thread tree, one post at a time (UN-RFC 0008)  |
| `chat`    | a running conversation (UN-RFC 0008)             |
| `data`    | not shown to people (UN-RFC 0008 section 3.1.1)  |
| `feed`    | entries newest first, comments under each (this document) |

A client that does not know a value of `view` MUST show the group as
`threads`. Like every `view`, `feed` is a hint: readers MAY switch a
feed to threads or chat and back, and clients SHOULD remember the choice
per group.

`view` says nothing about who may write; that is the group's type, and
for channels the `comments` field of UN-RFC 0030. Nodes treat a feed
like any other group. In particular, `feed` does not imply
`low_latency` (UN-RFC 0008 section 3.2), and owners SHOULD NOT set it
for feeds: a feed is not read in seconds, and the random forwarding
delay protects where entries are posted from.

## 3.2 Combinations

The rules of a feed come from fields that already exist. Owners SHOULD
use one of these:

| Kind of feed                         | `type`      | Other fields                          |
|--------------------------------------|-------------|---------------------------------------|
| Personal feed, news, a bot           | `channel`   | `comments: "open"` (UN-RFC 0030)      |
| Announcements without comments       | `channel`   | `comments: "none"`                    |
| Community feed, anybody may publish  | `open` or `moderated` |                             |
| Feed among friends                   | `closed`    |                                       |

and SHOULD set `kinds` (UN-RFC 0028) to `["chat", "post"]`, so that an
entry can be a short note or a post with a headline (section 4.1).

# 4. Showing a Feed

This section describes what a reader should see. Clients MAY differ in
layout; they SHOULD keep what each point is for.

## 4.1 Entries

- Entries are shown newest first, by `Date`, each as a whole: author,
  time, the full text with formatting (UN-RFC 0031) and attachments
  (UN-RFC 0027), not a subject line to open.
- An entry that is a **chat line** is a short note, shown without a
  headline. An entry that is a **post** shows its `Subject` as a
  headline above the text.
- Under each entry the client shows how many comments it holds and the
  newest one or two, and lets the reader open the rest.
- Pinned entries (UN-RFC 0033) are shown first, marked as pinned.
- Entries by starters of a channel (UN-RFC 0030 section 2) are the
  feed's own and need no mark; in an open group every entry shows its
  author.

## 4.2 Comments

- Comments are shown under their entry, oldest first, so that they read
  as a conversation.
- A client SHOULD show at most two levels: comments on the entry, and
  answers to a comment indented once beneath it. An answer deeper in
  the tree is shown as an answer to the comment at the second level,
  with a note of whom it answers. The article's `References` are not
  changed; the threads view still shows the whole tree.
- Writing a comment SHOULD default to a chat line (no subject), and the
  client SHOULD NOT ask for a subject; a reader who wants to write a
  post in answer can choose to.
- Write controls follow the group's rules (UN-RFC 0030 section 5): a
  reader who may not start an entry is not offered one, and comments on
  an entry whose `comment_days` has passed are shown as closed.

## 4.3 Quoting

Comments in a feed are short and sit right under what they answer, so
a client SHOULD NOT quote the entry in a comment by default. Where a
comment answers another comment, the indentation and the "in answer to"
note take the place of a quote.

## 4.4 Many Comments

An entry in a busy feed can collect thousands of comments. A reader
should see the entry and the newest conversation at once, and the
client should not fetch thousands of articles over Tor to show them.

- **Collapsed by default.** Under each entry the client shows the
  number of comments and the newest one or two (section 4.1). Opening
  the comments shows the newest page of them, oldest first within the
  page, with a way to load the earlier pages. A page SHOULD hold 20 to
  50 comments.
- **Answers collapsed too.** Answers to a comment (the second level of
  section 4.2) are shown as "N answers" until the reader opens them.
- **Always shown.** Even when the rest is collapsed, a client SHOULD
  show, marked as such, comments by the feed's starters (UN-RFC 0030
  section 2), comments by identities the reader follows, the reader's
  own comments and the answers to them, and a comment the reader came
  to through a mention (UN-RFC 0032). These rules depend only on things
  the reader can see and change; a client MUST NOT pick comments to show
  by how many answers or reactions they have (section 7).
- **Fetch what is shown.** A client SHOULD count comments and build the
  tree from overview data (`OVER`/`XOVER` where the node offers them,
  otherwise the headers it already holds), and fetch the bodies of
  comments only when they are shown. It SHOULD keep what it has fetched,
  so that opening an entry again costs nothing.
- **Owners can close.** An owner whose entry draws more comments than
  is useful can stop them with `comment_days` (UN-RFC 0030) or close
  comments on the whole feed.

# 5. Personal Feeds

## 5.1 The Feed Group

An identity's personal feed is the group it owns named `feed`:

```
feed@<fingerprint of the identity's key>
```

It is a **personal group** (UN-RFC 0029 section 2.1): its Group ID
follows from the key, so anyone who knows a key, or a name that leads to
it (UN-RFC 0019), can find it, and how it is started, ended, renewed,
found and followed is said there once for all personal groups. Only
what is particular to a feed is here.

Its manifest (UN-RFC 0004 section 3) has, besides what UN-RFC 0029
section 2.1 requires:

- `view`: `feed`;
- `comments`: `open` or `none`, and optionally `comment_days`
  (UN-RFC 0030);
- `kinds`: RECOMMENDED `["chat", "post"]`.

A feed for a closed circle of people is an ordinary closed group with
`"view": "feed"` (section 3.2), not a personal feed.

## 5.2 Starting a Feed

When a client creates a personal feed, which it only does when the user
asks (UN-RFC 0029 section 2.1), it SHOULD ask whether readers may
comment, with `open` as the suggested answer.

Entries expire with the group's `retention_days` like all articles.
Owners who want a few entries to stay pin them (UN-RFC 0033).

# 6. Following

To follow a feed is to subscribe to it, as to any group. Nothing is
sent to the feed's owner, to the network or to any node beyond the
reading the client does anyway.

- A client keeps the list of feeds a user follows in the user's vault,
  with the rest of their subscriptions. It MUST NOT publish the list,
  post it to any group, or send it to a node in any form other than
  reading the feeds.
- Reading a feed tells the reader's own node that somebody using it is
  interested in that feed, as for every group (UN-RFC 0008 section 2.3).
  Over Tor the node does not learn who. Clients SHOULD read followed
  feeds the same way and at the same times as their other groups, so
  that following does not stand out.
- Following is subscribing: there is no separate mechanism. Every
  group a user subscribes to that is shown as a feed is followed,
  personal or not - a channel such as `dk.marsvin` where a few post and
  everybody comments, news, a bot - and its entries come into the
  timeline (section 7). "Follow" is only the word a client uses for
  subscribing to a feed or to a person (section 6.1).

## 6.1 Following a Person

A user can also follow a **person**: an identity, given by its key or
by a name that leads to one (UN-RFC 0019), such as `andreas@lorensen`.
It is how people follow one another on Mastodon or Facebook, without
anybody being told.

- **What it follows.** To follow an identity is to follow every feed
  that is its own: its personal feed (section 5) and, when they exist,
  its other personal groups (UN-RFC 0029 section 2.1), and the feeds it
  lists in its public profile (UN-RFC 0022 section 4.5). A client
  subscribes to each of them as in section 6, and their entries come
  into the timeline (section 7).
- **New feeds.** A client reads the profiles of the identities a user
  follows as it reads other profiles (UN-RFC 0022 section 9.2), and
  when it finds a personal group or a listed feed it did not follow
  before, it follows it too. A feed the identity no longer lists, or
  whose group has expired, it stops following, unless the user also
  follows that feed on its own.
- **The key, not the name.** A client resolves a name to a key when the
  user follows, and from then on follows the key. If the name later
  leads to another key (UN-RFC 0019), the client keeps following the
  first and tells the user, who may follow the new key instead.
- **Private, as all following.** The list of identities a user follows
  is kept in the vault with the rest of section 6, and the same rules
  apply: it MUST NOT be published or sent to anyone, and the identity is
  not told. Section 8 is unchanged.
- **Unfollowing** an identity unsubscribes from the feeds that were
  followed only because of it.

# 7. The Timeline

A client SHOULD offer a timeline: one feed view (section 4) built from
the entries of every feed the user follows.

- Entries are ordered by `Date`, newest first. Each entry shows which
  feed it is from.
- A client SHOULD NOT reorder the timeline by what others do: by number
  of comments, by who commented, or by anything a reader cannot see and
  change. The timeline is what the reader chose to follow, in the order
  it was written. A client MAY offer filters the reader sets, such as
  hiding bots (UN-RFC 0030 section 6) or showing one feed only.
- Comments in the timeline are shown as in section 4.2. Writing a
  comment from the timeline writes it to the entry's own feed.
- Entries from feeds the reader does not follow MUST NOT be added to
  the timeline, except where the reader is mentioned (UN-RFC 0032), and
  then marked as a mention.

# 8. Who Follows

A feed's owner cannot see how many follow the feed, or who. This is on
purpose, and a client MUST NOT pretend otherwise.

- **Nodes do not know.** A node knows only that some of its own readers
  read a feed; it does not know who they are, and other nodes have
  their own readers. No node can give a total.
- **A public list would expose people.** Counting followers would mean
  that each follower says so in public, as on Mastodon or Nostr. That
  would put a map of who reads whom into the network, kept by every node
  and every archive, and it is exactly what Unseenet is built not to
  have.
- **An anonymous count would be false.** If followers were counted
  without saying who they are, anybody could make keys and be counted
  many times. Key standing (UN-RFC 0025) makes that slower, not
  impossible, and a number that can be bought is worth nothing to the
  reader and invites people to buy it.

What an owner can see is what everybody can see in the feed itself:

- the comments on each entry, and how many different keys commented;
- mentions of the owner (UN-RFC 0032);
- in a later document, reactions, which are public articles like
  comments and can be counted the same way.

A client MAY show the owner these numbers for their own feed, and
SHOULD make clear that they show who answered, not who read.

A future document MAY let a reader choose to say in public that they
follow a feed. If it does, it MUST be opt-in per feed, and clients MUST
show it as "people who chose to say so", never as the number of
followers.

# 9. Gateways

Short public notes on other networks, such as Nostr text notes or
posts on Mastodon, map naturally to entries in a feed. A network
profile (UN-RFC 0023) MAY bring them in as a feed under the network's
hierarchy, with each note as a chat-line entry and replies as comments.
This document does not define such a mapping.

# 10. Changes to Other Documents

- **UN-RFC 0008** section 3.1: `view` gains the value `feed`
  (section 3.1), and a client that does not know a value of `view`
  shows the group as `threads`.
- **UN-RFC 0029** section 2: the table of key-bound groups gains
  `feed@<fp>`, a personal group (UN-RFC 0029 section 2.1), this
  document section 5.1.
- **UN-RFC 0000** section 6: 0034 is added to the index.

# 11. Rationale

- **Why a view and not a group type?** A feed is a thread tree; only
  the way it is shown differs. The type is fixed at creation and
  decides who writes, which existing types and UN-RFC 0030 already
  cover. A view can be changed by the owner and overridden by the
  reader, and a client that does not know it still shows every article.
- **Why only two levels of comments?** It is what readers of feeds
  expect, and deep trees under a short note are hard to read on a
  phone. The tree is kept in the articles, so nothing is lost; readers
  who want it switch to the threads view.
- **Why chat lines as notes?** A short note has no subject, which is
  what a chat line is (UN-RFC 0028). Making up a subject for it would
  break the rule of UN-RFC 0028 section 3.3. A post with a subject
  becomes an entry with a headline, so one feed can carry both.
- **Why a key-bound personal feed?** So that a person's feed can be
  found from their key or name with no directory, and disappears when
  the key is no longer used (UN-RFC 0029).
- **Why no follower counts?** Section 8.
- **Why no ranking?** A timeline ordered by what others do rewards
  whatever gets the most reactions, and needs data about readers that
  Unseenet does not collect. Chronological order needs nothing.
- **Why no reactions here?** Reactions ("likes") are the first thing
  readers of feeds miss. They are also articles that cost postage and
  are carried by every node, and they deserve a document of their own,
  usable in every view, not only in feeds.

# 12. Security and Privacy Considerations

- **A personal feed is public and linked to the identity.** Everything
  in it can be kept by anybody. Section 5.2 makes the client say so.
  Users who need to keep things apart SHOULD use a separate identity
  for a feed (UN-RFC 0003 section 2).
- **Following stays private** as long as clients keep section 6. A
  client that publishes follow lists would expose its users, and a
  malicious client can do that whatever this document says.
- **Reading patterns.** A reader's own node can see which feeds are
  read through it, as for any group. Over Tor it does not learn by
  whom. A reader who follows a single small feed is easier to guess
  than one who follows many groups.
- **Spam in comments** is the spam of UN-RFC 0030 section 9: postage,
  key standing, bans and `comment_days` apply, and the owner can close
  comments.
- **Impersonation.** Anybody can create a group named like somebody
  else's feed, but not `feed@<fp>` for a key they do not hold. Clients
  SHOULD show a personal feed by its owner's name (UN-RFC 0019) or
  fingerprint, never by the group's title alone.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
