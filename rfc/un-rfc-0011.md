```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0011                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0005

          Unseenet: Node Information and Operator Contact
```

# Abstract

A node tells clients and peers who operates it, how to reach the
operator privately, and what its policies are. This document defines
the `LIST UNSEENET.NODEINFO` command and the information it returns.

# 1. Motivation

On Usenet every server had an administrator reachable at a well-known
address (`usenet@`, `news@`). Unseenet nodes are onion services with no
domain and no mail, so the same need must be met inside the protocol:
users must be able to report abuse, ask for a group to be carried, or
just say thank you, and they should be able to see a node's policy
before relying on it.

# 2. The NODEINFO Command

A node that implements this document adds the capability

```
UNSEENET-NODEINFO
```

and answers

```
LIST UNSEENET.NODEINFO
```

with `215` followed by a single line of canonical JSON (UN-RFC 0004
section 3) and the terminating `.`:

```
215 node information follows
{"contact":"operator@ab3k5x7qwe2rtz4m","description":"...","name":"mynode","operator":"ed25519:...","policy":{...},"software":"unseenet 0.2.0","v":1}
.
```

A node that has no information to give MAY omit the capability.

# 3. Fields

| Field         | Type        | Req. | Meaning                                                  |
|---------------|-------------|------|----------------------------------------------------------|
| `v`           | integer     | yes  | `1`                                                      |
| `name`        | string      | yes  | The node's name (as used for peering, UN-RFC 0005)       |
| `operator`    | key string  | no   | The operator's identity key                              |
| `contact`     | Group ID    | no   | Where to write to the operator; SHOULD be an inbox       |
| `description` | string      | no   | Free text, max 2048 characters                           |
| `policy`      | object      | yes  | See section 4                                            |
| `software`    | string      | no   | Implementation name and version                          |

Unknown fields MUST be ignored.

# 4. Policy

The `policy` object states the rules the node applies. Clients SHOULD
show it to users when they add a node.

| Field            | Type    | Meaning                                                    |
|------------------|---------|------------------------------------------------------------|
| `new_groups`     | string  | `accept`, `trusted` or `manual` (UN-RFC 0004 section 3.3) |
| `min_pow`        | integer | Minimum postage                                            |
| `retention_days` | integer | How long posts are kept                                    |
| `max_size`       | integer | Largest accepted article                                   |
| `logging`        | string  | Free text: what the node logs                              |
| `archive`        | boolean | Whether the node keeps posts longer (UN-RFC 0012)          |
| `honours_blocks` | boolean | Whether it refuses posts by identities blocked by hierarchy maintainers (UN-RFC 0018 section 8.2) |

# 5. The Operator's Contact Inbox

The RECOMMENDED way to set up operator contact is:

1. the operator creates, with an identity of their own, an **inbox**
   group (UN-RFC 0009) with `"local": true`, conventionally named
   `operator`, on their own node;
2. the operator puts its Group ID in `contact` and the identity in
   `operator`.

Because the inbox is local, messages to the operator stay on that node.
Because it is an inbox, the node itself - and anyone who seizes it -
cannot read them; only the operator's identity can.

# 6. Trust

The information is not signed. It does not need to be: the client
reached the node through its onion address, which authenticates the
node (UN-RFC 0005 section 1), so the information comes from the node it
claims to describe. It is, however, only what the node *claims*:
a client SHOULD present the policy as the operator's statement, not as
something the protocol enforces.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
