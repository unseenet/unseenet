```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0048                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0002, 0028, 0030, 0031, 0034

                       Unseenet: Reactions
```

# Abstract

A **reaction** is how a reader says "I like this" without writing a
comment: one emoji under a feed entry, a comment, a post or a chat line.
This document makes a reaction a small signed article of its own kind,
with no subject and one emoji, pointing at the article it answers. Each
key has at most one reaction on an article, and can change or take it
back. The owner of a group chooses which emoji the group takes, or none,
and nodes enforce that where they can see it. Clients show reactions as
counters, never as comments, and never use them to order what a reader
sees.

# 1. Motivation

Reactions are the first thing readers of feeds miss (UN-RFC 0034
section 11). Without them, the only way to show agreement is a comment,
which in a feed is noise and in a discussion is the "+1" and "me too"
that filled Usenet threads. A reaction says the same in one character
and is shown as a number, so it costs readers nothing.

Nostr (NIP-25) and Matrix (`m.reaction`) both make a reaction a small
event pointing at another, so the model is proven at scale and maps to
them directly through gateways (section 9).

A reaction is still an article: it is signed, costs postage and is
carried by every node. That keeps it honest (section 10), but it means
reactions must be cheap to count and must go away with what they are
about (section 6).

# 2. Terms

**Reaction**
:   An article with `Message-Kind: reaction` (section 3).

**Target**
:   The article a reaction is about: the last Message-ID of its
    `References`.

**Reaction set**
:   The emoji a group takes as reactions (section 4).

# 3. The Reaction Article

## 3.1 Headers

A reaction is an ordinary (non-control) article (UN-RFC 0002) with:

```
Message-Kind: reaction
Reaction: 👍
Subject:
References: <root@example> <comment@example>
```

- `Message-Kind` is `reaction` (UN-RFC 0028 section 3.1 gains this
  value). A receiver that does not know it takes the article for a post
  (UN-RFC 0028), which has no subject and is rejected; that is the
  intended failure on old nodes.
- `Reaction` holds exactly one emoji (section 3.2).
- `Subject` MUST be empty.
- `References` MUST be present, as for any reply (UN-RFC 0002 section
  2.3): the target's own `References` followed by the target's
  Message-ID. The **last** Message-ID is the target.
- The body MUST be the same emoji as `Reaction`, followed by an
  optional line break, so that a newsreader that does not know
  reactions shows something sensible. Receivers use the header.
- A reaction MUST NOT carry attachments (UN-RFC 0027), `Supersedes`
  other than in section 5, or a `Content-Type` other than the default.

## 3.2 The Emoji

The value of `Reaction` is one **emoji**: one fully-qualified RGI emoji
sequence of Unicode Technical Standard #51, version 15.1 or later,
including keycaps, flags, skin-tone modifiers and ZWJ sequences. It is
compared after removing every U+FE0F VARIATION SELECTOR-16. Shortcodes
(UN-RFC 0031 section 5.2) are not allowed in the header; a client that
lets the user type `:+1:` converts it with the gemoji table before
sending.

A reaction with anything else in `Reaction` (text, two emoji, a
shortcode, nothing) is invalid.

## 3.3 What Can Be Reacted To

The target MUST be an ordinary article in the **same group**: a thread
root or feed entry, a comment or a reply at any depth, a post or a chat
line. A reaction MUST NOT target a control article or another
reaction.

# 4. Which Reactions a Group Takes

## 4.1 Manifest Field

A manifest (UN-RFC 0004 section 3) MAY contain:

| Field       | Type                       | Meaning                              |
|-------------|----------------------------|--------------------------------------|
| `reactions` | array of strings, or `"any"` | The group's reaction set          |

- An array lists the emoji the group takes, 0 to 12 of them, each one
  emoji as in section 3.2, none repeated. An empty array means the
  group takes no reactions.
- `"any"` means the group takes any emoji.
- Anything else makes the manifest invalid (UN-RFC 0004 section 4,
  step 3).

A later manifest MAY change `reactions`. As for every posting rule it
applies to reactions that arrive after it; reactions a node already
holds stay.

## 4.2 Default

A manifest **without** `reactions` has, by its `view` (UN-RFC 0008,
UN-RFC 0034):

| `view`              | Reaction set                         |
|---------------------|--------------------------------------|
| `feed`, `chat`      | the default set: 👍 👎 ❤️ 😂 😮 😢    |
| `threads` or absent | none                                 |
| `data`              | none, and `reactions` MUST be absent |

Discussion groups take no reactions unless their owner turns them on:
they are a choice in a discussion, and an expectation in a feed or a
chat. The default set is fixed by this document; changing it would
change existing groups, so a later document may only add a new value.

## 4.3 Inboxes

Inbox manifests do not carry `reactions`; a node MUST ignore it there.
In private chats and private posts (UN-RFC 0009, UN-RFC 0028) any emoji
may be used. A reaction to a private message is a private message: it
is sealed to the inbox of the person reacted to, like any other.

## 4.4 Relation to Other Fields

`reactions` is independent of `kinds` (UN-RFC 0028), which never
contains `reaction`, and of `comments` (UN-RFC 0030): a channel may take
reactions without taking comments, so readers of an announcement
channel can say they liked it without being able to answer it. Where a
channel sets `comment_days`, reactions close at the same time as
comments.

# 5. One Reaction per Key

A key has at most **one** reaction on a target.

- **Changing** a reaction is a new reaction to the same target with
  `Supersedes` naming the reaction it replaces (UN-RFC 0042). Nodes
  withdraw the old one as for any edit.
- **Taking back** a reaction is a cancel of it (UN-RFC 0004 section 7).
- A node SHOULD reject a reaction from a key that already has a
  reaction on the same target the node holds, unless the new one
  supersedes it. Nodes see articles in different orders, so clients
  MUST NOT rely on this: where a key has several reactions on a target,
  a client counts only the one with the latest `Date`, and among equal
  dates the one with the greatest Message-ID.

The owner and moderators may cancel reactions like any other article.

# 6. Nodes

## 6.1 Accepting

In open, moderated and channel groups a node MUST reject a reaction
(UN-RFC 0002 section 5, the permission step) unless:

1. it is valid by section 3;
2. its emoji is in the group's reaction set (section 4) under the
   manifest current when it arrives;
3. the node holds the target, and the target is an ordinary article
   that is not a reaction. A node that does not hold the target MUST
   answer as for a temporary failure, as for a comment before its
   thread (UN-RFC 0030 section 4.1).

A reaction is not a comment: in a **channel**, it is accepted by these
rules whatever `comments` says (section 4.4). In a **moderated** group it
is accepted directly, without the submission queue (UN-RFC 0009 section
3); moderators can cancel it. All other rules apply unchanged: `banned`,
`min_pow` and the node's own minimum (UN-RFC 0006), and key standing
(UN-RFC 0025).

In closed groups and inboxes everything but the outer article is
encrypted, and a node cannot and MUST NOT try to enforce this section
(section 8).

## 6.2 Expiry

A reaction expires with the group's `retention_days` like any article.
When a node withdraws or expires a target, it SHOULD drop the reactions
to it as well: a reaction to nothing is of no use to anybody. Reactions
to a pinned article (UN-RFC 0033) are not pinned and expire by their own
`Date`.

## 6.3 Reading

Nodes SHOULD answer `HDR Reaction` (RFC 3977 section 8.5, UN-RFC 0005
section 2.4) over a range, so that clients can count reactions without
fetching articles. The reference implementation answers `HDR` for any
header.

# 7. Clients

## 7.1 Counting

A client counts reactions per target and emoji, one per key (section
5). In open, moderated and channel groups it SHOULD build the counts from
`HDR Reaction`, `HDR References` and `HDR Author-Key` over the range it
reads anyway (UN-RFC 0034 section 4.4), and fetch no reaction articles
unless the reader asks who reacted.

A client MAY count only keys of some standing (UN-RFC 0025), and MAY
show besides a count how many of the reacting keys are the reader's
contacts. It MUST make clear what it counts.

## 7.2 Showing

- Under every article that has reactions - an entry, a comment, an
  answer, a post, a chat line - a client shows each emoji with its
  count, the reader's own reaction marked.
- Reactions are never shown as comments, as posts in a thread tree or
  as lines in a chat, and never count as comments (UN-RFC 0034 section
  4.1).
- A reader can see who reacted with an emoji: their names (UN-RFC 0019)
  or fingerprints.
- A client MUST NOT order, pick or hide articles by their reactions: not
  in a feed, a timeline, a comment list or a thread (UN-RFC 0034
  sections 4.4 and 7). Reactions are shown, not used.

## 7.3 Reacting

- A client offers to react to an article only where the group's
  reaction set is not empty and the reader may post (write controls are
  not offered where writing is impossible).
- It offers the group's reaction set, in its order. Where the set is
  `"any"`, it offers the default set first and a way to choose any
  other emoji.
- Choosing the emoji the reader already gave takes it back (section 5);
  choosing another changes it.
- A terminal client SHOULD offer reacting with one key and the set as a
  short numbered list; a graphical client as a row of emoji under the
  article.
- Because a reaction costs postage, a client SHOULD do the work in the
  background and show the reaction at once, marked as pending until it
  is posted.
- A client SHOULD say, the first time a user reacts, that reactions are
  public and signed (section 10).

# 8. Closed Groups and Inboxes

In closed groups `Message-Kind`, `Reaction`, `Subject`, `References` and
the body are in the encrypted inner article (UN-RFC 0004 section 6);
`Reaction` MUST NOT appear in the outer article. Nodes cannot tell a
reaction from any other article there, and cannot count or enforce.

Clients of members enforce the reaction set: a reaction whose emoji is
not in it, or which breaks section 3 or 5, is not counted. A client MUST
NOT post one. Counting needs the inner articles, so in a busy closed
group a client fetches the articles to count them.

The same holds for inboxes (section 4.3), with any emoji allowed.

# 9. Gateways

A network profile (UN-RFC 0023) MAY map reactions:

- **Matrix:** an `m.reaction` annotation with an emoji key is a
  reaction; a redaction of it is a cancel. Keys that are not one emoji
  are dropped.
- **Nostr:** a kind 7 event (NIP-25) whose content is one emoji is a
  reaction; content `+` or empty is 👍 and `-` is 👎. A deletion
  (kind 5) of it is a cancel.
- **Usenet** and other networks without reactions: reactions MUST NOT
  be sent out, not even as articles with the emoji as text.

A gatewayed reaction whose emoji is not in the group's reaction set is
dropped, not changed to another emoji. Reactions coming in through a
gateway are counted under the gateway's key or the keys it uses for
outside authors, as the profile says, so that one outside person is
counted once.

# 10. Security and Privacy Considerations

- **Reactions are public and signed.** In open, moderated and channel
  groups anybody can see which key reacted to what, and keep it. That
  is the same as for a comment, but people react more freely than they
  write, so a client tells users so (section 7.3). Users who need to
  keep things apart use a separate identity (UN-RFC 0003 section 2).
- **A reading signal.** A reaction shows that a key read an article and
  when. Over many reactions that is a picture of what a key reads and at
  what times of day, which a comment shows too but less often. Clients
  SHOULD NOT post a reaction the moment an article arrives; the node's
  random forwarding delay (UN-RFC 0005 section 5.5) helps further.
- **Bought likes.** Anybody can make keys and react many times.
  Postage (UN-RFC 0006) and key standing (UN-RFC 0025) make that slower,
  and clients may count only keys of standing (section 7.1). Because
  reactions never order what readers see (section 7.2), inflated counts
  buy attention only from readers who look at the number.
- **Load.** Popular articles get many more reactions than comments.
  They are small, cost postage, expire with their group and with their
  target (section 6.2), and can be counted from headers (section 6.3).
  Owners who do not want them set `reactions` to `[]`.
- **Closed groups.** A node can see that articles arrive in a closed
  group, not that they are reactions; short articles in bursts may hint
  at it, as for chat lines (UN-RFC 0028 section 9). Clients MAY pad.

# 11. Rationale

- **Why an article, not a counter on a node?** A counter would be kept
  by nodes nobody can check, and could be set to anything. A signed
  article can be checked by every reader, and a node that hides one is
  caught by another that carries it.
- **Why a kind of its own?** So that a comment that happens to be "👍"
  stays a comment, and so that clients never show reactions as comments
  or count them as such.
- **Why the emoji in a header?** So that counting needs `HDR`, not the
  bodies of thousands of articles over Tor.
- **Why one per key?** Otherwise one reader could fill a counter. More
  than one emoji per key, as Matrix allows, would multiply the articles
  for little gain.
- **Why off by default in discussion groups?** Reactions belong to the
  feed and the chat; in a discussion they are welcome when the owner
  wants them, and they replace "+1" posts there.
- **Why 👎 in the default set?** Disagreeing should be as easy as
  agreeing, without a comment. On networks that rank by votes a
  thumbs down buries what it is given to; here reactions never order or
  hide anything (section 7.2), so it is only a counter. Owners who do
  not want it leave it out of their set.
- **Why may a channel take reactions but no comments?** An announcement
  wants to know it was read and liked, not to be answered.

# 12. Changes to Other Documents

- **UN-RFC 0002** section 2.3: the header `Reaction` is added.
- **UN-RFC 0028** section 3.1: `Message-Kind` gains the value
  `reaction`, defined in this document; section 3.3: a reaction's
  `Subject` is empty; section 4.1: `kinds` never contains `reaction`.
- **UN-RFC 0030** section 4: a reaction in a channel is accepted by
  section 6.1 of this document, not as a comment.
- **UN-RFC 0031** section 5.3: reactions are this document.
- **UN-RFC 0034** section 8: "in a later document, reactions" is this
  document; section 4.4: clients MUST NOT pick comments by reactions.
- **UN-RFC 0000** section 6: 0048 is added to the index.

# 13. Open Issues

- **Group-owned emoji** as reactions, once pictures used as emoji are
  specified (UN-RFC 0031 section 5.3).
- **Postage for reactions.** This document gives reactions the same
  postage as any article. A lower `min_pow` for reactions would make
  reacting quicker but bought likes cheaper.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
