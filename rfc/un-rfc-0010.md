```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0010                                              October 2026
Category: Standards Track
Status: Draft

                  Unseenet: Lists of Known Nodes
```

# Abstract

A new client has to connect to some node before it can learn anything.
This document defines a **node list**: a small, signed JSON document naming
nodes, published as posts in a channel group. Clients ship with a list,
and once connected read the newest one from the network - signed by a
publisher they trust, and fetched over Tor through the node they already
use. It is a starting point, not a directory: any node can be used, and
anyone can publish a list.

# 1. Motivation

Usenet newcomers got a server name from their provider. Unseenet has no
providers, and an onion address cannot be guessed. Typing a 56-character
address is a poor first experience, and a list fetched from a web site
would tell the network that the computer uses Unseenet. The network can
carry the list itself: channel groups already let only chosen keys post,
and every post is signed.

# 2. The List

A node list is a JSON object, UTF-8:

| Field     | Type   | Req. | Meaning                                       |
|-----------|--------|------|-----------------------------------------------|
| `v`       | integer| yes  | `1`                                           |
| `updated` | string | no   | When the publisher last changed it (free text, e.g. a date) |
| `nodes`   | array  | yes  | Node entries, at most 200                     |

A node entry:

| Field         | Type       | Req. | Meaning                                         |
|---------------|------------|------|-------------------------------------------------|
| `address`     | string     | yes  | `<56 base32>.onion`, optionally `:port` (default 119) |
| `name`        | string     | no   | A short label, at most 64 characters            |
| `description` | string     | no   | At most 200 characters, shown to users          |
| `node_key`    | key string | no   | The node's key (UN-RFC 0016)                    |
| `operator`    | key string | no   | The operator's identity key (UN-RFC 0011)       |

Clients MUST ignore entries whose `address` is not valid, and unknown
fields, and MUST treat the whole list as invalid only if it is not JSON,
`v` is not 1, or no entry is usable. Addresses other than onion addresses
are allowed for testing; clients SHOULD NOT offer them to ordinary users.

# 3. Publishing

A **publisher** is an identity that owns a channel group (UN-RFC 0004
section 2) for its list. It publishes a list by posting it, as the whole
body of an ordinary article, to that group. The owner and the posters
named in the group's manifest may publish; nobody else can, because nodes
enforce the channel rule.

Each post is a complete list. The newest post, by its `Date` header,
counts; older ones are history.

A publisher SHOULD post its list again before the group's retention
period ends (RECOMMENDED: monthly), so that it never expires on nodes.

# 4. Reading

A client has one or more **trust anchors**: publisher keys, and for each
the Group ID of its list. The Group ID contains the fingerprint of the
owner key, so a client that pins the Group ID pins the owner too.

To read a list, a client:

1. fetches the group through a node it already uses (over Tor, as for any
   group);
2. checks that the group's current manifest has the pinned owner;
3. considers only articles whose signature is valid (UN-RFC 0002) and
   whose `Author-Key` is the owner or one of the manifest's `posters`;
4. takes the newest such article whose body is a valid list;
5. keeps it, so that it is available before the next connection.

A client that cannot read a list keeps the one it has, and otherwise uses
the list it was shipped with.

Clients SHOULD read lists without subscribing the user to the group and
SHOULD NOT keep the group's articles beyond the list itself.

# 5. Using the List

A client SHOULD offer the nodes of its list when the user has none yet,
and when the user adds a node, always together with a way to enter any
other address. A client MAY add further nodes from the list as fallbacks,
so that it can read groups from them when the first node is down.

A list says that its publisher vouches for an address. It does not make a
node trustworthy: nodes see what their clients read (UN-RFC 0005 section
7), whoever lists them.

# 6. The Project's List

The reference client pins one trust anchor, the Unseenet project:

- owner key `ed25519:det5dxevwbk36eds2indrzlazyri3fq3bgdzw6kx4ems3o267sya`
- list group `unseenet.nodes@ph5fc5hop5232qsz`

Its list is kept in the project's repository and changed by pull request;
an automated poster publishes it when it changes and every month. Its
announcements (releases, security notices) are in the channel
`unseenet.announce@ph5fc5hop5232qsz`.

This is a convenience of the reference client, not part of the protocol.
Other clients and users may pin other publishers, or none.

# 7. Security Considerations

- **Forged lists.** Only the pinned owner and the posters it names can
  publish, and clients check signatures and authors themselves; a node
  cannot inject a list. A node can withhold the newest list; the client
  then keeps an older one.
- **A stolen poster key** can publish a list that sends new users to
  hostile nodes until the owner removes the key from the manifest. Owners
  SHOULD give automated posters their own keys, and SHOULD keep the owner
  key offline.
- **Hostile nodes** in a list learn which groups their users read, as any
  node does. Clients SHOULD let users choose several nodes.
- **Privacy.** Lists travel inside Unseenet, over Tor. A client never
  needs to contact a web site to learn about nodes.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
