```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0012                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.5.0
Updates: 0002, 0004, 0005

            Unseenet: Retention, Archive Nodes and History
```

# Abstract

This document separates two things that UN-RFC 0002 and 0004 mix: how
long a post **travels** between nodes, and how long a node **keeps** it.
Posts travel only within a bounded replication window, so the network
never carries old traffic. Archive nodes may keep posts much longer and
serve them to readers, and owners and authors can ask archives not to
keep their posts.

# 1. Motivation

Without a bound, a network that runs for years would keep offering old
posts to every new node and peer, and storage would only grow. With a
bound and nothing else, history would simply disappear. Usenet solved
this with expiry on ordinary servers and a few archives (and the
`X-No-Archive` header for people who did not want to be archived). This
document does the same.

# 2. Terms

Replication window
: The age up to which a post is accepted from others and passed on.

Retention
: How long a node keeps a post before deleting it.

For an ordinary node they are the same. For an archive node, retention
is longer.

# 3. Replication Window

The replication window of a group at a node is

```
window = min( node retention_days, group retention_days )
```

where the group value is the manifest's `retention_days` (UN-RFC 0004
section 3.1, default 90).

A node MUST reject an article whose `Date` is older than the window, and
MUST NOT offer such an article to peers. This is what keeps old posts
from circulating: whatever happens, nothing older than the window moves
between nodes (except under section 5.3).

The `retention_days` of a manifest is therefore the owner's statement of
how long posts should **circulate**. UN-RFC 0004 called it a suggestion;
this document makes it binding for replication and advisory for archives.

# 4. Ordinary Nodes

An ordinary node deletes articles once they are older than the window,
and keeps their Message-IDs in its history at least two days longer
(UN-RFC 0005 section 5.4). Manifests and key control articles are never
deleted while the group is carried.

# 5. Archive Nodes

## 5.1 Keeping Posts

An archive node keeps articles longer than the window - possibly
forever - and serves them to readers with the ordinary commands
(`GROUP`, `ARTICLE`, `LISTGROUP`). It announces this with
`"archive": true` in its node information (UN-RFC 0011).

Closed-group and inbox articles are archived as received, i.e. encrypted.

## 5.2 Opting Out

- A manifest field `"archive": false` asks archive nodes to keep the
  group's posts no longer than its window.
- An article header `No-Archive: yes` asks the same for that article.
  The header is covered by the signature, so only the author can set it.

Archive nodes MUST honor both. This cannot be enforced technically -
anybody can copy what they can read - but it is a clear statement of
the author's and owner's wishes, and well-behaved software follows it.
Archive operators SHOULD state their adherence in their policy.

## 5.3 Backfilling Between Archives

Two archive nodes MAY exchange old articles to fill each other's gaps.
This MUST be explicitly configured on both sides for that peer (an
"archive peering"), and only then is the replication window waived for
articles received from that peer. Such articles MUST NOT be passed on to
ordinary peers.

Archive peering uses the pull method of UN-RFC 0005 section 5.3 with
`NEWNEWS` and `ARTICLE`. A later document may define a more efficient
range transfer.

# 6. Reading History

A client that wants older posts than its node holds can connect to an
archive node and read the group there. Because article numbers are
local to each node, the client identifies posts by Message-ID when
combining what it reads from several nodes.

# 7. Considerations

- Archives make history durable, which is valuable and also a risk to
  people who later regret what they wrote. Section 5.2 gives authors a
  choice; clients SHOULD make `No-Archive` easy to set, and MAY set it by
  default in some groups.
- An archive of closed groups protects nothing new and exposes nothing
  new: it holds ciphertext that only past and present members can read.
  It does mean that a compromised group secret exposes the archived
  history of that epoch.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
