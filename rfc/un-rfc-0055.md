```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0055                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0001, 0005, 0010, 0011, 0021

               Unseenet: What a Node Carries
```

# Abstract

A node does not have to carry every group. This document lets a node
carry the hierarchies its operator chooses - only `alt.*`, only
`palaestina.*`, only an association's `forening.*` - and say so, in a
`carries` field of its node information and in **announcements** signed
with its node key. A small set of **infrastructure groups**, the
network's own lists of nodes, hierarchies and names, MUST be carried by
every node, so that no node or group of nodes can hide which nodes carry
what. Peers exchange what both carry, clients move a group only to a
node that carries it, and coverage is made visible instead of enforced.
The project's list of known nodes moves to a council (UN-RFC 0054), so
that no single key decides which nodes are listed.

# 1. Motivation

UN-RFC 0001 section 2 starts from a full node, which carries the text of
every ordinary group, and lets a partial node carry less. UN-RFC 0021
lets a listed node leave groups out with `excludes`. Both start from
"everything, except". That works against two things the network needs:

1. **Many nodes.** A node is easiest to run when it carries what its
   operator cares about and nothing they do not want responsibility for.
   Somebody may carry `alt.*` gladly and `dk.*` not at all, or run a node
   only to keep one cause's groups alive. Onion services let operators
   stay unknown; a duty to carry everything turns many would-be operators
   away, and fewer nodes are easier to pressure.
2. **Clients that switch node.** When a node does not answer, a client
   should continue on another of its nodes (unseenet #603). It must only
   choose a node that carries the group, and today it learns that only by
   asking each node.

Leaving a group out is not censorship as long as anybody can carry it
and everybody can see who does. What would be censorship is a node, or
a group of nodes, hiding which nodes carry a group. This document
therefore makes carrying free and the network's own directories
mandatory.

# 2. Terms

- **Pattern list:** an ordered list of RFC 3977 wildmats over group
  *names* (the part of a Group ID before `@`, UN-RFC 0004 section 1). A
  pattern starting with `!` excludes. The last pattern that matches a
  name decides; a name no pattern matches is not carried.
- **Carries:** a node carries a group when the group is an
  infrastructure group (section 4), or its name matches the node's
  pattern list and it is not excluded in some other way this document
  allows (section 3.2).
- **Full node:** a node whose pattern list is `["*"]`.
- **Partial node:** any other node.
- **Infrastructure group:** a group listed in section 4.

The key words "MUST", "SHOULD" and "MAY" are as in UN-RFC 0000
section 2.

# 3. Saying What a Node Carries

## 3.1 The `carries` Field

Node information (UN-RFC 0011 section 3) gets a field `carries`, an
object:

| Field       | Type             | Req. | Meaning                                             |
|-------------|------------------|------|-----------------------------------------------------|
| `groups`    | array of strings | yes  | The pattern list, at most 64 patterns               |
| `files`     | boolean          | no   | Carries blobs (UN-RFC 0027); default `false`        |
| `sites`     | boolean          | no   | Carries site and page groups (UN-RFC 0035); default `false` |
| `closed`    | boolean          | no   | Carries closed groups and private posts (ciphertext); default `true` |
| `key_bound` | string           | no   | `all`, `part` or `none`, as UN-RFC 0040 section 8; default `all` |
| `new`       | boolean          | no   | Picks up new matching groups by itself (UN-RFC 0004 section 3.3); default `true` |

Examples:

```
{"groups": ["*"], "files": true, "sites": true}
{"groups": ["alt.*", "dk.*", "!dk.politik.*"]}
{"groups": ["palaestina.*"], "files": true}
{"groups": ["forening.*"], "closed": true}
```

A node that implements this document MUST give `carries`. A node
information without it is read as `{"groups": ["*"]}`, which is what
nodes did before.

## 3.2 Excluding Single Groups

A node MAY leave out single groups its patterns match, with the
`excludes` field of UN-RFC 0021 section 3: a wildmat over Group IDs.
Patterns are the main tool; `excludes` is for exceptions, such as one
group an operator will not carry for legal reasons in its country.
`excludes` never applies to an infrastructure group, even if it
matches.

## 3.3 Local Groups

Local groups (UN-RFC 0009 section 4) are carried by the node they live
on whatever its patterns, and never by anyone else. They are not
announced.

## 3.4 Changing What a Node Carries

An operator may change the pattern list at any time. A node that stops
carrying a group SHOULD keep answering for it, as "not carried"
(`411`), so that clients learn quickly; it MAY delete what it held.
It announces the change (section 5) within a day.

# 4. Infrastructure Groups

Every node MUST carry these groups, whatever its pattern list, MUST
exchange them with every peer, and MUST NOT refuse or drop a valid
article in them for any reason other than the general limits (UN-RFC
0005 section 6) and postage:

| Group                                   | What it holds                          | Document  |
|-----------------------------------------|----------------------------------------|-----------|
| `unseenet.nodes.announce` (section 5)   | Nodes' own announcements               | this      |
| `unseenet.nodes` and its council successor (section 8) | The project's list of known nodes | 0010 |
| `unseenet.entrances`                    | The list of web entrances              | 0043      |
| `unseenet.gateways`                     | The directory of gateways              | 0038      |
| `unseenet.hierarchies`                  | The root list of hierarchies           | 0018      |
| `unseenet.names`, `unseenet.names.claims` and their council successors | Names and claims | 0019, 0054 |
| `unseenet.announce`, `unseenet.releases` | Announcements and releases            | 0010, 0043 |
| `unseenet.canary`                       | Canary posts that show nodes are connected | 0021  |

The table names groups by name; the Group IDs are those the reference
client pins (UN-RFC 0010 section 6 and the documents named). A later
document MAY add groups to this list; it MUST NOT remove one without
saying where its job went.

They are the network's telephone book. If a node could leave out the
announcements of nodes that carry `palaestina.*`, or the hierarchy that
grants it, it could make those groups hard to find without ever touching
them. Carrying the books costs little: each of these groups is small and
bounded (UN-RFC 0001 section 2, scale), and none grows with the number
of identities.

A node that does not carry them does not conform to this document.
Clients SHOULD NOT rely on such a node as their only source of lists,
and lists of known nodes MUST NOT list it (section 8).

# 5. Node Announcements

## 5.1 The Group

`unseenet.nodes.announce` is an **open council group** (UN-RFC 0054
Part I), so that no single key can change who may announce or what it
costs. Its council is that of the project's node list (section 8). Until
that council is founded, the project creates the group with the project
key and moves it as UN-RFC 0054 section 14 moves the registrar.

Its manifest SHOULD set `min_pow` higher than ordinary groups (UN-RFC
0006), since every node carries it.

## 5.2 An Announcement

A node announces itself by posting an ordinary article with
`Author-Key` its node key (UN-RFC 0016), `Subject: node <name>`,
`Content-Type: application/json` and a canonical JSON body:

| Field     | Type       | Req. | Meaning                                        |
|-----------|------------|------|------------------------------------------------|
| `v`       | integer    | yes  | `1`                                            |
| `address` | string     | yes  | The node's onion address, optionally `:port`   |
| `name`    | string     | yes  | As in node information                         |
| `carries` | object     | yes  | As in section 3.1                              |
| `operator`| key string | no   | As in node information (UN-RFC 0011)           |
| `contact` | Group ID   | no   | As in node information                         |
| `date`    | date       | yes  | RFC 3339 UTC, the article's `Date`             |

A node MUST announce itself when it starts carrying, when `carries`
changes, and at least every 30 days. An announcement nobody has renewed
for 45 days is stale; clients ignore it.

A node does not need anybody's approval to announce itself. An operator
who does not want the node found - a node for a few friends - simply does
not announce it; it still MUST carry the infrastructure groups.

## 5.3 Checking an Announcement

An announcement is only the node's own word, as node information is
(UN-RFC 0011 section 6). Before a client offers or uses an announced
node, it MUST connect to `address` and check that the node information
it gets there gives the same `node_key` as the announcement's
`Author-Key`. The onion address authenticates the node, so this binds
the key to the address; an announcement for somebody else's address
fails.

## 5.4 Keeping the Group Small

A node SHOULD keep only the newest announcement per `Author-Key`, and
MUST keep at least that one until it is stale. Nodes MAY refuse more
than one announcement per `Author-Key` per day (`439`, reason `rate`).

# 6. Peering

The groups a node sends to a peer (UN-RFC 0005 section 5.1) default to
those both carry: the infrastructure groups, plus the groups matching
both nodes' pattern lists. A node learns its peer's pattern list from
the peer's node information when it connects, and again at least daily.

An operator MAY narrow this further per peer, except for infrastructure
groups, which MUST always be sent and taken.

Two nodes with nothing in common but the infrastructure groups - an
`alt.*` node and a `palaestina.*` node - MAY still peer; they then
exchange only the telephone book. Both will usually also peer with a
full node.

# 7. Clients

- **Which node for a group.** When a client looks for a node for a
  group (adding it, or because the group's node does not answer), it
  MUST only choose a node whose `carries` covers the group. It SHOULD
  prefer the user's own nodes, then nodes from its lists, then announced
  nodes it has checked (section 5.3).
- **Not carried anywhere.** If none of the nodes the client knows
  carries a group, the client keeps the group bound to its node and
  shows it as not available right now (unseenet #603), rather than
  moving it.
- **Coverage.** A client SHOULD show, in a group's information, how many
  of the nodes it knows carry the group, and MAY say plainly when it is
  only one. It is information, not a warning.
- **Before choosing a node.** When the user adds a node, the client
  SHOULD show what it carries next to its policy (UN-RFC 0011 section 4).
- **Waiting.** A client MUST NOT let one node that does not answer hold
  up what other nodes have already answered, such as the list of groups.

# 8. The Project's List of Known Nodes

The project's list of known nodes (UN-RFC 0010 section 6) moves to a
**council** as the registrar does (UN-RFC 0054): a `channel` council
group whose members' replicas compute the list from public data and post
the same result. After the move no single key - the project's included -
decides which nodes are listed.

The list says "these are the nodes this council vouches for": a
starting point for new users, no longer the only way to find nodes, since
every node can announce itself (section 5). A listed node:

- MUST carry the infrastructure groups and give `carries`;
- MUST be connected in the sense of UN-RFC 0021, counted over the groups
  it carries;
- need not be a full node.

The rules by which replicas add and remove nodes, and the founding of
the council, are left to a revision of UN-RFC 0020 (unseenet #56). Until
then the list is kept as UN-RFC 0010 section 6 says.

The root list of hierarchies (UN-RFC 0018) goes the same way, and
section 4 explains why it matters less than it seems: the root list does
not decide whether a hierarchy exists or is carried - anybody may create
groups under any name, and nodes carry what their patterns match. It
only records who may speak *for* a hierarchy (its maintainer: blocks,
default spam-report issuers). The direction for that revision
(informative):

- a free top-level hierarchy is claimed like a name (UN-RFC 0054
  section 8: commit, reveal, a ripened key), first claim wins, and is
  renewed or lapses;
- a hierarchy equal to a domain name or a country-code TLD goes only to
  whoever proves it in DNS, as names do (unseenet #590): `dk.*` to whoever
  answers for `.dk`, `torproject.*` to whoever answers for torproject.org;
- a hierarchy without a maintainer is free, like `alt.*`: no blocks
  across it, only each group owner's rules.

# 9. Changes to Other Documents

- **UN-RFC 0001** section 2 (scale) and section 4: a node carries the
  infrastructure groups and the groups its pattern list matches; a full
  node is one whose list is `["*"]`. "A full node carries the text of
  every ordinary group" becomes a definition, not an expectation.
- **UN-RFC 0005** section 5.1: the default set of groups to send and
  take is that of section 6, not `*`; infrastructure groups cannot be
  left out.
- **UN-RFC 0010** section 6: the project's list moves to a council
  (section 8); section 5 gains announced nodes as a further source.
- **UN-RFC 0011** section 3: new field `carries` (section 3.1).
- **UN-RFC 0021**: a listed node must carry the groups the other listed
  nodes carry *that match its own pattern list*; `excludes` is for
  single exceptions (section 3.2) and cannot name an infrastructure group.

# 10. Rationale

- **Why not require full nodes on the list?** Fewer nodes are easier to
  pressure than many. Freedom to carry a part brings in operators who
  would never carry everything, and a group is safest when many small
  nodes carry it because they care about it. What would hurt is not
  knowing who carries a group, which section 4 prevents.
- **Why no "do not carry" for owners?** An open group can always be
  copied by whoever reads it. An owner who wants a group kept to a few
  nodes, or to a few people, makes it closed (UN-RFC 0004); its articles
  are then ciphertext wherever they travel.
- **Why patterns over names, not Group IDs?** Operators choose
  hierarchies, and hierarchies are names (UN-RFC 0018). A name pattern
  covers groups that do not exist yet; Group IDs are kept for the
  exceptions in `excludes`.
- **Why announcements in a council group?** An announcement group owned
  by one key could be closed, or its postage raised until nobody can
  announce, by that key. A council cannot be steered by one member.
- **Why check announcements against node information?** Anybody can post
  an announcement naming any address. Only the node behind the onion
  address can answer with the matching node key.

# 11. Security and Privacy Considerations

- **A node that lies about what it carries** is found out by peers and
  by canaries (UN-RFC 0021) for the groups it claims; clients that find
  a group missing on a node that claims it SHOULD prefer another node.
- **A node that leaves out infrastructure groups** does not conform.
  Because every node carries them and exchanges them with every peer, one
  such node cannot keep them from anyone who has a second node.
- **Fake nodes.** Anybody can run many nodes and announce them. Postage
  and the per-key rate (section 5.4) make the group expensive to flood;
  checking (section 5.3) rules out announcements for addresses one does
  not run. A client SHOULD NOT add announced nodes to the user's vault
  without the user, except as described for failover.
- **What `carries` reveals.** A pattern list tells what the operator
  chooses to carry, nothing about who reads it. An operator who does not
  want even that known does not announce the node.
- **Uptime.** Announcements renewed at least every 30 days at a random
  time do not reveal when a node is up beyond what connecting to it
  already does (UN-RFC 0005 section 7).

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
