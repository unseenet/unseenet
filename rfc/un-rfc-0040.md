```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0040                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0000, 0005, 0010, 0011, 0017, 0021, 0029

                  Unseenet: Key-bound Groups at Scale
```

# Abstract

Key-bound groups (UN-RFC 0029) are the part of the network that grows
with the number of **people**, not the number of topics: every identity
may have an inbox, a profile, a picture, a feed, a site and more. At the
design targets of UN-RFC 0001 section 1.2 that is several million
groups. This document stops listing them: they are left out of `LIST`,
out of the state part of `NEWNEWS` and out of the group counts that
decide whether a node is complete. Instead, nodes compare the
key-bound manifests they hold with **range-based set reconciliation**
(`XUN-RECONCILE`), whose cost grows with the number of differences, not
with the number of groups. The document also bounds what one key can
make every node carry.

# 1. Motivation

Several rules written for ordinary groups break when there are millions
of key-bound ones:

- `NEWNEWS` lists the state of **every** matching group first, whatever
  its age (UN-RFC 0017 section 3). A node pulling `NEWNEWS *` would get
  millions of manifest Message-IDs on every pull, before any posts.
- `LIST ACTIVE` and `LIST NEWSGROUPS` list every group: millions of lines
  for a reader that only wants groups it can join.
- A node is complete when it lists every group carried by the network
  (UN-RFC 0021 section 6), and the project's nodes must exchange all
  groups, verifiably (UN-RFC 0021 section 7). Comparing millions of
  names every day is not realistic, and those rules were meant to show
  which **topics** a node carries.

None of this is needed to find a key-bound group: its Group ID follows
from the owner's key (UN-RFC 0029 section 2). A client that knows a key
asks for `profile@<fp>` directly, alone or in a batch (unseenet #218).
What is needed is a cheap way for nodes to make sure they hold the same
set, and that is what this document adds.

# 2. Terms

Key-bound group
: As in UN-RFC 0029 section 2, including the names later documents add
  to its table (`feed`, `site`, `attest`, ...).

Ordinary group
: Any other group.

Key-bound state
: For each key-bound group a node carries, its current manifest
  (UN-RFC 0004 section 3.2). Articles posted *in* key-bound groups (inbox
  messages, feed posts, pages) are not state; they travel and expire as
  articles always do.

Item
: One entry of a node's key-bound state: the pair (*key*, *value*) where
  *key* = SHA-256(Group ID) and *value* = SHA-256(Message-ID of the
  current manifest), both 32 octets, written as 64 lowercase hex digits.

# 3. Not Listed

A node MUST leave key-bound groups out of:

- the answers to `LIST ACTIVE`, `LIST NEWSGROUPS` and `LIST ACTIVE.TIMES`,
  whatever the wildmat;
- part 1 (group state) of `NEWNEWS` (UN-RFC 0017 section 3, as updated in
  section 5);
- the groups it counts as carried, and the groups by which it is judged
  complete, in UN-RFC 0021 section 6 (see section 7).

A key-bound group is still fully reachable by its Group ID: `GROUP`,
`LISTGROUP`, `ARTICLE` and the other commands that name a group or an
article work as before, and so do peering wildmats over Group IDs
(UN-RFC 0005 section 5.1). Part 2 of `NEWNEWS` - articles received since
the given time - still includes everything received in key-bound groups,
manifests included, so peers that pull regularly keep up as before.

A client MUST NOT rely on listings to discover key-bound groups. It
derives their Group IDs from keys it has seen.

# 4. Reconciliation

## 4.1 What It Is For

Regular pulling (part 2 of `NEWNEWS`) and pushing keep peers in step
for everything that changes while both are up. Reconciliation covers
the rest:

- a **new node**, or one that was away longer than its peers' history,
  getting the key-bound state of the network;
- a **daily check** that two peers hold the same key-bound state,
  repairing what got lost;
- the **completeness** check of section 7.

Its cost is about the number of differences times the logarithm of the
number of items, not the number of items.

## 4.2 Ordering and Fingerprints

Items are ordered by *key* as an unsigned 256-bit number. Because *key*
is a hash, items spread evenly over the whole range.

A **range** is written `<lower> <upper>`: every item with
`lower <= key < upper`. `<lower>` and `<upper>` are 64 hex digits; the
upper bound of the last range is written `end`.

The **fingerprint** of a range is the first 16 octets of

```
SHA-256( count || sum )
```

where `count` is the number of items in the range as an unsigned 64-bit
big-endian number and `sum` is the sum of SHA-256(*key* || *value*) over
the items, each read as an unsigned 256-bit big-endian number, modulo
2^256, written as 32 octets big-endian. The sum lets a node keep
fingerprints up to date as items come and go, without recomputing a
range.

## 4.3 The XUN-RECONCILE Command

```
C: XUN-RECONCILE
C: <range lines>
C: .
S: 295 reconcile
S: <range lines>
S: .
```

A range line is one of

| Line                                      | Meaning                                            |
|-------------------------------------------|----------------------------------------------------|
| `<lower> <upper> F <fingerprint> <count>` | My fingerprint and item count for this range       |
| `<lower> <upper> L <n>` then `n` lines `<key> <Message-ID>` | My items in this range, all of them  |
| `<lower> <upper> =`                       | (answer only) This range is the same on both sides |

The ranges in one message MUST be in ascending order and MUST NOT
overlap.

The node answers each range it was sent:

- `F` with the same fingerprint and count: `=`.
- `F` that differs: if the node has at most 64 items in the range, it
  answers `L` with them; otherwise it splits the range into 16 equal
  parts by *key* and answers `F` for each.
- `L`: it answers `L` with its own items in that range (which may be
  none), and the exchange for that range is done.

The client continues with the ranges the answer did not settle (`F`
answers that differ from its own, using the same rule), until every
range is `=` or has been answered with `L` by both sides. Then each side
knows, for every differing range, the other's items **with their
Message-IDs**:

- an item whose *key* it lacks, or whose *value* differs, is fetched
  with `ARTICLE <Message-ID>` and accepted like any article - so a
  manifest with a lower serial than the one held is refused as usual
  (UN-RFC 0004 section 3.2), and nothing is accepted unchecked;
- an item it has that the other lacks may be offered with `IHAVE` or
  `CHECK`/`TAKETHIS` (UN-RFC 0005 section 5.2).

A first message normally holds one range, `0000...0000 end`. A node
MAY limit a message to 4096 range lines and one exchange to 64 rounds,
and answers `400` beyond that. A client that expects many differences -
a new node with an empty state - therefore works through the key space
a part at a time, one exchange per part, with parts small enough that
the listed items of one part fit the limit (with five million items:
one part per first two octets of *key*, about 76 items each). It can
tell how far apart the sides are from the counts in the first answer.
Fetching the articles is the real cost of a new node either way.

`XUN-RECONCILE` is advertised in `CAPABILITIES` as
`UNSEENET-RECONCILE 1`. A node SHOULD answer it without peer
authentication, so that anyone can check a node (section 7), and MAY
rate-limit unauthenticated use. Starting from an empty set, a client
can walk the whole key-bound state this way; section 10 says why that
reveals nothing that is not already public.

## 4.4 Example

Two nodes with five million items that differ in 100 of them: the
whole range differs and is split into 16, those into 256 (about 20 000
items each), of which about 80 differ; those are split twice more until
each differing range holds a handful of items, which are then listed.
That is five or six rounds and a few thousand short lines over one
connection - seconds over Tor, where listing would be about five million
lines. Two nodes that hold the same state settle it in one round with
one line each way.

# 5. NEWNEWS (Updates UN-RFC 0017)

Part 1 of the answer to `NEWNEWS` (UN-RFC 0017 section 3) lists the state
of every **ordinary** group the node carries that matches the wildmat,
whatever its age. Key-bound groups are left out of part 1. Parts 2 and 3
are unchanged and include key-bound groups: a manifest the node received
at or after the given time is listed in part 2, so a renewed profile
reaches a peer that pulls, as before.

# 6. Peers (Updates UN-RFC 0017 section 4)

A node that pulls from a peer which advertises `UNSEENET-RECONCILE`:

- MUST reconcile its key-bound state with that peer when it pulls from
  it for the first time, and when it has not pulled from it for longer
  than the peer keeps the record of what it received (in doubt: 7 days);
- SHOULD reconcile with each peer once a day, at a random time, and
  fetch what it lacks;
- otherwise pulls as before (parts 2 and 3 of `NEWNEWS`).

The reconciliation comes **before** `NEWNEWS`, so that the node holds
the state of key-bound groups before it is offered articles in them -
the same order part 1 of `NEWNEWS` gives ordinary groups.

A node offered an article in a key-bound group whose manifest it does
not hold - from a peer that cannot reconcile, or one changed meanwhile -
SHOULD fetch that manifest from the peer (with the batch lookup of
unseenet #218 where the peer has it) and then take the article, rather
than refuse it.

Peers that do not advertise `UNSEENET-RECONCILE` are pulled as before;
they then deliver key-bound state only as it changes.

# 7. Completeness (Updates UN-RFC 0021 sections 6 and 7)

UN-RFC 0021 section 6 counts and compares **ordinary** groups only. A
connected node is complete for a day when, in addition,

- it advertises `UNSEENET-RECONCILE`, and
- a reconciliation with a listed node that day shows that it lacks at
  most 0.1% of that node's items, or 100 items, whichever is more.

The allowance covers manifests still on their way. Where a node lacks
items, the checker can name the ranges, so the note to the operator of
UN-RFC 0021 section 7 says what is missing without a list of groups.
This is how the rule that the project's nodes exchange all groups,
verifiably, is checked for key-bound groups.

# 8. Partial Nodes (Updates UN-RFC 0011)

A small node - a Raspberry Pi at home - MAY carry the key-bound state
of only part of the key space. It says so in its node information
(UN-RFC 0011 section 3) with the new field

| Field       | Type                     | Meaning                                         |
|-------------|--------------------------|-------------------------------------------------|
| `key_bound` | `"all"` or array of strings | `"all"` (the default), or the hex prefixes of *key* it carries, e.g. `["0", "1", "a7"]` |

Such a node:

- MUST still carry the key-bound groups its own users need: their own,
  and those of the keys they ask for;
- when a client asks for a key-bound group it does not hold, SHOULD
  fetch its manifest from a peer at once (with the batch lookup of
  unseenet #218 where the peer has it) and answer when it has it;
- reconciles only the ranges it carries;
- is not complete in the sense of section 7, and so cannot be on the
  project's list of nodes (UN-RFC 0010).

# 9. What One Key Costs (Updates UN-RFC 0029)

UN-RFC 0000 section 4 asks for an upper bound per identity. The
key-bound state of one key is one manifest per key-bound group, and a
node MUST refuse (`441 size`) the manifest article of a key-bound group
larger than:

| Group        | Largest manifest article | Why                                          |
|--------------|--------------------------|----------------------------------------------|
| `inbox@`     | 8 KiB                    | Settings and the owner's own bans            |
| `feed@`      | 8 KiB                    | Settings (UN-RFC 0034)                        |
| `profile@`   | 12 KiB                   | Profile of at most 8192 octets (UN-RFC 0022 section 4.4) |
| `avatar@`    | 16 KiB                   | Picture of at most 8192 octets (UN-RFC 0022 section 8.1) |
| `names@`     | 64 KiB                   | Issuers only (UN-RFC 0019)                    |
| `attest@`    | 64 KiB                   | Issuers only; revocations are sharded (UN-RFC 0036 section 7) |
| `site@`      | 64 KiB                   | Only where the operator carries sites (UN-RFC 0035) |

So an ordinary person costs every full node at most 44 KiB of state
(inbox, feed, profile, picture), and typically a few KiB; an issuer or a
site owner at most 236 KiB more. Articles posted in key-bound groups are
not state: they are limited by size, postage and retention like every
article. A key-bound group that is not renewed expires (UN-RFC 0029
section 5), so what a node carries follows the number of **active**
identities, not of every key ever seen.

# 10. Security and Privacy Considerations

- **Nothing new becomes public.** Key-bound manifests are public and
  flooded to every full node; anyone who runs a node holds them all
  today, and `LIST ACTIVE` lists them today. Leaving them out of
  listings does not hide them, and walking them with `XUN-RECONCILE`
  (section 4.3) reveals nothing a node operator does not already have.
  What the document protects is the cost of routine operations, not a
  secret. A user who does not want to be found by key does not publish
  a profile (UN-RFC 0022 section 13).
- **Nothing is accepted on a peer's word.** Reconciliation only tells a
  node which Message-IDs to fetch. Every manifest is then checked like
  any article: signature, postage, serial, `expires`.
- **Forged fingerprints.** A peer that lies in `F` lines can at worst
  make the other fetch articles it already has, or miss differences in
  that exchange; the daily check with other peers catches the second.
  The fingerprint is not a security mechanism, only a summary.
- **Cost attacks.** A client could open many exchanges or send wide
  `L` lists. The limits of section 4.3 and rate limits for
  unauthenticated use bound the work per connection; the fingerprints of
  ranges are kept as running sums, so answering `F` is a lookup.
- **Scale.** At the targets of UN-RFC 0001 section 1.2, with one million
  active identities and about four key-bound groups each:
  - state: typically a few GB per full node, at most about 44 GB for
    ordinary identities (section 9);
  - the item index: key, value and Message-ID, about 130 octets each,
    some 500 MB;
  - renewals (UN-RFC 0029 section 4): about four million manifests per
    545 days, some 7 000 a day - well under a manifest a second;
  - a daily reconciliation between two peers in step: one round, two
    lines; with a hundred differences, five or six rounds;
  - clients: nothing grows with the number of identities, since a
    client never lists key-bound groups.

# 11. Rationale

- **Why reconciliation and not a list with dates?** A "changed since"
  list (part 2 of `NEWNEWS`) is already there and stays. It cannot
  repair what was lost, nor bring a new node up to date, nor show that
  two nodes hold the same set; reconciliation does all three at a cost
  that follows the differences.
- **Why this algorithm?** Range-based reconciliation with additive
  fingerprints, as in Negentropy (used by Nostr relays), needs no state
  per peer, works in a few rounds over one connection and is simple to
  implement on a sorted index. The parameters (16-way split, lists of at
  most 64 items) keep each round small over Tor.
- **Why hash the Group ID?** So items spread evenly over the key space,
  ranges split evenly, and partial nodes (section 8) carry even shares.
- **Why limits per group in section 9?** The rule of UN-RFC 0000 section
  4 asks for a bound per identity, and the article limit of 64 KiB alone
  would allow 448 KiB per key - too much at a million keys for a full
  node on a free-tier VM.

# 12. Open Issues

- The limits of section 9 are first estimates and should be checked
  against real manifests with the load generator (unseenet #219) before
  this document leaves Draft.
- Whether a partial node should answer a missing key-bound group at
  once with `411` and fetch it in the background, or hold the answer
  for a few seconds while it fetches (section 8).
- Whether the completeness allowance of section 7 should be measured
  twice, some hours apart, to tell a lagging node from a missing one.

# 13. Changes to Other Documents

- **UN-RFC 0005** section 2: `LIST ACTIVE`, `LIST NEWSGROUPS` and
  `LIST ACTIVE.TIMES` leave out key-bound groups (section 3);
  `CAPABILITIES` may list `UNSEENET-RECONCILE 1`, and the command
  `XUN-RECONCILE` is added (section 4.3).
- **UN-RFC 0010** and **0021** sections 6 and 7: completeness counts
  ordinary groups, and key-bound state is checked by reconciliation
  (section 7).
- **UN-RFC 0011** section 3: the node information field `key_bound`
  (section 8).
- **UN-RFC 0017** sections 3 and 4: part 1 of `NEWNEWS` covers ordinary
  groups; peers reconcile key-bound state (sections 5 and 6).
- **UN-RFC 0029** section 2: the limits per key-bound group (section 9);
  a later document that adds a key-bound group adds its limit there.
- **UN-RFC 0000** section 6: 0040 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
