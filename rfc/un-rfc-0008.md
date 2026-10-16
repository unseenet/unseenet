```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0008                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0004, 0005

          Unseenet: Chat Groups and Low-Latency Delivery
```

# Abstract

Unseenet was designed for discussion, where a minute does not matter.
Chat needs seconds. This document lets a client be told about new
articles as soon as its node has them (`XUN-WATCH`), and lets a group's
owner mark the group as a chat, so that nodes forward its articles
without the random delay of UN-RFC 0005 section 5.5 and clients show it
as a conversation.

# 1. Where the Time Goes

Without this document, an article posted in one place reaches a reader
elsewhere after:

1. the poster's proof-of-work (about a second at 20 bits, UN-RFC 0006);
2. up to 60 seconds of random delay at each node (UN-RFC 0005 section 5.5);
3. the reader's next poll of their node.

Section 2 removes the third, section 3 the second, and section 4 lets
owners lower the first.

# 2. Watching for New Articles

## 2.1 Capability

A node that implements this section adds the capability

```
UNSEENET-WATCH
```

## 2.2 The XUN-WATCH Command

```
XUN-WATCH <wildmat>
```

The node answers `290 watching` and from then on sends one line for
every article it accepts in a group matching the wildmat:

```
291 <group-id> <article-number> <message-id>
```

The client ends watching by sending a line `DONE`; the node answers
`292 done` and the connection returns to normal command mode. While
watching, the client MUST NOT send other commands. A client that wants
to read and watch at the same time opens a second connection.

The node SHOULD send `293 keepalive` after 5 minutes without other
output, so that clients and Tor can tell a quiet connection from a dead
one.

## 2.3 Privacy

The wildmat tells the node which groups the client follows - which it
learns anyway when the client reads them. Clients SHOULD watch the same
groups they read and nothing more specific.

# 3. Chat Groups

## 3.1 Manifest Fields

UN-RFC 0004 section 3.1 is extended with:

| Field         | Type    | Default     | Meaning                                         |
|---------------|---------|-------------|-------------------------------------------------|
| `view`        | string  | `"threads"` | How clients show the group: `threads`, `chat` or `data` |
| `low_latency` | boolean | `false`     | Nodes forward without random delay              |

`view` is a hint. Readers may switch views; clients SHOULD remember a
reader's choice per group. A client that does not know a group's `view`
MUST show it as `threads`. The owner MAY change `view` in a later
manifest; unlike the type, it is not fixed at creation.

## 3.1.1 Data Groups

A group with `"view": "data"` carries articles for programs rather than
for people: lists, certificates and the like, usually as JSON, such as
the node list (UN-RFC 0010), the root list of hierarchies (UN-RFC 0018)
and name certificates (UN-RFC 0019). Clients:

- SHOULD NOT offer data groups when a reader browses groups to join, and
  SHOULD NOT count them as unread. A client knows a group is a data group
  from its manifest; a client MAY also ship with a list of well-known data
  groups, such as the project's, so that it can hide them before it has
  read their manifests, and SHOULD mark any other as a data group as soon
  as it learns its manifest;
- read them in the background when they need what they carry, without
  subscribing the reader;
- MAY let a reader open one anyway, shown as `threads`, and SHOULD then
  mark it as a data group.

`data` says nothing about who may post; that is the group's type. A data
group is usually a channel. Nodes treat it like any other group.

## 3.2 Forwarding

A node MUST NOT apply the random forwarding delay of UN-RFC 0005 section
5.5 to articles in a group with `"low_latency": true`. It SHOULD forward
them as soon as they are accepted.

## 3.3 The Trade-off

The random delay makes it harder for someone watching several nodes to
tell where an article entered the network. A low-latency group gives
that up for speed. Clients MUST make it visible that a group is
low-latency, and owners SHOULD only enable it for groups where the
members accept this, such as a chat among friends.

Closed-group content stays end-to-end encrypted in any case; what is
weakened is only the protection of *who posted from where*.

# 4. Postage in Chat Groups

Proof-of-work per message is felt in a chat. Owners of chat groups MAY
set a lower `min_pow`; clients MUST compute the postage they attach as

```
max( node's UNSEENET-MINPOW, group's min_pow )
```

rather than a fixed value, so that a lower group minimum actually makes
posting faster. Nodes still apply their own minimum (UN-RFC 0006 section 3).

# 5. Chat View (Informative)

A chat view shows a group's articles in order of arrival, newest last,
as `Name: text`, without subjects or threads, with a single input line.
Articles sent from a chat view carry an automatic `Subject` (e.g. the
first words of the text) so that thread views and other clients still
show something meaningful, and no signature.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
