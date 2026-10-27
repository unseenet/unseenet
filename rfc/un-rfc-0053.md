```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0053                                              October 2026
Category: Standards Track
Status: Accepted
Updates: 0018, 0029, 0045, 0051

                 Unseenet: Content Labels
```

# Abstract

Readers should be able to choose not to see profanity, adult content,
violence or a spoiler - by their own choice, never by anyone else's
decision. Such content is legal and fine for many readers, so it must
not go through spam reports, which sanction. This document defines
content labels: words that **labellers** - people or programs - attach
to posts others wrote, in a channel of their own. A label only
describes. It never hides anything for anyone who did not choose that,
never removes anything from the network, and never changes postage,
ripening or what a node carries. Labels come in two kinds: **warnings**,
from the fixed set shared with an author's own tags (UN-RFC 0052), which
a reader's client blurs or hides as the reader chose; and **topics**,
which only feed the reader's own rules (UN-RFC 0051).

# 1. Motivation

UN-RFC 0052 lets an author tag their own post, and warn about it. Many
will not, and some posts come through gateways from networks with no
such habit. A labeller fills in what authors do not: a volunteer who
marks spoilers in a film group, a program that recognises profanity, a
hierarchy's own list of what is adult.

This must stay apart from spam reports (UN-RFC 0045). A report says
"this should not be here" and can make a node hide or delete a post and
make a key's postage dearer. A label says "this is what it is" and does
nothing on its own. If the two were one mechanism, a label would soon be
used to punish, and readers could not tell description from sanction.

# 2. Terms

Labeller
: A key that publishes labels, in its `labels@` channel (section 3).

Label
: A word a labeller attaches to a post: a warning or a topic.

Warning
: A label from the fixed set of UN-RFC 0052 section 4.

Topic
: Any other label: a tag word (UN-RFC 0052 section 3) saying what a
  post is about.

# 3. The Labeller's Channel

A labeller has a key-bound channel (UN-RFC 0029) named `labels`:
`labels@<fingerprint>`. Only its key posts there. Its manifest MAY hold

| Field       | Type    | Meaning                                         |
|-------------|---------|-------------------------------------------------|
| `policy`    | string  | What it labels and how, at most 2000 characters |
| `contact`   | string  | Where to object: an inbox or a URL, at most 512 |
| `automatic` | boolean | True if a program makes the labels              |
| `topics`    | boolean | True if it also labels topics (section 5)       |

The manifest is at most 4 KiB, as a `reports@` manifest (UN-RFC 0045
section 3). A node checks the channel like any key-bound channel.

# 4. Label Articles

A label article is a post in the labeller's channel, signed by its key,
`Content-Type: application/json`, holding

```json
{"v": 1,
 "posts": [{"id": "<x@y>", "group": "dk.film@ab3k...", "labels": ["spoiler"]},
           {"id": "<z@y>", "group": "alt.snak@cd4m...", "labels": ["profanity", "politics"]}],
 "note": "Spoilers for the new season"}
```

- `posts`: 1 to 1000 entries, each a post's Message-ID, its Group ID,
  and 1 to 8 labels, each a tag word (UN-RFC 0052 section 3), each once.
- `note`: optional, at most 200 characters, for people.

Entries that break these rules are left out, and the rest still count.
A post in an inbox is never labelled. A labeller withdraws a label
article as any post (UN-RFC 0042); what it said then no longer counts.
A newer label article about the same post replaces what the same
labeller said about it before: a labeller corrects a label by labelling
again, with `"labels": []` for none.

Labels name **posts only**, never keys. A label on a person - "usually
posts X" - would describe a person, not content; that is profiling, and
whoever wants to sanction a person has reports (UN-RFC 0045).

# 5. Who Follows Which Labeller

As for report issuers (UN-RFC 0045 section 7), with one difference
between the two kinds:

**Warnings** from a labeller count for a reader when:

- the reader follows the labeller;
- the hierarchy of the post's group names the labeller in its list
  (`labellers`, UN-RFC 0018, as `report_issuers`, at most 16); or
- the group's owner names the labeller in its manifest (`labellers`, as
  UN-RFC 0045 section 7.5, at most 16).

**Topics** from a labeller count only when the reader follows the
labeller *for topics* - their own choice, never a default. Nobody can
quietly categorise a hierarchy for everyone.

In every case the reader can turn a labeller off, and turning it off
turns it off wherever it was named for them. A reader's choices of
labellers are kept with their other settings (UN-RFC 0044).

# 6. What a Client Does

For each post the client knows the post's own warnings and tags (UN-RFC
0052) and the labels of the labellers that count for it (section 5).

- **Warnings**, the author's and labellers' alike: the reader chooses
  per warning - show, blur behind *Show anyway*, or hide. Clients SHOULD
  blur by default. Nothing is hidden or blurred silently: the post says
  which warning and, for a label, which labeller, one action from being
  shown. The reader's own posts and their contacts' are never blurred or
  hidden by labels.
- **Topics** are not shown as warnings. They are input to the reader's
  rules (UN-RFC 0051, `labelled`), and a client MAY show them near the
  post when the reader asks.
- Of several labellers labelling the same post, the client shows what
  each said; a warning counts if any labeller that counts gave it.

## 6.1 Age

Nobody on Unseenet needs to know a reader's age, and clients MUST NOT
ask for it to let anyone else know. Instead a client SHOULD offer, at
first start and beside profile editing, a short guide: which age group
the reader is in or is setting up for (for example under 13, 13 to 17,
adult), and which labellers and rules it suggests for it (for example
`hide if labelled sexual nudity gore` for the younger groups, blur for
adults).

The age itself is never stored, only the choices it led to, kept with
the reader's other settings (UN-RFC 0044, encrypted to the reader).
Nothing of it goes in a public profile or to a node. The reader can
change everything afterwards. A client MAY let a parent lock these
settings with a PIN on a child's device.

Groups open only to holders of an `adult` attestation (UN-RFC 0036) are
a separate tool for group owners.

# 7. Nodes

A node MUST NOT act on labels: it carries, hides, forwards, deletes and
prices posts exactly as it would without them, and labels MUST NOT
change postage or ripening (UN-RFC 0025). A node checks a `labels@`
channel and its articles as it checks any key-bound channel, and the
`labellers` field of a manifest as `report_issuers`.

## 7.1 Looking Up Labels and Reports

A reader that follows many labellers and issuers need not fetch their
whole channels. It asks its node which of their articles name the posts
it is about to show, then fetches only those and checks them as any
article. The node never answers with labels or reports themselves:
only with which signed articles to read, so it can withhold what it
does not want to give - as it always could - but never invent a label
or a report.

```
C: XUN-MARKS
C: channel <group-id>
C: channel <group-id>
C: post <message-id>
C: post <message-id>
C: key <key>
C: .
S: 297 <n> articles
S: <article-message-id> <channel-group-id>
S: ...
S: .
```

- `channel` lines name the `labels@` and `reports@` channels the reader
  follows, `post` lines the posts it shows - a page at a time, never one
  post as it is opened - and `key` lines their authors (for reports of
  keys, UN-RFC 0045 section 4). At most *max* lines in all, *max* at
  least 256; the same line MUST NOT appear twice.
- The answer lists every article in those channels that names one of
  the posts or keys and still counts (section 7.2): its Message-ID and
  its channel, at most 1024 lines, newest first.
- The client fetches those it does not hold (`ARTICLE`, or
  `XUN-MANIFESTS`-style batches where a node offers them), checks each
  as section 4 and UN-RFC 0045 section 4 say, and keeps them: the next
  page often needs the same articles.
- A node lists `UNSEENET-MARKS <max>` in `CAPABILITIES`. A client talking
  to a node without it, or about a channel the node does not carry,
  fetches that channel whole, as before.
- Asking tells the node nothing new: it serves the reader those posts,
  and which channels a reader follows is as visible to its node as
  which groups it reads.

To keep articles relevant to what readers ask about, a labeller or an
issuer SHOULD keep each article's posts within one top-level hierarchy
(`dk.*`, `alt.*`), and SHOULD publish often rather than in large
batches.

## 7.2 Entries Expire with Their Posts

A label means nothing once its post is gone. An entry naming a post
counts while the post is carried; an article whose posts are all gone
no longer counts, and a node MAY drop it. (A report of a key keeps its
`until`, UN-RFC 0045 section 4.) A channel then holds at most what the
network holds, instead of growing for ever.

# 8. Rationale

**Why apart from reports.** Reports sanction; labels describe. Mixing
them would let a description become a punishment, and readers could not
tell which was which.

**Why warnings may have defaults and topics not.** A new reader should
not have to find labellers before a spoiler is blurred, so whoever runs
a hierarchy or a group may name some for warnings. Topics categorise
people's speech; if a hierarchy could do that for everyone by default,
one maintainer could shape how a whole hierarchy is read.

**Why posts only.** See section 4.

**Why a fixed set of warnings.** A client offers a setting per warning;
with an open set a reader could never know what they chose not to see.

**Why age is never stored.** A stored age is a fact about a person that
leaks; the choices it leads to are all a client needs.

# 9. Security and Privacy Considerations

- Labels are public, like reports. A labeller says, in public, what it
  thinks posts are; it is answerable for that, and readers stop
  following one they disagree with.
- A wrong or hostile warning only blurs a post for those who follow the
  labeller, and says who did it; *Show anyway* is one action.
- Following a topic labeller is a choice that stays in the reader's
  encrypted settings.
- Illegal content, such as abuse material, is not a label: it is
  `illegal` in a spam report (UN-RFC 0045), and hierarchy and group bans.

# 10. Changes to Other Documents

- UN-RFC 0029 section 2: `labels` is a key-bound group name.
- UN-RFC 0018: a hierarchy list may hold `labellers` (section 5).
- UN-RFC 0045: reasons sanction; what a post contains is a label
  (section 4 there).
- UN-RFC 0051: the condition `labelled` (a separate amendment).
- UN-RFC 0045: looking reports up and their expiry (sections 7.1, 7.2
  here, 27 October 2026).

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
