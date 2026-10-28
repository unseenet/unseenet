```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0021                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.3.0
Updates: 0010, 0011, 0020

            Unseenet: Listed Nodes Must Be Connected
```

# Abstract

A node list (UN-RFC 0010) offers nodes to new users. Today a node is
listed if it answers and proves its node key; nothing says it shares
posts with anyone. A listed node that peers with nobody is an island: a
new user who picks it sees only its own posts, and nobody else sees
theirs. This document adds two conditions for the project's list - a
listed node must exchange posts with the other listed nodes in both
directions, and must carry the groups they carry, except groups it
openly excludes - and a way to check both from outside, with small
daily **canary** posts. It adds an `excludes` field to node information
(UN-RFC 0011), so that a node can say which groups it leaves out.

# 1. Motivation

Peering is agreed between operators, one pair at a time (UN-RFC 0005
section 5.1), and is invisible from outside. Being on a node list does
not peer a node with anyone. An operator can therefore be listed, with
the best intentions, and never peer: the check sees a node that answers
and is satisfied.

Asking operators which nodes they peer with does not help: the answer
cannot be checked, peerings change, and a node can be well connected
through a node that is not listed. What users need is the effect -
posts written on any listed node reach every other listed node - and
that can be checked by posting and looking.

# 2. Terms

- **Listed node**: a node on the steward's node list.
- **Checker**: the program that checks listed nodes for the steward:
  today the GitHub workflow, under UN-RFC 0020 each replica.
- **Canary**: a small article the checker posts to one listed node, to
  see where it arrives.
- **In the network**: a canary is in the network when, at the next
  check, more than half of the listed nodes that answered have it, the
  node it was posted to included.

# 3. Excluded Groups (Updates UN-RFC 0011)

UN-RFC 0011 section 4 gets a new policy field:

| Field      | Type   | Meaning                                                |
|------------|--------|--------------------------------------------------------|
| `excludes` | string | RFC 3977 wildmat over Group IDs: groups the node does not carry by choice. Absent or `""`: none. |

A node that sets `excludes` MUST refuse articles in matching groups,
from clients and peers alike, as it refuses groups it does not carry
(UN-RFC 0005 section 5.1, reason `group`). It SHOULD add the Group ID of
every group its operator has dropped (UN-RFC 0013 section 3), so that
dropping a group never needs a second step.

Clients SHOULD show `excludes` with the rest of the policy when a user
adds a node. It tells users what they will not find there, and lets an
operator carry less than everything - for example because the law where
the node runs forbids some content - and still be listed.

# 4. Canaries

The steward owns a channel group for canaries, data view (UN-RFC 0008
section 3.1.1), whose posters are the checker keys. The project's is
`unseenet.canary@ph5fc5hop5232qsz`.

A canary is an ordinary signed article in that group:

- `Subject`: `canary <node name> <date>`;
- body: canonical JSON (UN-RFC 0004 section 3):

| Field   | Type       | Req. | Meaning                                   |
|---------|------------|------|-------------------------------------------|
| `v`     | integer    | yes  | `1`                                       |
| `node`  | key string | yes  | The node key of the node it was posted to |
| `date`  | string     | yes  | The UTC day, `YYYY-MM-DD`                 |
| `nonce` | string     | yes  | 16 random bytes, base64url               |

The nonce makes every canary a new article; a node cannot answer for a
canary before it exists.

Once each UTC day the checker:

1. **reads**: for every listed node that answers, which canaries of the
   previous UTC day it has (`NEWNEWS` or `OVER` on the canary group);
2. **posts**: a new canary to **each** listed node, with `POST` to that
   node alone. A node that refuses it - for example because the
   canary's postage is below its `min_pow` - has a problem to fix, and
   the refusal is noted.

From the readings it makes a matrix: canary posted to A, seen at B. A
day's delay is generous: it covers the random push delay (UN-RFC 0005
section 5.5), a peer that was briefly down, and hourly catch-up pulls
(UN-RFC 0017).

# 5. Connected

A listed node that answered is **connected** for a day when

- **outgoing**: its canary of the previous day is in the network; and
- **incoming**: it has every canary of the previous day that is in the
  network.

The majority in "in the network" matters. With nodes A and B peered
with each other and C and D with each other, but no peering between the
pairs, every node would see one canary besides its own; requiring more
than half makes both halves fail, and the operators can see why. A list
with one node is connected by definition.

How a node is connected is not checked: peering with one listed node is
the usual way, but a path through nodes that are not listed counts too.
Pulling alone (UN-RFC 0017) gets canaries in; a node must also push, or
be pulled from, for its own canary to get out.

# 6. Carrying the Groups

A group is **carried by the network** on a day when more than half of
the connected nodes list it in `LIST ACTIVE`. A connected node is
**complete** for that day when it lists every group carried by the
network that does not match its `excludes`.

The groups of the steward's own hierarchy (for the project, `unseenet.*`)
carry the lists, names and announcements that clients need. A node whose
`excludes` matches any of them is not complete.

# 7. The Rule for the Project's List (Updates UN-RFC 0010 and 0020)

UN-RFC 0010 section 6 gets two more conditions. The project lists a
node, and keeps it listed, only if

- it is connected (section 5); and
- it is complete (section 6).

At request time the checker posts a canary to the new node and one to a
listed node, and waits up to an hour for each to appear on the other
side. The request form asks which listed nodes the operator peers with;
the answer only helps the operator and the steward, it is not checked.
Until a second node is listed, the first node's own request needs no
canary check.

After that, the same timing as for reachability applies: a node that is
not connected, or not complete, for 3 days in a row gets a note to its
operator, saying which canaries it is missing or which groups; after 10
days it is taken off the list. A node that the checker could not reach
on a day gets no verdict for connection that day; reachability rules
apply.

Under UN-RFC 0020, the `health <date>` report (section 9) gets two
optional fields, and "down" is extended accordingly:

| Field          | Type          | Meaning                                   |
|----------------|---------------|-------------------------------------------|
| `disconnected` | array of keys | Node keys reached but not connected       |
| `incomplete`   | array of keys | Node keys connected but not complete      |

A node counts as down if, for each of the last 10 completed UTC days, at
least one replica reported on it and none reported it reached,
connected and complete.

# 8. Rationale

- **Why canaries, not peer lists?** A peer list says what an operator
  configured; a canary shows what happens. It catches wrong keys, peers
  that do not list the node back (UN-RFC 0016), patterns that leave out
  groups, and peers that are gone.
- **Why a majority?** "Seen by at least one other node" passes two
  separate halves of the network. "Seen by all" fails everybody when one
  node is broken. A majority fails the minority and keeps a broken node
  from failing the rest.
- **Why all groups?** New users are told nothing about what a node
  leaves out; they assume the network is what their node shows. A node
  that carries less is fine, but it must say so (`excludes`), and the
  majority rule means a group only counts once most of the network has
  taken it.
- **Why not leave this to operators?** They should still decide whom to
  peer with. This document only decides which nodes the steward offers
  to new users, as UN-RFC 0010 section 6 already does.

# 9. Security Considerations

- **Gaming the check.** A node could pass by reading the canary group
  and copying canaries from other nodes. That copy is itself a pull: it
  makes the node connected for canaries and, if it does the same for
  every group, for everything else. A node that copies only canaries
  passes incoming but not completeness, unless it also lists groups it
  does not really carry; the steward cannot prevent such deliberate
  deceit, only make it more work than peering.
- **A hostile majority.** Most listed nodes acting together can fail an
  honest node. They could equally refuse to peer with it. The steward
  sees the matrix and can decide otherwise (UN-RFC 0020 decisions).
- **Load.** One small canary per listed node per day, kept for the
  group's retention: with 200 nodes (the list's maximum), 200 articles
  a day.
- **Privacy.** Canaries reveal that the steward checks a node daily,
  which is public anyway. Comparing `LIST ACTIVE` reveals which groups a
  node carries, which any client can already see.

# 10. Changes to Other Documents

- UN-RFC 0010 section 6: the two conditions of section 7.
- UN-RFC 0011 section 4: the `excludes` field of section 3.
- UN-RFC 0020 section 9: the `disconnected` and `incomplete` fields and
  the extended meaning of "down" (section 7).
- UN-RFC 0000 section 6: 0020 and 0021 are added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
