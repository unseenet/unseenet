```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0005                                              October 2026
Category: Standards Track
Status: Draft

     ONNTP: Unseenet Transport and Peering over Onion Services
```

# Abstract

ONNTP is the wire protocol between Unseenet clients and nodes and
between nodes. It is a profile of NNTP (RFC 3977) with the streaming
extension (RFC 4644) and authentication (RFC 4643), carried over Tor
onion services. Existing newsreaders can be used with an Unseenet node
through a local SOCKS-capable connection.

# 1. Transport

1. A node MUST be reachable as a Tor v3 onion service. The ONNTP
   service MUST be on **virtual port 119**.
2. TLS and STARTTLS MUST NOT be required. Tor already provides
   encryption and authenticates the node by its onion address.
3. A node MUST NOT, by default, listen on any non-loopback interface.
   It MAY listen on loopback for local clients and testing.
4. Clients connect through Tor's SOCKS5 port with *remote* hostname
   resolution (SOCKS5 "domain name" address type). Clients MUST NOT
   resolve `.onion` names locally or via DNS.

# 2. Command Profile

## 2.1 Required Reader Commands

A node MUST implement: `CAPABILITIES`, `MODE READER`, `LIST ACTIVE`,
`LIST NEWSGROUPS`, `GROUP`, `LISTGROUP`, `ARTICLE`, `HEAD`, `BODY`,
`STAT`, `POST`, `NEWNEWS`, `DATE`, `HELP` and `QUIT`, as in RFC 3977.

## 2.2 Required Peering Commands

A node MUST implement `MODE STREAM`, `CHECK` and `TAKETHIS` (RFC 4644)
and `IHAVE` (RFC 3977).

## 2.3 Capabilities

The `CAPABILITIES` response MUST include:

```
VERSION 2
READER
POST
IHAVE
STREAMING
LIST ACTIVE NEWSGROUPS
NEWNEWS
UNSEENET 1
UNSEENET-MAXSIZE <octets>
UNSEENET-MINPOW <bits>
```

`UNSEENET-MAXSIZE` is the node's article size limit (UN-RFC 0002), and
`UNSEENET-MINPOW` its minimum postage (UN-RFC 0006). A client SHOULD
read both before posting.

## 2.4 Unsupported Commands

Commands not listed (e.g. `XOVER`, `OVER`, `XHDR`) MAY be implemented.
A node that does not implement a command MUST answer `500`.

# 3. Articles on the Wire

- Articles are sent exactly as defined in UN-RFC 0002, with NNTP
  dot-stuffing and the terminating `.` line.
- Between nodes, articles MUST be transmitted byte-for-byte as received
  (apart from dot-stuffing). A node MUST NOT add, remove or reorder
  headers when forwarding.
- When serving `ARTICLE` or `HEAD` to a **reader**, a node MAY add
  `Path: not-for-mail` and an `Xref` header for compatibility with
  existing newsreaders. These synthesized headers MUST be placed after
  the article's headers and MUST NOT be sent to peers. Clients MUST
  remove them before verifying a signature.
- Article numbers in `GROUP`, `LISTGROUP` and `ARTICLE <n>` are local
  to each node, as in NNTP.

# 4. Posting

`POST` follows RFC 3977. The node validates the article (UN-RFC 0002
section 5). On rejection it answers `441` followed by a short reason:

| Reason text prefix | Meaning                                    |
|--------------------|--------------------------------------------|
| `441 syntax`       | Malformed article                           |
| `441 signature`    | Signature or Message-ID invalid             |
| `441 postage`      | Insufficient proof-of-work                  |
| `441 group`        | Group unknown or not carried                |
| `441 permission`   | Not permitted by the group's manifest       |
| `441 duplicate`    | Already have it                             |
| `441 date`         | Date outside the accepted window            |
| `441 size`         | Too large                                   |
| `441 later`        | Not acceptable yet; post it again later (UN-RFC 0030) |

Because Message-IDs are content-derived, a client already knows the
Message-ID before posting and can retry safely: a repeated POST of the
same article is harmless.

# 5. Peering

## 5.1 Configuration

Peering is configured by node operators, per peer, with:

- the peer's onion address;
- the set of groups to send (a list of RFC 3977 wildmats over Group IDs,
  default `*`);
- optionally the set of groups to take from the peer (wildmats, default
  `*`); articles in other groups pushed or pulled from that peer are
  refused like articles in a group the node does not carry (`439`/`437`,
  reason `group`) and are not remembered as seen;
- optionally a shared secret for `AUTHINFO USER`/`AUTHINFO PASS`
  (RFC 4643). Over Tor, sending the password in plain text is acceptable.
  UN-RFC 0016 replaces the shared secret with node keys.

A node MAY refuse `IHAVE`, `CHECK` and `TAKETHIS` from connections that
have not authenticated as a configured peer, answering `480`.

## 5.2 Push: Streaming Feed

When a node accepts a new article (from a client or a peer), it queues
the Message-ID for every peer whose group set matches, except the peer
it came from. The feeding node:

1. connects, optionally authenticates, sends `MODE STREAM` (expects `203`);
2. sends `CHECK <id>` for queued articles (pipelining allowed);
3. on `238` sends `TAKETHIS <id>` followed by the article;
4. on `438` (not wanted) or `239`/`439` (TAKETHIS result) drops the ID
   from the queue; on `431` (try later) retries later.

Queues SHOULD survive restarts.

## 5.3 Pull: Catch-up

A node or client that has been offline catches up with

```
NEWNEWS <wildmat> <yyyymmdd> <hhmmss> GMT
```

and fetches unknown Message-IDs with `ARTICLE <id>`. Pull SHOULD be used
on (re)connection and MAY be the only mechanism for nodes that are
online only intermittently. UN-RFC 0017 specifies the details.

## 5.4 Loop Prevention

There is no Path header. Loops and duplicates are prevented solely by
the **history**: the set of Message-IDs a node has seen, including
rejected and cancelled ones. A node MUST keep a Message-ID in its
history at least as long as the longest retention period it applies,
plus 2 days. Articles older than that are rejected on `Date` (UN-RFC
0002 section 2.5), so they cannot loop back in.

## 5.5 Random Delay

To make it harder to tell where an article entered the network, a node
SHOULD delay forwarding each article by a random time (RECOMMENDED:
uniformly 0 to 60 seconds), independently per peer.

# 6. Limits

- Command lines MUST NOT exceed 512 octets.
- A node SHOULD close idle connections after 10 minutes.
- A node MAY limit the number of concurrent connections and POSTs per
  connection. Because Tor hides client addresses, per-address limits are
  impossible; postage (UN-RFC 0006) is the primary rate limit.
- A node that has as many client connections as it takes MAY answer the
  first command of a new connection with `400 too many connections, try
  another node` and close it. It SHOULD still let a connection
  authenticate as a peer first (`CAPABILITIES`, `AUTHINFO`, `XUN-PEER`,
  `XUN-PEER-PROOF`, UN-RFC 0016), and then serve it: peers do not count
  against the limit, so a full node keeps replicating. A client treats
  `400` like a node it cannot reach, and tries again later with a random
  backoff (UN-RFC 0043 section 4.4).

# 7. Security Considerations

- A node learns which groups a client reads. Clients that care SHOULD
  use several nodes and SHOULD fetch groups they are not interested in
  as cover, or simply subscribe to whole hierarchies.
- Peering reveals the topology to the peers involved, but not to others.
- Tor onion services can be subject to denial of service; Tor's own
  onion-service proof-of-work defense SHOULD be enabled on nodes where
  available.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
