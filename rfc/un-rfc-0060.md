```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0060                                              October 2026
Category: Standards Track
Status: Draft
Implemented: -
Updates: 0002, 0004, 0005, 0028, 0032, 0034, 0044, 0045, 0046, 0055, 0059

                         Unseenet: Sharing
```

# Abstract

On Facebook, Mastodon and X people share what they see: a post from
their timeline or a group goes into their own feed, on its own or with
a few words of their own. This document gives Unseenet the same. A
**share** is an ordinary signed article that refers to the original by
Message-ID and group; it never copies it. The reader's client fetches
the original, and a node that does not hold it fetches it from its
peers, so the author keeps the post in their own hands - an edit or a
withdrawal reaches every share - and no single node can stop a shared
post from being read. A post can also be shared into a few other
groups, which keeps the useful part of Usenet crossposting without its
abuse. Nothing is counted: there is no "shared 12 times".

# 1. Motivation

Sharing is how things travel on the networks people know. Without it a
good post in `dk.snak` is seen only by those who already read
`dk.snak`, and a feed (UN-RFC 0034) holds only what its owner wrote.

Copying the post would be the simple way, and the wrong one:

- The author would lose control. A withdrawn or edited post (UN-RFC
  0004 section 7, UN-RFC 0042) would live on, unchanged, in every copy.
- Copies would outlive the original's expiry and fill the network with
  duplicates over the years.
- A copy carried inside another article is an inline part, which
  Unseenet does not otherwise use.

So a share is a reference. That raises one question a copy would not:
the reader's node may not carry the original's group (UN-RFC 0055).
If that ended the matter, a node operator - or whoever can lean on one
- could decide what may be shared. Section 6 therefore lets a node
fetch the original from its peers, and lets the client go to another
node when its own will not.

Usenet had crossposting: one article in several groups at once. Used
well it brought a question to the two groups that could answer it; used
badly it put the same post in every group there was, and the answers
were spread over all of them. UN-RFC 0002 allows one `Newsgroups` only.
Section 7 lets a reader share a post into a few groups instead, each
share an article of its own in its group, at its own cost.

# 2. Terms

Target
: The article that is shared.

Share
: An article with a `Share-Of` header (section 3). A **plain share**
  has no text of its own; a **share with a comment** has.

Sharer
: The key that wrote the share.

Own feed
: The sharer's personal feed, `feed@<fingerprint>` (UN-RFC 0034
  section 5.1).

The key words MUST, SHOULD and MAY are as in RFC 2119.

# 3. Principles

1. **A reference, never a copy.** A share carries the target's
   Message-ID and Group ID, not its text, pictures or signature.
2. **The author decides about the original.** An edit shows in every
   share; a withdrawal removes it from every share; expiry ends it.
3. **Nobody can stop a share being read.** If the reader's node does
   not hold the target, it fetches it; if it will not, the client asks
   another node (section 6).
4. **Closed things stay closed.** What is encrypted cannot be shared.
5. **Nothing is counted.** No number of shares is shown anywhere, as no
   follower count is (UN-RFC 0034 section 8).
6. **A share costs what a post costs.** Postage (UN-RFC 0006) and a
   ripe key (UN-RFC 0025), so sharing opens no new path for spam.

# 4. The Share

## 4.1 Headers

A share carries, besides the headers every article has (UN-RFC 0002):

| Header        | Required | Value                                                  |
|---------------|----------|--------------------------------------------------------|
| `Share-Of`    | yes      | The target's Message-ID, with angle brackets            |
| `Share-Group` | yes      | The target's Group ID (UN-RFC 0004)                     |

A **plain share**:

```
Message-Kind: share
Share-Of: <a1b2c3@example>
Share-Group: dk.snak@ph5f...
Subject:
```

- `Message-Kind` is `share` (UN-RFC 0028 section 3.1 gains this value).
  A node that does not know it takes the article for a post without a
  subject and rejects it, the same intended failure as for reactions
  (UN-RFC 0048 section 3.1).
- `Subject` MUST be empty.
- The body MUST be the target's address (UN-RFC 0031 section 3.4.1,
  `unseenet:<group-id>?m=<message-id>`) on one line, so that a
  newsreader that does not know shares shows something useful.
  Receivers use the headers.
- A plain share MUST NOT carry attachments (UN-RFC 0027), a
  `Link-Card` (UN-RFC 0059) or `References`: it is a thread root.

A **share with a comment** is an ordinary chat line or post (UN-RFC
0028) with the two headers. Its body is the sharer's own text, which
MUST NOT be empty; it MAY carry attachments and a link card like any
post. It is a thread root.

## 4.2 What Can Be Shared

The target MUST be an ordinary article - a feed entry, a thread root,
a comment or reply at any depth, a post or a chat line - in a group
that is **not encrypted**. It MUST NOT be:

- an article in a closed group, a private post or a private chat
  (UN-RFC 0004 section 6, UN-RFC 0009), or any other encrypted article;
- a control article, a reaction (UN-RFC 0048) or a plain share.

Sharing a plain share shares its target instead: the client resolves
it and writes `Share-Of` for the original. A share with a comment can
be shared; it is a post.

Pages of a site (UN-RFC 0035) and people are shared by putting their
address in a post, which gets a card (UN-RFC 0059 section 9).

## 4.3 Where a Share Goes

| Destination                         | Rules                                  |
|-------------------------------------|----------------------------------------|
| The sharer's own feed               | The usual place; section 5             |
| Another group                       | Section 7                              |
| A private chat or private post      | Sent to one person, section 7.4        |

## 4.4 Please Don't Share

An author or a group owner can ask that something not be shared:

- an article MAY carry `Sharing: no`;
- a manifest (UN-RFC 0004 section 3) MAY carry `"share_from": false`
  for the whole group.

A client MUST NOT offer to share such a target, and SHOULD say why
when the user looks for it ("The author asked not to share this").
A node that holds the target MAY reject a share of it. This is a
courtesy, not a protection: anyone who can read a post can copy its
words, and a client MUST NOT present it as more than a request.

## 4.5 Taking a Share Back

A share is withdrawn like any article (UN-RFC 0004 section 7). A
client SHOULD offer "Undo share" where it offers "Share", and SHOULD
NOT let a key hold two shares of the same target in the same group:
sharing again withdraws the earlier share. A share with a comment is
edited with UN-RFC 0042; `Share-Of` and `Share-Group` MUST NOT change
between versions.

# 5. Showing a Share

## 5.1 The Original

A client shows the target as a card made from the network (UN-RFC
0059 section 9): author with name and picture (UN-RFC 0022), group,
time, and the start of the text with its first picture, cut as an entry
is cut in a feed (UN-RFC 0034 section 4.1). Opening it opens the target
in its own group.

- The card is made from the **fetched and checked** target (section
  6.3), never from anything in the share. The sharer cannot change
  what the author wrote.
- If the target has a newer version (UN-RFC 0042), the newest is shown.
  For a share with a comment the card SHOULD say "edited after it was
  shared" when that version is newer than the share's `Date`, so that
  nobody can change what was commented on without it being seen.
- While the target is being fetched the client shows its address and
  "fetching"; it MUST NOT hold up the rest of the feed for it (UN-RFC
  0055 section 7).
- If the target is gone, the card says so and why when known:
  "withdrawn by its author", "no longer in the network" (expired or
  never found), or "not available right now" (section 6.4).

## 5.2 A Plain Share

A plain share is shown as the target itself under a line "Andreas
shared", with the sharer's name opening their profile. It has no text
of its own.

- **Comments and reactions go to the original.** Writing a comment or a
  reaction from a plain share writes it to the target's group, under
  the target, if the reader may write there (UN-RFC 0030 section 5);
  otherwise the write controls are not offered. The comments shown are
  the target's.
- A plain share whose target is gone is not shown in feeds or the
  timeline at all, since there is nothing to show; it stays visible in
  the threads view of its group as its one-line body.
- Replies made to a plain share by clients that do not know this
  document are accepted by nodes and shown in the threads view; feed
  views show the target's comments.

## 5.3 A Share with a Comment

A share with a comment is shown as a post or chat line with the card of
section 5.1 under its own text. It has its own thread: comments and
reactions on it are about the comment and go to the share's own group.

## 5.4 The Timeline

A share in a group that is in the reader's timeline (UN-RFC 0034
section 6.2) brings its target in, at the share's `Date`.

- **Each target once.** When the same target comes in more than once -
  from its own feed and as shares, or from several sharers - the client
  shows it once, at the newest of those times, with "shared by Søren
  and Mette" naming only sharers whose groups are in the timeline. A
  share with a comment is the sharer's own post and is not merged.
- **No count.** A client MUST NOT show how many times a target has been
  shared, in the timeline or anywhere else, and MUST NOT order or weigh
  anything by it, except under the reader's own rules (UN-RFC 0051).
- A reader MAY hide plain shares from one feed or from the whole
  timeline; the choice is kept in their state (UN-RFC 0044 section 4.2,
  `hide_shares`).

## 5.5 Offering It

A client offers "Share" and "Share with a comment" on what can be
shared (section 4.2), with "Share into a group…" and "Send to…" (section
7) next to them, as one menu. It MUST NOT offer them on what cannot be
shared, rather than offering them and refusing afterwards. In the
bootable client sharing works as anywhere else: nothing leaves the
network.

# 6. Fetching the Target

## 6.1 The XUN-FETCH Command

A client asks its node for a target with

```
XUN-FETCH <message-id> <group-id>
```

| Answer                     | Meaning                                              |
|----------------------------|------------------------------------------------------|
| `220 <message-id>` + article | The target, or its newest version (section 6.2)    |
| `436 try later`            | The node is fetching it from a peer                  |
| `430 no such article`      | Not at the node or its peers: withdrawn, expired or never there |
| `503 not fetched here`     | The node does not fetch this group for its users     |

A node that does not know the command answers `500`, and the client
falls back to `ARTICLE <message-id>`.

## 6.2 What a Node Does

A node asked for a target:

1. **Holds it.** If it holds the target, it answers with it. If it
   holds a newer version that names the target in `Supersedes` (UN-RFC
   0042), it answers with that version. A node SHOULD keep, for as long
   as it keeps the newer version, which Message-IDs that version
   replaced, so that a share made before an edit still leads to the
   post.
2. **Knows it is gone.** If it has seen a valid cancel of the target,
   it answers `430`.
3. **Fetches it.** Otherwise it asks its peers whose `carries` covers
   the group (UN-RFC 0055 section 3.1) with `ARTICLE <message-id>`, at
   most three at a time, and answers `436` meanwhile. It holds the
   question for up to 10 seconds before answering `436`, as for
   key-bound groups (UN-RFC 0040 section 8), since over Tor a few
   seconds hardly show.
4. **Checks it** as any article (UN-RFC 0002 section 3): signature,
   postage, and that its `Newsgroups` is the group asked for. An
   article that fails is dropped and the node answers `430`.
5. **Keeps it in a cache, not in the group.** A fetched article from a
   group the node does not carry is kept for at most 24 hours. It is
   not added to the group, not listed, not offered to peers and not
   counted in what the node carries. After 24 hours it is fetched
   again if asked for, so that a withdrawal takes effect.
6. **Remembers misses** for some minutes, so that asking for random
   Message-IDs cannot make it flood its peers, and MAY limit how many
   fetches one session starts.

## 6.3 The Client

A client:

1. asks its own node with `XUN-FETCH`; on `436` it tries again after a
   few seconds, at most for a minute;
2. on `503`, or `430` from a node that does not carry the group, or no
   answer, asks another node whose `carries` covers `Share-Group`,
   chosen as UN-RFC 0055 section 7 says, before it gives up. A `430`
   from a node that carries the group is final;
3. checks the article itself, as UN-RFC 0042 section 4.1 says for
   edits: signature, `Newsgroups` equal to `Share-Group`, and either
   `Message-ID` equal to `Share-Of` or a valid newer version that names
   it in `Supersedes`. Anything else is shown as "not available"; a
   node is not trusted for this.

## 6.4 Operators

An operator MAY turn off fetching for groups outside what the node
carries, and SHOULD do so for groups it excludes on purpose (UN-RFC
0055 section 3.2); the node then answers `503`. That is the operator's
choice about their own machine, and it decides nothing about the
network: the client goes to another node (section 6.3). This is the
point of the section. A share must not be something one node can stop.

Infrastructure groups (UN-RFC 0055 section 4) are carried everywhere
and need no fetching.

# 7. Sharing into a Group

## 7.1 What It Is

A share can be written into another group than one's own feed: a
question from `dk.snak` brought to `dk.edb.linux`, a news post brought
to the group that discusses it. This is the good part of Usenet
crossposting, done from the reader's side.

It is not crossposting. `Newsgroups` still names one group (UN-RFC 0002
section 2.1). Each share into a group is an article of its own in that
group, so:

- it pays its own postage under that group's `min_pow` (UN-RFC 0006
  section 3) and needs a ripe key (UN-RFC 0025);
- it follows that group's rules for who may start a thread or entry
  (UN-RFC 0030); a share into a chat group is a chat line;
- the conversation about it stays where it is written. There are no
  answers spread over many groups and no `Followup-To` to argue about.

## 7.2 Limits

- A key MAY share one target into **at most three groups** besides its
  own feed and private sends (section 7.4). A client MUST NOT offer
  more, and SHOULD show which groups the target is already shared into
  by the user.
- A node that holds a share and finds that it already holds three
  other shares of the same target by the same key, in other groups than
  the sharer's own feed, SHOULD reject it.
- A group owner can refuse shares into the group with the manifest
  field `"share_into": false`. Nodes MUST reject a share, plain or with
  a comment, in such a group; clients MUST NOT offer the group. The
  default is `true`, except for groups with `"view": "chat"`, where it
  is `false` unless set.
- A share into a group MUST NOT be a plain share when the group has
  `"view": "threads"` or no `view`: a share into a discussion group
  needs a comment that says why it is brought there. Feeds take plain
  shares.

## 7.3 Spam Reports

Shares are articles and can be reported like any other (UN-RFC 0045).
An issuer MAY count shares of the same target by the same key across
the groups it sees, as Usenet's NoCeM issuers counted crossposts and
multiposts, and report keys that share widely.

## 7.4 Sending to One Person

A share MAY be sent in a private chat or as a private post (UN-RFC
0009, UN-RFC 0028): "look at this". It is encrypted like any private
article, with `Share-Of` and `Share-Group` inside the ciphertext, and
the receiver's client fetches the target as in section 6. Since the
target is open, this reveals nothing the receiver could not read. Such
sends do not count towards section 7.2 and send no notice (section 8).

# 8. Share Notices

An author SHOULD hear that their post was shared, as they hear that
they were mentioned (UN-RFC 0032). The notice is built and checked
exactly as a mention notice, with these differences:

| Header          | Value                                                     |
|-----------------|-----------------------------------------------------------|
| `Subject`       | The target's `Subject`, or `Share` for a chat line         |
| `Content-Type`  | `text/x-unseenet-share; charset=utf-8`                    |
| `Share-Of`      | The target's Message-ID                                    |
| `Share-Group`   | The target's Group ID                                      |
| `Shared-As`     | The share's Message-ID                                     |
| `Shared-In`     | The share's Group ID                                       |

`Mention-Group` and `Mention-Of` are absent. The body is one line, for
example `Andreas shared your post in his feed: Mit marsvin hoster`, and
MUST NOT contain the comment's text.

- **Writer's client.** It sends one notice per share into a feed or a
  group, by default, and lets the user turn it off for one share. It
  sends none for a private send (section 7.4), for a target by the
  sharer's own key, or for an author it cannot find an inbox for.
- **Receiver's client.** It checks the notice as UN-RFC 0032 section 5
  says, fetching the **share** (`Shared-As` in `Shared-In`) and
  discarding the notice unless the share's `Author-Key` is the notice's
  `Sender-Key` and its `Share-Of` names one of the receiver's articles.
  Share notices are **on** by default; a user can turn them off in
  their state (UN-RFC 0044, `share_notices`). A client shows them
  under *For you* with the other notices, never as a count.
- A notice tells the author who shared, which the share itself already
  says to everyone; it adds nothing that was private.

# 9. Gateways and Services

- **Out.** A gateway carrying a group to another network (UN-RFC 0023,
  0026) maps a plain share to that network's repost where the target is
  there too (a Nostr kind 6 repost, NIP-18), and a share with a comment
  to a quote (a Nostr note with a `q` tag). Otherwise it sends a note
  with the share's text and the target's address. It MUST NOT copy the
  target's text into the other network on the sharer's behalf.
- **In.** A repost or quote from another network becomes a share when
  the gateway carries the target, otherwise an ordinary post with a
  link. Share notices are not carried to or from other networks.
- **Bots and other services** (UN-RFC 0030 section 6) share through
  Session like any client. A bot SHOULD NOT share others' posts
  automatically unless that is what its channel says it does.

# 10. Rationale

**Why a reference.** See section 1: the author keeps control, expiry
works, and nothing is duplicated. The price is a fetch, and a fetch is
what Unseenet already does for blobs (UN-RFC 0027), manifests of
key-bound groups (UN-RFC 0040 section 8) and mention notices (UN-RFC
0032 section 5).

**Why nodes fetch from peers.** Once nodes may carry only part of the
network (UN-RFC 0055), a reference could become a way to hide things:
"not on this node". A node that fetches, and a client that goes to
another node when one will not, mean that what one operator chooses
for their own machine decides nothing for the network.

**Why the cache is short and separate.** A node that keeps what it
fetched as part of a group would carry, and forward, groups its
operator did not choose. A 24-hour cache that is never forwarded keeps
the operator's choice about what the node carries, and lets
withdrawals take effect.

**Why no crossposting.** One article in many groups needs one manifest
and one set of rules to decide whether it is accepted, which several
groups do not have; and its answers end up everywhere. A share per
group fits the rest of the protocol and costs per group.

**Why three groups.** It is enough to bring something to the two or
three places it belongs, and few enough that sharing everywhere is not
possible. Old Usenet policies drew the line at a similar number.

**Why no count.** A count turns sharing into a score, and a score
decides what people see. Unseenet shows what the reader chose, in the
order it was written (UN-RFC 0034 section 7).

**Why notices are on.** Being shared is something most people want to
know, and the share is public anyway. Those who don't want to know can
turn it off.

**Why "please don't share" is only a request.** Anything that can be
read can be copied. Calling the flag a protection would be a promise
Unseenet cannot keep.

# 11. Open Issues

- Section 7.2 requires a comment for a share into a discussion group,
  and makes chat groups refuse shares unless their owner allows them.
  Both are proposals, to be confirmed.
- Whether a node SHOULD keep fetched articles longer than 24 hours when
  many of its users ask for them, as a cache for popular shares.

# 12. Security and Privacy Considerations

- **Nothing closed leaks.** Clients do not offer to share encrypted
  articles (section 4.2), and a node that holds an encrypted target
  MUST reject a share of it. A `Share-Of` naming an encrypted article
  reveals only a Message-ID, which the share's readers cannot decrypt.
  A comment can still repeat what a closed group said; no protocol can
  stop a reader from doing that.
- **The sharer cannot fake the original.** The card is made from the
  target as fetched and checked by the reader (section 6.3), never from
  the share. A comment can misrepresent a post, but the post is shown
  as its author wrote it, and later edits are marked (section 5.1).
- **Withdrawals win.** A cancel removes the target from every share as
  soon as clients see it; caches on nodes expire within 24 hours.
- **What fetching reveals.** A node that fetches tells its peers that
  someone at it asked for an article, not who. A client that asks a
  node shows that node its interest, as reading anything does; nodes
  are reached over Tor.
- **Fetching as a lever.** Asking a node to fetch makes it hold, for a
  while, an article from a group its operator may not carry. The cache
  is not carried, not listed and not forwarded (section 6.2), and the
  operator may turn fetching off for groups outside what the node
  carries (section 6.4). Misses are remembered and fetches per session
  may be limited, so the command cannot be used to make a node flood
  its peers.
- **Shares as spam.** Every share pays postage and needs a ripe key;
  shares into groups are limited to three per target (section 7.2) and
  can be reported (section 7.3). Notices follow the rules of UN-RFC
  0032, including ignored senders.
- **A share is public.** It shows to everyone that the sharer read and
  passed on the target. Clients SHOULD make this as clear as for any
  post, and offer "Send to…" (section 7.4) for the private case.

# 13. Example

Andreas shares a post from `dk.snak` into his feed, and Mette shares it
with a comment:

```
Newsgroups: feed@5snjknxh...
Author-Key: ed25519:5snjknxh...
Message-Kind: share
Share-Of: <9f2e41@unseenet>
Share-Group: dk.snak@ph5f...
Subject:

unseenet:dk.snak@ph5f...?m=<9f2e41@unseenet>
```

```
Newsgroups: feed@q7ma2xw...
Author-Key: ed25519:q7ma2xw...
Message-Kind: chat
Share-Of: <9f2e41@unseenet>
Share-Group: dk.snak@ph5f...

Det her er præcis det, vi talte om i går 😂
```

A reader who follows both feeds sees the post once in the timeline,
"shared by Andreas", and Mette's comment as her own entry with the post
as a card under it. The author of the post gets two share notices. If
the author withdraws the post, Andreas's share disappears from feeds
and Mette's comment shows "withdrawn by its author" in place of the
card.

# 14. Changes to Other Documents

- UN-RFC 0002 section 2: the headers `Share-Of`, `Share-Group` and
  `Sharing` are added.
- UN-RFC 0004 section 3: the manifest fields `share_from` and
  `share_into` are added (sections 4.4 and 7.2).
- UN-RFC 0005: the command `XUN-FETCH` is added (section 6.1).
- UN-RFC 0028 section 3.1: the `Message-Kind` value `share` is added.
- UN-RFC 0032: share notices (section 8) are checked as mention
  notices are.
- UN-RFC 0034 sections 4 and 7: shares in feeds and the timeline
  (section 5).
- UN-RFC 0044 section 4.2: the settings `share_notices` and
  `hide_shares` are added.
- UN-RFC 0045: issuers may count shares across groups (section 7.3).
- UN-RFC 0046: the local API gains a call to fetch a target, answering
  `503 later` while the node fetches, and calls to share and to undo a
  share.
- UN-RFC 0055 section 7: clients go to another node for a target the
  way they do for a group.
- UN-RFC 0059 section 9: a shared target is shown with a card for an
  Unseenet address.
- UN-RFC 0000 section 6: 0060 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
