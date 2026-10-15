```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0001                                              October 2026
Category: Informational
Status: Draft

                Unseenet: Architecture and Terminology
```

# Abstract

Unseenet is a decentralized discussion network modeled on Usenet,
carried over Tor onion services, with signed articles, optional
end-to-end encrypted groups and proof-of-work spam resistance. This
document describes the overall architecture and defines common terms.
It is non-normative; the normative rules are in UN-RFC 0002 to 0006.

# 1. Goals

1. **Easy access.** A person should be able to join groups and chats by
   running a single program, e.g. from a USB stick, with no installation,
   no account registration, no public IP and no port forwarding.
2. **Decentralization.** No central server, registry or company. Anyone
   can run a node; nodes replicate groups to each other the way Usenet
   servers did.
3. **Confidentiality where wanted.** Closed groups are end-to-end
   encrypted; nodes carry ciphertext they cannot read.
4. **Resilience to seizure.** A seized node or USB stick should reveal as
   little as possible (see UN-RFC 0007).
5. **Open protocol.** Anybody can write a compatible node or client from
   these documents alone.

## 1.1 Non-Goals

- **Binary file distribution.** Unseenet is a text network. Articles are
  small (UN-RFC 0002 sets a default limit of 64 KiB). This keeps storage
  bounded and limits node operators' legal exposure.
- **Global consensus.** There is no global list of groups or users. Each
  node carries what its operator chooses.
- **Perfect anonymity against a global adversary.** Unseenet inherits
  Tor's threat model and does not improve on it.

# 2. Terminology

Node
: A long-running server, reachable as a Tor onion service, that stores
  articles and replicates them to other nodes. Comparable to a Usenet
  news server or an old BBS.

Client
: A program a person uses to read and post. It connects to one or more
  nodes over Tor. Typically portable (USB) and stores its data encrypted.

Peer
: Another node with which a node exchanges articles.

Feed
: The stream of articles a node offers to a peer.

Article
: The unit of content. A header block and a body, signed by its author
  (UN-RFC 0002).

Identity
: An Ed25519 key pair. The public key *is* the identity; display names
  are just labels (UN-RFC 0003).

Group
: A named stream of articles, owned by an identity and described by a
  signed manifest (UN-RFC 0004).

Manifest
: A signed control article that defines a group's name, type, owner,
  moderators and policy.

Group ID
: The globally unique name of a group: a human-readable name plus a
  fingerprint of the owner's key, e.g. `dk.snak@ab3k5x7qwe2rtz4m`.

Closed group
: A group whose article bodies and sensitive headers are encrypted with
  a key shared only among members.

Postage
: A proof-of-work value attached to an article to make mass posting
  expensive (UN-RFC 0006).

# 3. Architecture

```
  +--------+        Tor         +--------+   Tor (peering)  +--------+
  | Client | <----------------> | Node A | <--------------> | Node B |
  +--------+   ONNTP reader      +--------+                  +--------+
   (USB)                             ^                           ^
                                     |       Tor (peering)       |
                                     +-------> +--------+ <------+
                                               | Node C |
                                               +--------+
```

- Every node is a Tor **onion service**. Its `.onion` address is derived
  from its service key, so the address itself authenticates the node.
  No TLS, certificates or DNS are needed.
- Clients and nodes speak **ONNTP** (UN-RFC 0005): a strict subset of
  NNTP (RFC 3977) with streaming feeds (RFC 4644), over Tor.
- Nodes replicate articles by **flood-fill**: when a node accepts a new
  article it offers it to all peers that carry the group. Duplicate
  suppression uses the Message-ID, which is a hash of the article's
  content (UN-RFC 0002), so it cannot be forged or collide by accident.
- Unlike Usenet, there is **no Path header**. The route an article took
  is not recorded, because it leaks where an article entered the network.

# 4. The Three Authorities

Unseenet deliberately splits control between three parties, so that no
single party decides everything:

| Party        | Decides                                                      |
|--------------|--------------------------------------------------------------|
| Group owner  | Group type, who may post, who may read (closed groups), moderators |
| Node operator| Which groups and peers the node carries, retention, minimum postage |
| Reader       | What they see: filters, trust, which identities to ignore    |

A group owner cannot force a node to carry a group. A node operator
cannot forge or alter articles (they are signed) and cannot read closed
groups. A reader can always hide content locally.

# 5. Group Types (summary)

| Type      | Read          | Post                                    | Encrypted |
|-----------|---------------|-----------------------------------------|-----------|
| open      | anyone        | anyone (signed, with postage)           | no        |
| moderated | anyone        | moderators, or with moderator approval  | no        |
| channel   | anyone        | owner and listed posters only           | no        |
| closed    | members only  | members only                            | yes, E2E  |

"Chats" are, in this first series, closed (or open) groups with short
retention, used by clients in a conversational way. A low-latency
delivery mechanism is reserved for UN-RFC 0008.

# 6. Relationship to Usenet

What is kept: hierarchical group names, a store-and-forward network of
independently operated servers, NNTP as the wire protocol, Message-IDs,
References threading, the freedom of each server to choose its feeds.

What is changed: articles are signed; groups are owned and their
control messages are signed (no forged `newgroup`/`rmgroup`/`cancel`);
Message-IDs are content hashes; there is no Path; transport is Tor;
closed groups are encrypted; spam is priced with proof-of-work.

# 7. Security Considerations

See UN-RFC 0003 (cryptography), 0004 (group access), 0006 (spam) and
0007 (data at rest). Briefly: content confidentiality is only provided
for closed groups; metadata (group ID, size, approximate time,
author key) is visible to nodes for all articles.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
